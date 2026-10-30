"""Dependency refresh trust boundaries and the pins consumed by packaging."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'packages/bc250-fsr4-common'
spec = importlib.util.spec_from_file_location('updater', ROOT / 'scripts/update-freefg.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class Updates(unittest.TestCase):
    def setUp(self):
        self.pin = json.loads((COMMON / 'freefg-upstream.json').read_text())
        self.recipes = (COMMON / 'freefg-recipes.json').read_bytes()

    def test_offline_check_has_no_network_dependency(self):
        with mock.patch.object(updater, 'fetch', side_effect=AssertionError('Network forbidden')):
            self.assertEqual(len(updater.validate(self.pin, self.recipes)['verified']), 19)

    def test_changed_recipes_fail_checksum_gate(self):
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            updater.validate(self.pin, self.recipes + b' ')

    def test_floating_branch_and_wrong_project_are_refused(self):
        for field, value in [('commit', 'main'), ('url', 'https://example.com/recipes.json')]:
            with self.subTest(field=field):
                pin = copy.deepcopy(self.pin)
                pin['recipes'][field] = value
                with self.assertRaises(ValueError):
                    updater.validate(pin, self.recipes)

    def test_source_companion_cannot_be_another_release(self):
        self.pin['runtime']['source_url'] = self.pin['runtime']['source_url'].replace('1.1.5', '1.1.4')
        with self.assertRaisesRegex(ValueError, 'matching upstream'):
            updater.validate(self.pin, self.recipes)

    def test_schema_change_requires_adapter_update(self):
        data = json.loads(self.recipes)
        data['schema'] = 2
        raw = json.dumps(data).encode()
        self.pin['recipes']['sha256'] = updater.sha(raw)
        with self.assertRaisesRegex(ValueError, 'schema'):
            updater.validate(self.pin, raw)

    def test_refresh_checks_runtime_source_and_ini_together(self):
        source = b'GPL source companion'
        manifest = {'source_archive': {'sha256': updater.sha(source), 'optiscaler_tag_commit': 'a' * 40},
                    'intel_free': True}
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, 'w') as archive:
            archive.writestr('freefg-1.2.3/manifest.json', json.dumps(manifest))
        binary = zipped.getvalue()
        assets = [{'name': name, 'browser_download_url': f'https://github.com/daniel-h-0/freefg/releases/download/v1.2.3/{name}',
                   'id': index, 'digest': 'sha256:' + updater.sha(payload)}
                  for index, (name, payload) in enumerate([('freefg-1.2.3.zip', binary), ('freefg-1.2.3-source.zip', source)])]
        release = {'draft': False, 'prerelease': False, 'assets': assets}
        def fetch(url):
            if '/releases/tags/' in url:
                return json.dumps(release).encode()
            if url.endswith('freefg-1.2.3.zip'):
                return binary
            if url.endswith('freefg-1.2.3-source.zip'):
                return source
            if url.endswith('/' + 'a' * 40 + '/OptiScaler.ini'):
                return b'[FrameGen]\nEnabled=auto\n'
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(updater, 'fetch', side_effect=fetch):
            updater.refresh_runtime(self.pin, '1.2.3', Path(temporary))
            updater.validate(self.pin, self.recipes)
            self.assertEqual(self.pin['runtime']['source_sha256'], updater.sha(source))
            self.assertEqual((Path(temporary) / 'freefg-1.2.3-source.zip').read_bytes(), source)
            assets[1]['digest'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(ValueError, 'GitHub SHA256'):
                updater.refresh_runtime(self.pin, '1.2.3')

    def test_packaging_variables_match_the_dependency_record(self):
        done = subprocess.run(['python3', str(ROOT / 'scripts/update-freefg.py'), '--shell'], capture_output=True, text=True, check=True)
        values = dict(line.split('=', 1) for line in done.stdout.splitlines())
        self.assertEqual(values['FREEFG_VERSION'], self.pin['runtime']['version'])
        self.assertEqual(values['FREEFG_URL'], self.pin['runtime']['url'])
        self.assertEqual(values['FREEFG_SHA256'], self.pin['runtime']['sha256'])
        self.assertEqual(values['FREEFG_INI_SHA256'], self.pin['runtime']['opti_ini_sha256'])

    def test_all_source_fingerprints_cover_adapter_and_upstream_data(self):
        for base in ('ge-proton', 'proton-cachyos'):
            done = subprocess.run(['bash', '-c', 'source "$1"; fsr4_payload_source_paths "$2" "$3"', '_',
                                   str(ROOT / 'scripts/fsr4-payload-sources.sh'), str(ROOT), base],
                                  capture_output=True, text=True, check=True)
            paths = {Path(path).name for path in done.stdout.splitlines()}
            for name in ('bc250_freefg_state.py', 'bc250_freefg_recipes.py', 'freefg-upstream.json',
                         'freefg-recipes.json', 'update-freefg.py'):
                self.assertIn(name, paths)

    def test_retained_recipe_notice_is_present(self):
        self.assertEqual(self.pin['recipes']['license'], 'MIT')
        self.assertIn('Copyright (c) 2026 FreeFG contributors', self.pin['recipes']['notice'])
