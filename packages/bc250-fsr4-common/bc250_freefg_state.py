# SPDX-License-Identifier: MIT
"""Local Proton payload transactions; no game installations or network access.

The launcher holds Session's lock until Proton exits. Patched protonfixes calls
stage_setup() with its real setup routine against a temporary prefix. Only the
three payload locations below are committed. A write-ahead journal lets the next
launch restore the entire previous transaction after interruption.
"""
from __future__ import annotations

import configparser
import copy
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
from urllib.parse import unquote, urlparse

SCHEMA = 1
UMU = Path('drive_c/windows/system32/umu')
DRIVER = Path('drive_c/windows/system32/amdxcffx64.dll')
INI = 'OptiScaler.ini'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def object_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            sync_dir(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def plain(path):
    """Never follow a payload directory or state-file link outside its prefix."""
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError('Refusing symlink in managed path: ' + str(path))
    return path


def clone_file(src, dst):
    # FICLONE on btrfs/XFS, with a normal copy on other prefix filesystems.
    src, dst = Path(src), Path(dst)
    with src.open('rb') as source, dst.open('wb') as target:
        try:
            fcntl.ioctl(target.fileno(), 0x40049409, source.fileno())
        except OSError:
            shutil.copyfileobj(source, target)
        target.flush()
        os.fsync(target.fileno())
    shutil.copystat(src, dst)
    return str(dst)


def clone(src, dst):
    src, dst = Path(src), Path(dst)
    if src.is_symlink():
        raise RuntimeError('Unexpected symlink at payload root: ' + str(src))
    if src.is_dir():
        # Only same-directory DLL proxy links are permitted. Never follow them.
        for path in src.rglob('*'):
            if path.is_symlink():
                target = os.readlink(path)
                if '/' in target or '\\' in target or target in ('', '.', '..') or not (path.parent / target).is_file() or (path.parent / target).is_symlink():
                    raise RuntimeError('Unsafe payload link: ' + str(path))
        shutil.copytree(src, dst, symlinks=True, copy_function=clone_file)
    elif src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        clone_file(src, dst)


def remove(path):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def parse_ini(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def values(text):
    parser = parse_ini(text)
    return {f'{section}.{key}'.lower(): value for section in parser.sections()
            for key, value in parser[section].items()}


def ini_files(root):
    result = {}
    if root.is_dir():
        for path in sorted(root.rglob('*')):
            if path.suffix.lower() == '.ini' and path.is_file():
                plain(path)
                text = path.read_bytes().decode('utf-8-sig')
                values(text)  # a damaged INI is a conflict, never a reset
                result[path.relative_to(root).as_posix()] = text
    return result


def merge_ini(template, desired, overrides, previous=""):
    """Merge values while retaining the player's comments, order and newlines."""
    template_parser = parse_ini(template)
    base = previous or template
    base_parser = parse_ini(base)
    locations = {f'{section}.{key}'.lower(): (section, key)
                 for parser in (base_parser, template_parser)
                 for section in parser.sections() for key in parser[section]}
    changes = {**values(template), **{k.lower(): v for k, v in desired.items()}, **{k.lower(): v for k, v in overrides.items()}}
    # Explicit keys retain their spelling when a template has not defined them.
    for key in desired:
        locations.setdefault(key.lower(), tuple(key.split('.', 1)))
    lines = base.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in base else '\n'
    section_pattern = re.compile(r'^\s*\[([^]]+)\]')
    option_pattern = re.compile(r'^(\s*)([^#;\s][^=:]*?)(\s*[=:]\s*)(.*?)(\r?\n)?$')
    for key, value in changes.items():
        current = values(''.join(lines))
        if key in current and current[key] == value or key not in current and value is None:
            continue
        section, option = locations.get(key, key.split('.', 1))
        active, start, end, found = None, None, len(lines), None
        for index, line in enumerate(lines):
            heading = section_pattern.match(line)
            if heading:
                if start is not None:
                    end = index
                    break
                active = heading.group(1)
                if active.lower() == section.lower():
                    start = index
                continue
            parsed = option_pattern.match(line)
            if active and active.lower() == section.lower() and parsed and parsed.group(2).strip().lower() == option.lower():
                found = (index, parsed)
        if found:
            index, parsed = found
            stop = index + 1
            while stop < end and lines[stop].strip() and lines[stop][:1].isspace() and not section_pattern.match(lines[stop]) and not option_pattern.match(lines[stop]) and not lines[stop].lstrip().startswith(('#', ';')):
                stop += 1
            replacement = [] if value is None else [parsed.group(1) + parsed.group(2) + parsed.group(3) + str(value).replace('\n', newline + '    ') + newline]
            lines[index:stop] = replacement
        elif value is not None:
            if lines and not lines[-1].endswith(('\n', '\r')):
                lines[-1] += newline
            if start is None:
                lines.extend([newline + '[' + section + ']' + newline, option + '=' + str(value).replace('\n', newline + '    ') + newline])
            else:
                lines.insert(end, option + '=' + str(value).replace('\n', newline + '    ') + newline)
    result = ''.join(lines)
    parse_ini(result)
    return result


def capture(profile, texts):
    """Observe edits, including deletions, against what the last launch wrote."""
    overrides = profile.setdefault('overrides', {})
    for name in set(texts) | set(profile.get('applied', {})):
        current = values(texts.get(name, ''))
        applied = profile.get('applied', {}).get(name, {})
        target = overrides.setdefault(name, {})
        for key in set(current) | set(applied):
            if current.get(key) != applied.get(key):
                target[key] = current.get(key)
    profile['last'] = texts


def archive_path(manifest, entry):
    uri = urlparse(entry['download_url'])
    if uri.scheme == 'file' and uri.netloc in ('', 'localhost'):
        path = Path(unquote(uri.path))
    elif not uri.scheme and not uri.netloc:
        relative = Path(unquote(uri.path))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest artifact path')
        path = Path(manifest).parent / relative
    else:
        raise ValueError('Recovery requires a local pinned artifact')
    if uri.query or uri.fragment or path.is_symlink() or digest(path) != entry['zip_sha256_hash']:
        raise ValueError('Recovery artifact checksum mismatch: ' + str(path))
    return path



def read_generation(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('Invalid retained generation identity')
    record = read_json(plain(Path(root) / 'generations' / identity / 'record.json'))
    if record is None or object_id(record) != identity:
        raise ValueError('Retained generation metadata differs from its identity')
    return record


def verify_bundle(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('Invalid retained bundle identity')
    path = plain(Path(root) / 'bundles' / identity)
    record = read_json(plain(path / 'identity.json'))
    if record is None or object_id(record) != identity:
        raise ValueError('Retained bundle metadata differs from its identity')
    expected = copy.deepcopy(record['manifest'])
    for entries in expected.values():
        for entry in entries:
            suffix = ''.join(Path(unquote(urlparse(entry['download_url']).path)).suffixes)
            entry['download_url'] = entry['zip_sha256_hash'] + suffix
    config = copy.deepcopy(record['config'])
    config['manifest'] = 'manifest.json'
    if read_json(plain(path / 'manifest.json')) != expected or read_json(plain(path / 'config.json')) != config:
        raise ValueError('Retained manifest/config differs from its package identity')
    if record.get('upstream') and digest(plain(path / 'freefg-recipes.json')) != record['upstream']['recipes']['sha256']:
        raise ValueError('Retained recipe snapshot differs from its package identity')
    return path


def retain_bundle(root, tool, config, version, provider):
    """Save only selected payloads; package upgrades cannot remove rollback inputs."""
    manifest_path = Path(tool) / config['manifest']
    manifest = read_json(manifest_path)
    selected = {}
    for key, entries in manifest.items():
        requested = version if key == 'optiscaler' else provider
        matches = [entry for entry in entries if entry['version'] == requested]
        if requested in ('1', 'default') and len(entries) == 1:
            matches = entries
        if key == 'optiscaler' and version == '0':
            continue
        if key != 'optiscaler' and provider == '0':
            continue
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous recovery payload: ' + key)
        selected[key] = copy.deepcopy(matches)
    upstream = config.get('freefg_upstream')
    record = {'config': config, 'manifest': copy.deepcopy(selected), 'upstream': upstream,
              'version': version, 'provider': provider}
    identity = object_id(record)
    destination = root / 'bundles' / identity
    if destination.is_dir():
        verify_bundle(root, identity)
        return identity
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.bundle-') as temporary:
        stage = Path(temporary)
        for entries in selected.values():
            for entry in entries:
                source = archive_path(manifest_path, entry)
                name = entry['zip_sha256_hash'] + ''.join(source.suffixes)
                clone(source, stage / name)
                entry['download_url'] = name
        if upstream:
            source = Path(tool) / 'freefg-recipes.json'
            if digest(source) != upstream['recipes']['sha256']:
                raise ValueError('Recipe data differs from package pin')
            clone(source, stage / 'freefg-recipes.json')
        retained = copy.deepcopy(config)
        retained['manifest'] = 'manifest.json'
        write_json(stage / 'manifest.json', selected)
        write_json(stage / 'config.json', retained)
        write_json(stage / 'identity.json', record)
        os.rename(stage, destination)
        sync_dir(destination.parent)
    return identity


class Session:
    def __init__(self, prefix, compat):
        self.prefix = Path(prefix).resolve()
        self.compat = Path(compat).resolve()
        self.root = plain(self.prefix / '.bc250-freefg')
        self.targets = [plain(self.prefix / UMU), plain(self.prefix / DRIVER),
                        plain(self.compat / 'upscaler_files')]
        self.fd = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = plain(self.root / 'session.lock')
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError('Another game or recovery operation is using this Wine prefix')
        try:
            self.recover()
            self.reload()
            self.observe()
            return self
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def __exit__(self, *exc):
        try:
            self.reload()
            self.observe()
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None

    def reload(self):
        self.state = read_json(plain(self.root / 'state.json'), {'schema': SCHEMA, 'games': {}, 'active': None})
        if self.state.get('schema') != SCHEMA:
            raise ValueError('Unsupported FreeFG recovery state')

    def observe(self):
        key = self.state.get('active')
        if key in self.state['games']:
            capture(self.state['games'][key], ini_files(self.targets[0]))
            write_json(self.root / 'state.json', self.state)

    def profile(self, key):
        return self.state['games'].setdefault(key, {'history': [], 'pin': None, 'overrides': {}, 'applied': {}, 'last': {}, 'adopted': False})

    def snapshot(self, destination):
        destination.mkdir(parents=True, exist_ok=True)
        present = []
        for index, path in enumerate(self.targets):
            plain(path)
            present.append(path.exists())
            if path.exists():
                clone(path, destination / str(index))
        write_json(destination / 'present.json', present)

    def install_image(self, source):
        present = read_json(source / 'present.json')
        for index, target in enumerate(self.targets):
            plain(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.parent / ('.bc250-restore-' + target.name)
            remove(temporary)
            if present[index]:
                clone(source / str(index), temporary)
            remove(target)
            if present[index]:
                os.rename(temporary, target)
            sync_dir(target.parent)

    def recover(self):
        journal = plain(self.root / 'journal')
        if not journal.exists():
            return
        before = read_json(journal / 'before.json')
        if before is None:
            raise RuntimeError('Incomplete FreeFG recovery journal; manual recovery required')
        self.install_image(journal / 'image')
        if before['state'] is None:
            (self.root / 'state.json').unlink(missing_ok=True)
        else:
            write_json(self.root / 'state.json', before['state'])
        # Rename is the completion marker. A crash before it repeats recovery.
        done = self.root / 'recovered-journal'
        remove(done)
        os.rename(journal, done)
        sync_dir(self.root)
        remove(done)

    def commit(self, image, state):
        with tempfile.TemporaryDirectory(dir=self.root, prefix='.journal-') as temporary:
            journal = Path(temporary)
            self.snapshot(journal / 'image')
            write_json(journal / 'before.json', {'state': read_json(self.root / 'state.json')})
            os.rename(journal, self.root / 'journal')
            sync_dir(self.root)
        try:
            self.install_image(image)
            write_json(self.root / 'state.json', state)
            done = self.root / 'committed-journal'
            remove(done)
            os.rename(self.root / 'journal', done)
            sync_dir(self.root)
            remove(done)
        except BaseException:
            self.recover()
            raise
        self.state = state

    def status(self, key):
        profile = self.state['games'].get(key, {})
        current = profile.get('current')
        generation = read_generation(self.root, current) if current else None
        return {'game': key, 'active_game': self.state.get('active'), 'generation': current,
                'pinned': bool(profile.get('pin')), 'history': profile.get('history', []),
                'overrides': profile.get('overrides', {}), 'adopted_recipe': profile.get('adopted', False),
                'details': generation, 'project': 'https://github.com/daniel-h-0/freefg'}

    def action(self, key, action):
        if action == 'status':
            return self.status(key)
        profile = self.state['games'].get(key)
        if not profile:
            raise RuntimeError('No managed generation for this game')
        if action == 'update':
            profile['pin'] = None
        elif action == 'recommend':
            # Only recipe/default keys are relinquished, never unrelated settings.
            current = read_generation(self.root, profile['current'])
            for name, settings in current.get('desired', {}).items():
                for option in settings:
                    profile.get('overrides', {}).get(name, {}).pop(option.lower(), None)
            profile['adopted'] = True
        elif action == 'rollback':
            history = profile['history']
            current = profile['current']
            position = history.index(current)
            if position == 0:
                raise RuntimeError('No older retained generation for this game')
            previous = history[position - 1]
            profile['pin'] = previous
            # Actual restore uses the same staged path on the next launch. No
            # half-rollback: the running game's payload is never changed here.
        else:
            raise ValueError('Unknown recovery action: ' + action)
        write_json(self.root / 'state.json', self.state)
        return {**self.status(key), 'pending': action, 'applies': 'next game launch'}

    def plan(self, tool, config, game, version, provider, desired, explicit, recipe, retained=None):
        profile = self.profile(game['key'])
        if not profile['history']:
            legacy = not self.state.get('active') and self.targets[0].exists()
            if legacy:
                texts = ini_files(self.targets[0])
                profile['overrides'] = {name: values(text) for name, text in texts.items()}
                profile['last'] = texts
                baseline = self.root / 'baseline'
                if not baseline.exists():
                    self.snapshot(baseline)
            else:
                profile['adopted'] = True
        bundle = retained or retain_bundle(self.root, tool, config, version, provider)
        # Desired settings retain original spelling for INI sections.
        plan = {'schema': SCHEMA, 'prefix': str(self.prefix), 'compat': str(self.compat),
                'game': game, 'bundle': bundle, 'version': version, 'provider': provider,
                'desired': {INI: desired}, 'explicit': {INI: explicit}, 'recipe': recipe,
                'root': str(self.root)}
        write_json(self.root / 'state.json', self.state)
        write_json(self.root / 'plan.json', plan)
        return self.root / 'plan.json'


def file_hashes(root):
    result = {}
    if root.is_dir():
        for path in root.rglob('*'):
            if path.is_file() and path.suffix.lower() != '.ini':
                result[path.relative_to(root).as_posix()] = ('link:' + os.readlink(path)) if path.is_symlink() else digest(path)
    return result


def stage_setup(setup, compat_config, env, compat_dir, prefix_dir):
    """Run the original upstream setup against a candidate, then commit it."""
    plan_path = Path(env['BC250_FREEFG_PLAN'])
    plan = read_json(plain(plan_path))
    session = Session(prefix_dir, compat_dir)
    if plan['schema'] != SCHEMA or plan['prefix'] != str(session.prefix) or plan['compat'] != str(session.compat) or plan_path != session.root / 'plan.json':
        raise RuntimeError('FreeFG launch plan does not match this prefix')
    # The wrapper owns the session lock; recursively taking it here would fail.
    session.reload()
    profile = session.profile(plan['game']['key'])
    bundle = verify_bundle(session.root, plan['bundle'])
    local_env = dict(env)
    local_env.pop('BC250_FREEFG_PLAN')
    local_env['PROTON_UPSCALER_MANIFEST'] = str(bundle / 'manifest.json')
    # Settings are merged after extraction. Upstream must not seed over edits.
    local_env['PROTON_OPTISCALER_CONFIG'] = ''
    with tempfile.TemporaryDirectory(dir=session.root, prefix='.stage-') as temporary:
        stage = Path(temporary)
        staged_prefix, staged_compat = stage / 'pfx', stage / 'compat'
        staged_prefix.mkdir()
        staged_compat.mkdir()
        payload = staged_prefix / UMU
        payload.parent.mkdir(parents=True)
        if session.targets[0].exists():
            clone(session.targets[0], payload)
        else:
            payload.mkdir()
        old_hashes = file_hashes(payload)
        active = session.state['games'].get(session.state.get('active'), {})
        old_generation = session.state.get('installed') or active.get('current')
        old_record = read_generation(session.root, old_generation) if old_generation else {}
        opti_enabled = 'optiscaler' in compat_config
        managed = old_record.get('files', {})
        old_driver = old_record.get('driver')
        driver_path = session.targets[1]
        driver_owned = False
        if driver_path.exists():
            if old_driver:
                driver_owned = digest(driver_path) == old_driver
                if not driver_owned:
                    raise RuntimeError('Locally modified managed FSR4 driver')
            else:
                tracked_driver = read_json(session.targets[2], {}).get('fsr4_files', {}).get(DRIVER.as_posix())
                if tracked_driver:
                    driver_owned = hashlib.md5(driver_path.read_bytes()).hexdigest() == tracked_driver.get('md5_hash')
                    if not driver_owned:
                        raise RuntimeError('Locally modified legacy FSR4 driver')
        if not managed:
            # Conservative adoption of protonfixes' old, per-file ownership.
            tracked = read_json(session.targets[2], {}).get('opti_files', {})
            for name, record in tracked.items():
                relative = Path(name)
                if not relative.is_relative_to(UMU) or '..' in relative.parts:
                    raise ValueError('Unsafe legacy tracking path')
                relative = relative.relative_to(UMU).as_posix()
                path = payload / relative
                if path.is_file() and path.suffix.lower() != '.ini':
                    if hashlib.md5(path.read_bytes()).hexdigest() != record.get('md5_hash'):
                        raise RuntimeError('Locally modified legacy payload: ' + relative)
                    managed[relative] = old_hashes[relative]
        same_payload = (old_record.get('bundle') == plan['bundle'] and
                        old_record.get('version') == plan['version'] and
                        old_record.get('provider') == plan['provider'])
        for name, checksum in managed.items():
            if name in old_hashes and old_hashes[name] != checksum:
                raise RuntimeError('Locally modified managed payload: ' + name)
            if opti_enabled and not same_payload:
                remove(payload / name)
        # Reuse a verified payload on an ordinary launch. The original INI
        # templates are retained separately from the last player's settings.
        if same_payload or not opti_enabled:
            if session.targets[2].exists():
                clone(session.targets[2], staged_compat / 'upscaler_files')
            if session.targets[1].exists():
                clone(session.targets[1], staged_prefix / DRIVER)
        else:
            for name in ini_files(payload):
                (payload / name).unlink()
        before_unknown = {name: checksum for name, checksum in file_hashes(payload).items()
                          if name not in managed}
        setup(compat_config, local_env, str(staged_compat), str(staged_prefix))
        for name, checksum in before_unknown.items():
            path = payload / name
            now = ('link:' + os.readlink(path)) if path.is_symlink() else (digest(path) if path.is_file() else None)
            if now != checksum:
                raise RuntimeError('New payload would overwrite an unowned file: ' + name)
        candidate_driver = staged_prefix / DRIVER
        if driver_path.exists() and candidate_driver.exists() and not driver_owned and digest(driver_path) != digest(candidate_driver):
            raise RuntimeError('New payload would overwrite an unowned FSR4 driver')
        templates = old_record['templates'] if same_payload else ini_files(payload)
        if opti_enabled:
            # Even an unchanged payload may be entering a different logical
            # game in a shared prefix. Its predecessor's generated INIs are
            # retained in that game's profile, not leaked into this one.
            for name in ini_files(payload):
                (payload / name).unlink()
        desired = plan['desired']
        # Wiring remains part of the desired baseline. A player override wins;
        # explicit menu and launch options are the final layer for this launch.
        for name in (set(templates) | set(profile.get('last', {}))) if opti_enabled else ():
            template = templates.get(name, profile['last'].get(name, ''))
            merged = merge_ini(template, desired.get(name, {}), profile.get('overrides', {}).get(name, {}), profile.get('last', {}).get(name, ''))
            merged = merge_ini(merged, plan['explicit'].get(name, {}), {})
            path = payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(merged)
        texts = ini_files(payload)
        record = {k: plan[k] for k in ('bundle', 'version', 'provider', 'game', 'desired', 'recipe')}
        record['files'] = {name: checksum for name, checksum in file_hashes(payload).items() if name not in before_unknown}
        record['templates'] = templates
        record['driver'] = digest(candidate_driver) if candidate_driver.exists() else old_driver
        generation = object_id(record)
        saved = session.root / 'generations' / generation
        if not saved.exists():
            saved.mkdir(parents=True)
            write_json(saved / 'record.json', record)
        if generation not in profile['history']:
            profile['history'].append(generation)
        profile['current'] = generation
        if opti_enabled:
            profile['applied'] = {name: values(text) for name, text in texts.items()}
            profile['last'] = texts
            session.state['active'] = plan['game']['key']
        session.state['installed'] = generation
        image = stage / 'image'
        image.mkdir()
        os.rename(payload, image / '0')
        if (staged_prefix / DRIVER).exists():
            os.rename(staged_prefix / DRIVER, image / '1')
        elif session.targets[1].exists():
            clone(session.targets[1], image / '1')
        if (staged_compat / 'upscaler_files').exists():
            os.rename(staged_compat / 'upscaler_files', image / '2')
        write_json(image / 'present.json', [(image / str(i)).exists() for i in range(3)])
        session.commit(image, session.state)
        # Propagate only the loader decisions made by the actual Proton base.
        for name in ('WINE_OPTISCALER_NAME', 'WINE_UPSCALER_REPLACE', 'DXVK_NVAPI_DRS_SETTINGS'):
            if name in local_env:
                env[name] = local_env[name]
