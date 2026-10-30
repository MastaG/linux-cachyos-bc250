#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reviewable FreeFG dependency refresh for the Proton packages, never at launch.

No FreeFG installer is imported or run. Runtime, source companion and OptiScaler
INI are validated independently; recipes are imported unchanged at a commit pin.
Use --download-dir to retain the exact inputs for a maintainer's release mirror.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import urllib.error
import urllib.request
import zipfile

REPO = 'daniel-h-0/freefg'
API = 'https://api.github.com/repos/' + REPO
RAW = 'https://raw.githubusercontent.com/' + REPO
SHA = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'bc250-freefg-dependency-refresh',
                                                 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def asset_bytes(asset):
    try:
        data = fetch(asset['browser_download_url'])
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403, 404):
            raise
        # Some GitHub proxies/connectors cannot follow release download URLs.
        # gh uses the authenticated release-asset API; no token enters output.
        result = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/assets/{asset["id"]}',
                                 '-H', 'Accept: application/octet-stream'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        data = result.stdout
    expected = asset.get('digest', '')
    if not expected.startswith('sha256:') or sha(data) != expected[7:]:
        raise ValueError('Missing/mismatched GitHub SHA256 for ' + asset['name'])
    return data


def archive_manifest(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist()
                 if name.endswith('/manifest.json') or name == 'manifest.json']
        # A runtime has one top-level package manifest; nested data files may
        # use the same basename, so select the shallowest unambiguously.
        depth = min(name.count('/') for name in names) if names else -1
        names = [name for name in names if name.count('/') == depth]
        if len(names) != 1:
            raise ValueError('Ambiguous/missing FreeFG package manifest')
        entry = archive.getinfo(names[0])
        if entry.file_size > 5_000_000:
            raise ValueError('Unreasonable package manifest size')
        return json.loads(archive.read(entry))


def validate(lock, recipes, planner=None):
    if lock.get('schema') != 1 or lock.get('adapter') != 1:
        raise ValueError('Unsupported FreeFG dependency schema')
    runtime, recipe = lock['runtime'], lock['recipes']
    if not VERSION.fullmatch(runtime['version']) or not COMMIT.fullmatch(recipe['commit']):
        raise ValueError('Runtime needs a release version; recipes need a full commit')
    for value in (runtime['sha256'], runtime['source_sha256'], runtime['opti_ini_sha256'], recipe['sha256']):
        if not SHA.fullmatch(value):
            raise ValueError('Invalid dependency SHA256')
    base = f'https://github.com/{REPO}/releases/download/v{runtime["version"]}/'
    if runtime['url'] != base + f'freefg-{runtime["version"]}.zip' or runtime['source_url'] != base + f'freefg-{runtime["version"]}-source.zip':
        raise ValueError('Runtime/source must name matching upstream release assets')
    if recipe['url'] != RAW + '/' + recipe['commit'] + '/packaging/recipes/recipes.json':
        raise ValueError('Recipes must name the immutable upstream path')
    if recipe['schema'] != 1 or recipe['file'] != 'freefg-recipes.json':
        raise ValueError('Unsupported recipe layout')
    if not re.fullmatch(r'https://raw\.githubusercontent\.com/daniel-h-0/OptiScaler/[0-9a-f]{40}/OptiScaler\.ini', runtime['opti_ini_url']):
        raise ValueError('OptiScaler INI needs its own immutable source pin')
    if sha(recipes) != recipe['sha256']:
        raise ValueError('Recipe snapshot differs from its dependency pin')
    if lock.get('planner'):
        pin = lock['planner']
        if pin.get('format') != 1 or pin.get('file') != 'freefg_compat.py' or not COMMIT.fullmatch(pin['commit']):
            raise ValueError('Unsupported shared planner pin')
        if pin['url'] != RAW + '/' + pin['commit'] + '/packaging/compat.py' or not SHA.fullmatch(pin['sha256']):
            raise ValueError('Planner needs an immutable FreeFG source pin')
        if planner is not None and sha(planner) != pin['sha256']:
            raise ValueError('Shared planner differs from its dependency pin')
    data = json.loads(recipes)
    if data.get('schema') != 1 or not isinstance(data.get('verified'), list):
        raise ValueError('Unsupported recipe schema')
    for row in data['verified']:
        if row.get('route') not in ('opti', 'native') or row.get('fg_input') not in ('upscaler', 'dlssg', 'fsrfg', 'fsrfg30', None):
            raise ValueError('Recipe semantics require an adapter update')
    return data


def refresh_runtime(lock, version, download_dir=None):
    if not VERSION.fullmatch(version):
        raise ValueError('Expected a numeric FreeFG release version')
    release = json.loads(fetch(API + '/releases/tags/v' + version))
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('Dependency refresh requires a published stable release')
    assets = {asset['name']: asset for asset in release['assets']}
    binary_name, source_name = f'freefg-{version}.zip', f'freefg-{version}-source.zip'
    binary = asset_bytes(assets[binary_name])
    manifest = archive_manifest(binary)
    source = asset_bytes(assets[source_name])
    if manifest['source_archive']['sha256'] != sha(source):
        raise ValueError('Source companion differs from runtime provenance')
    commit = manifest['source_archive']['optiscaler_tag_commit']
    if not COMMIT.fullmatch(commit):
        raise ValueError('Missing exact OptiScaler source identity')
    ini_url = f'https://raw.githubusercontent.com/daniel-h-0/OptiScaler/{commit}/OptiScaler.ini'
    ini = fetch(ini_url)
    # Confirm both the expected config format and that this is the public proxy
    # layout our builder consumes. Changed layouts require adapter work.
    if b'[FrameGen]' not in ini or not manifest.get('intel_free'):
        raise ValueError('Unsupported FreeFG runtime/OptiScaler layout')
    lock['runtime'] = dict(version=version, url=assets[binary_name]['browser_download_url'],
                           sha256=sha(binary), source_url=assets[source_name]['browser_download_url'],
                           source_sha256=sha(source), opti_ini_url=ini_url,
                           opti_ini_sha256=sha(ini), optiscaler_commit=commit)
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        for name, data in ((binary_name, binary), (source_name, source), ('FreeFG-OptiScaler.ini', ini)):
            (download_dir / name).write_bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true', help='validate committed pins offline (default)')
    parser.add_argument('--shell', action='store_true', help='emit validated shell-quoted packaging variables')
    parser.add_argument('--runtime-version', help='refresh from this published FreeFG release')
    parser.add_argument('--recipes-commit', help='refresh unchanged recipe data at this 40-character commit')
    parser.add_argument('--download-dir', type=Path, help='retain verified runtime and GPL source companion for mirroring')
    parser.add_argument('--dry-run', action='store_true', help='print proposed pins without changing the checkout')
    args = parser.parse_args(argv)
    common = args.root / 'packages/bc250-fsr4-common'
    pin_path, recipe_path = common / 'freefg-upstream.json', common / 'freefg-recipes.json'
    lock, recipes = json.loads(pin_path.read_text()), recipe_path.read_bytes()
    planner_path = common / 'freefg_compat.py'
    planner = planner_path.read_bytes() if lock.get('planner') else None
    validate(lock, recipes, planner)
    if args.runtime_version:
        refresh_runtime(lock, args.runtime_version, args.download_dir)
    if args.recipes_commit:
        if not COMMIT.fullmatch(args.recipes_commit):
            raise ValueError('Recipe refresh requires an exact 40-character commit')
        url = RAW + '/' + args.recipes_commit + '/packaging/recipes/recipes.json'
        recipes = fetch(url)
        lock['recipes'].update(commit=args.recipes_commit, url=url, sha256=sha(recipes))
        planner_url = RAW + '/' + args.recipes_commit + '/packaging/compat.py'
        planner = fetch(planner_url)
        if b'WIKI_PLAN_FORMAT = 1' not in planner:
            raise ValueError('Recipe revision lacks the supported shared planner API')
        lock['planner'] = dict(format=1, commit=args.recipes_commit, url=planner_url, sha256=sha(planner), file='freefg_compat.py',
                               license='MIT', notice=lock['recipes']['notice'])
    data = validate(lock, recipes, planner)
    if args.shell:
        if args.runtime_version or args.recipes_commit:
            raise ValueError('--shell cannot refresh dependencies')
        runtime = lock['runtime']
        for name, value in [('VERSION', runtime['version']), ('URL', runtime['url']), ('SHA256', runtime['sha256']),
                            ('INI_URL', runtime['opti_ini_url']), ('INI_SHA256', runtime['opti_ini_sha256'])]:
            print('FREEFG_' + name + '=' + shlex.quote(value))
        return 0
    if args.runtime_version or args.recipes_commit:
        if not args.dry_run:
            # A partial write fails closed at the checksum gate. No installed
            # package or prefix is touched; git records both reviewable changes.
            recipe_path.write_bytes(recipes)
            if planner is not None:planner_path.write_bytes(planner)
            pin_path.write_text(json.dumps(lock, indent=2) + '\n')
        print(json.dumps(lock, indent=2))
    else:
        print(f'FreeFG {lock["runtime"]["version"]}; recipes {lock["recipes"]["commit"]}: {len(data["verified"])} curated rows; pins valid')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit('FreeFG dependency refresh: ' + str(error))
