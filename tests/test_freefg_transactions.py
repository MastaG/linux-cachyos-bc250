"""Exercise real patched GE/CachyOS setup against disposable shared prefixes."""
import copy
import io
import tarfile
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_fsr4_runtime as fixtures
from test_fsr4_runtime import COMMON, wrapper, STUB_INI

sys.path.insert(0, str(COMMON))
import bc250_freefg_state as state
import bc250_freefg_recipes as recipes


class TransactionTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.RuntimeTests.setUpClass.__func__)
    upscalers_module = fixtures.RuntimeTests.upscalers_module

    def setUp(self):
        fixtures.RuntimeTests.setUp(self)
        self.config['proton'] = 'unused-proton'
        self.config['preset']['FrameGen.Enabled'] = 'true'
        self.config['freefg_upstream'] = json.loads((COMMON / 'freefg-upstream.json').read_text())
        for name in ('freefg-recipes.json', 'bc250_freefg_state.py'):
            shutil.copy2(COMMON / name, self.work / name)
        self.env = {'SteamAppId': '1836730', 'SteamGameId': '1836730',
                    'STEAM_COMPAT_DATA_PATH': str(self.compat), 'WINEPREFIX': str(self.prefix),
                    'HOME': str(self.work), 'PROTON_OPTISCALER_MENU': '0'}
        self.args = ['waitforexitandrun', '/Games/Echo Point Nova/Greylock-Win64-Shipping.exe']
        self.base = 'ge-proton'
        self.change = None
        self.stage_failure = None
        # What the menu answers (variant, change, switched); menu_env is what it was given.
        self.menu = (None, {}, False)
        self.menu_env = None

    def launch(self, **env):
        inherited = {**self.env, **env}
        module = self.upscalers_module(self.base)
        original = module.setup_upscalers
        if self.stage_failure:
            # Only fail inside the staging recursion, after it writes something.
            def setup(features, effective, compat, prefix):
                if 'BC250_FREEFG_PLAN' not in effective:
                    (Path(prefix) / 'partial-update').write_text('partial')
                    raise RuntimeError(self.stage_failure)
                return original(features, effective, compat, prefix)
            module.setup_upscalers = setup
        def run(proton, arguments, effective, lock):
            self.last_env, self.last_args = effective, arguments
            with self.assertRaisesRegex(RuntimeError, 'Another game'):
                with state.Session(self.prefix, self.compat):
                    pass
            features = {feature for key, feature in [('PROTON_FSR4_UPGRADE', 'fsr4'),
                        ('PROTON_USE_OPTISCALER', 'optiscaler')] if effective.get(key, '0') != '0'}
            module.setup_upscalers(features, effective, str(self.compat), str(self.prefix))
            if self.change:
                self.change()
            return 0
        def menu(config, launch, menu_tool=None):
            self.menu_env = launch
            variant, change, switched = self.menu
            return variant, dict(change), switched
        with mock.patch.object(wrapper, 'TOOL', self.work), \
             mock.patch.object(wrapper, 'menu_choice', side_effect=menu), \
             mock.patch.object(wrapper, 'supervised', side_effect=run), \
             mock.patch.object(module.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')):
            return wrapper.managed_launch(self.config, self.args, inherited)

    def ini(self):
        return self.prefix / state.UMU / state.INI

    def edit(self, key, value):
        self.ini().write_text(state.merge_ini(self.ini().read_text(), {key: value}, {}))

    def setting(self, key):
        return state.values(self.ini().read_text()).get(key.lower())

    def action(self, action, appid='1836730'):
        with state.Session(self.prefix, self.compat) as session:
            return session.action('steam:' + appid, action)

    def test_default_on_and_overlay_off_survives(self):
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.edit('FrameGen.Enabled', 'false')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')
        self.assertEqual(self.save.read_bytes(), b'preserve existing progress')

    def test_variant_switch_preserves_saved_settings(self):
        self.launch()
        self.edit('XeFG.InterpolationCount', '3')
        self.edit('Spoofing.Dxgi', 'true')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual((self.ini().parent / 'winmm.dll').read_bytes(), self.variant['winmm.dll'])
        self.assertEqual(self.setting('XeFG.InterpolationCount'), '3')
        self.assertEqual(self.setting('Spoofing.Dxgi'), 'true')
        self.launch(PROTON_USE_OPTISCALER='1')
        self.assertEqual(self.setting('XeFG.InterpolationCount'), '3')

    def test_explicit_launch_override_is_temporary(self):
        self.launch()
        self.edit('FrameGen.Enabled', 'false')
        self.launch(BC250_OPTISCALER_EXTRA='FrameGen.Enabled=true')
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')

    def test_shared_prefix_keeps_two_independent_profiles(self):
        self.launch()
        self.edit('FrameGen.Enabled', 'false')
        self.edit('XeFG.InterpolationCount', '3')
        self.launch(SteamAppId='222', SteamGameId='222')
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.assertEqual(self.setting('XeFG.InterpolationCount'), 'auto')
        self.edit('Spoofing.Dxgi', 'true')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')
        self.assertEqual(self.setting('XeFG.InterpolationCount'), '3')
        self.assertEqual(self.setting('Spoofing.Dxgi'), 'false')
        self.launch(SteamAppId='222', SteamGameId='222')
        self.assertEqual(self.setting('Spoofing.Dxgi'), 'true')

    def test_changed_default_updates_only_owned_values(self):
        self.launch()
        self.edit('Spoofing.Dxgi', 'true')
        self.config['preset']['FrameGen.Enabled'] = 'false'
        self.config['preset']['Spoofing.Dxgi'] = 'auto'
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')
        self.assertEqual(self.setting('Spoofing.Dxgi'), 'true')

    def test_existing_ini_adoption_preserves_even_auto(self):
        self.ini().parent.mkdir(parents=True)
        self.ini().write_bytes(STUB_INI)
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'auto')
        self.assertFalse(self.action('status')['adopted_recipe'])
        self.action('recommend')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')

    def test_failure_in_stage_does_not_mutate_payload_or_tracking(self):
        self.launch()
        before = self.ini().read_bytes()
        tracked = (self.compat / 'upscaler_files').read_bytes()
        dll = (self.ini().parent / 'winmm.dll').read_bytes()
        self.stage_failure = 'injected staging failure'
        with self.assertRaisesRegex(RuntimeError, self.stage_failure):
            self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(before, self.ini().read_bytes())
        self.assertEqual(tracked, (self.compat / 'upscaler_files').read_bytes())
        self.assertEqual(dll, (self.ini().parent / 'winmm.dll').read_bytes())
        self.assertFalse((self.prefix / 'partial-update').exists())

    def test_rollback_retains_payload_after_package_files_are_removed(self):
        self.launch()
        initial = self.action('status')['generation']
        self.config['preset']['FrameGen.Enabled'] = 'false'
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.edit('XeFG.InterpolationCount', '3')
        self.action('rollback')
        # Old artifacts disappear in a pacman upgrade. Recovery is still local.
        shutil.rmtree(self.work / 'artifacts')
        (self.work / 'manifest.json').unlink()
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.assertEqual(self.setting('XeFG.InterpolationCount'), '3')
        self.assertEqual((self.ini().parent / 'winmm.dll').read_bytes(), self.files['winmm.dll'])
        self.assertEqual(self.action('status')['generation'], initial)
        self.launch()
        self.assertEqual(self.action('status')['generation'], initial)
        self.assertTrue(self.action('status')['pinned'])

    def test_unpin_resumes_packaged_updates(self):
        self.launch()
        self.config['preset']['FrameGen.Enabled'] = 'false'
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.action('rollback')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.action('update')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')
        self.assertFalse(self.action('status')['pinned'])

    def test_modified_owned_dll_refuses_without_overwrite(self):
        self.launch()
        dll = self.ini().parent / 'winmm.dll'
        dll.write_bytes(b'player DLL')
        with self.assertRaisesRegex(RuntimeError, 'Locally modified managed payload'):
            self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(dll.read_bytes(), b'player DLL')

    def test_modified_driver_refuses_without_overwrite(self):
        self.launch()
        driver = self.prefix / state.DRIVER
        driver.write_bytes(b'player driver')
        with self.assertRaisesRegex(RuntimeError, 'Locally modified managed FSR4 driver'):
            self.launch()
        self.assertEqual(driver.read_bytes(), b'player driver')

    def test_unowned_collision_refuses_without_overwrite(self):
        self.ini().parent.mkdir(parents=True)
        dll = self.ini().parent / 'winmm.dll'
        dll.write_bytes(b'other mod')
        with self.assertRaisesRegex(RuntimeError, 'unowned file'):
            self.launch()
        self.assertEqual(dll.read_bytes(), b'other mod')

    def test_unrelated_files_and_ini_values_survive(self):
        self.launch()
        other = self.ini().parent / 'overlay-notes.txt'
        other.write_text('my notes')
        self.edit('MyOverlay.Position', '42')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(other.read_text(), 'my notes')
        self.assertEqual(self.setting('MyOverlay.Position'), '42')

    def test_bad_recipe_hash_refuses_before_payload_changes(self):
        self.config['freefg'] = {'test-opti': {}}
        (self.work / 'freefg-recipes.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.launch()
        self.assertFalse(self.ini().exists())

    def test_symlink_directory_cannot_escape_prefix(self):
        outside = self.work / 'outside'
        outside.mkdir()
        self.ini().parent.parent.mkdir(parents=True)
        self.ini().parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.launch()
        self.assertEqual(list(outside.iterdir()), [])

    def test_journal_recovers_interrupted_commit(self):
        self.launch()
        before = self.ini().read_bytes()
        with state.Session(self.prefix, self.compat) as session:
            journal = session.root / 'journal'
            journal.mkdir()
            session.snapshot(journal / 'image')
            state.write_json(journal / 'before.json', {'state': session.state})
            self.ini().write_text('[FrameGen]\nEnabled=broken\n')
            # Simulate death after the payload rename, before state is committed.
        with state.Session(self.prefix, self.compat) as session:
            self.assertFalse((session.root / 'journal').exists())
        self.assertEqual(self.ini().read_bytes(), before)

    def test_session_lock_is_released_after_exception(self):
        self.stage_failure = 'failure'
        with self.assertRaises(RuntimeError):
            self.launch()
        with state.Session(self.prefix, self.compat):
            pass

    def test_unsupported_launch_option_fails_before_payload(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported OptiScaler'):
            self.launch(BC250_OPTISCALER_EXTRA='Imaginary.Key=true')
        self.assertFalse(self.ini().exists())

    def test_ordinary_launch_does_not_reextract_archives(self):
        self.launch()
        with mock.patch('tarfile.open', side_effect=AssertionError('Unnecessary extraction')):
            self.launch()

    def test_comments_and_section_spelling_survive_variant_switch(self):
        self.launch()
        self.ini().write_text('; Player comment\n' + self.ini().read_text() + '\n[MyOverlay]\n; Position choice\nPosition = 42\n')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        text = self.ini().read_text()
        self.assertIn('; Player comment', text)
        self.assertIn('[MyOverlay]\n; Position choice\nPosition = 42', text)

    def test_menu_rollback_then_resume_uses_the_corresponding_bundle(self):
        self.launch()
        self.config['preset']['FrameGen.Enabled'] = 'false'
        self.launch()
        # Exercise the same action returned by the native GTK menu.
        with state.Session(self.prefix, self.compat) as session:
            session.action('steam:1836730', 'rollback')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')
        self.action('update')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')

    def test_supervisor_keeps_lease_and_returns_child_status(self):
        code = """import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
try:
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
 sys.exit(7)
sys.exit(99)
"""
        with state.Session(self.prefix, self.compat) as session:
            result = wrapper.supervised(sys.executable, ['-c', code, str(session.root / 'session.lock')], os.environ.copy(), session.fd)
            self.assertEqual(result, 7)

    def test_rollback_never_overrides_full_opt_out(self):
        self.launch()
        self.config['preset']['FrameGen.Enabled'] = 'false'
        self.launch()
        self.action('rollback')
        self.launch(PROTON_FSR4_UPGRADE='0')
        self.assertEqual(self.last_env['PROTON_USE_OPTISCALER'], '0')
        self.assertEqual(self.last_env['PROTON_FSR4_UPGRADE'], '0')

    def test_provider_only_does_not_reset_optiscaler_settings(self):
        self.launch()
        self.edit('FrameGen.Enabled', 'false')
        before = self.ini().read_bytes()
        self.launch(SteamAppId='333', SteamGameId='333', PROTON_USE_OPTISCALER='0')
        self.assertEqual(before, self.ini().read_bytes())
        self.assertIn('BC250_FREEFG_PLAN', self.last_env)
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')

    def test_utility_environment_clears_inherited_transaction_context(self):
        with mock.patch.object(wrapper, 'TOOL', self.work):
            env = wrapper.environment(self.config, {**self.env, 'BC250_FREEFG_PLAN': '/old/plan',
                                      'BC250_FREEFG_MODULE': '/old/helper'}, game=False)
        self.assertNotIn('BC250_FREEFG_PLAN', env)
        self.assertNotIn('BC250_FREEFG_MODULE', env)

    def test_managed_menu_does_not_override_recipe_when_player_accepts_default(self):
        menu = fixtures.load_script('tested_managed_menu', COMMON / 'bc250-fsr4-menu.py')
        result = menu.answer({'preset': 'freefg', 'disable_framegen': 0}, 'freefg', 'freefg',
                             {'freefg': True}, managed=True)
        self.assertEqual(result['changed'], '')
        result = menu.answer({'preset': 'freefg', 'disable_framegen': 1}, 'freefg', 'freefg',
                             {'freefg': True}, managed=True)
        self.assertEqual(result['changed'], 'FrameGen.Enabled=false')

    def test_generated_scaling_ini_does_not_leak_between_shared_games(self):
        self.launch()
        scaling = self.ini().parent / 'OptiScaler/BC250-XeFG/settings.ini'
        scaling.parent.mkdir(parents=True)
        scaling.write_text('[Scaling]\nPercent=75\n')
        self.launch(SteamAppId='222', SteamGameId='222')
        self.assertFalse(scaling.exists())
        self.launch()
        self.assertEqual(scaling.read_text(), '[Scaling]\nPercent=75\n')

    def test_cached_manifest_tampering_cannot_change_pinned_payload(self):
        self.launch()
        status = self.action('status')
        bundle = self.prefix / '.bc250-freefg/bundles' / status['details']['bundle']
        manifest = json.loads((bundle / 'manifest.json').read_text())
        manifest['optiscaler'][0]['sha256_hash']['winmm.dll'] = '0' * 64
        (bundle / 'manifest.json').write_text(json.dumps(manifest))
        before = self.ini().read_bytes()
        with self.assertRaisesRegex(ValueError, 'package identity'):
            self.launch()
        self.assertEqual(self.ini().read_bytes(), before)

    def test_crlf_and_comments_are_retained(self):
        self.launch()
        content = ('; keep this comment\n' + self.ini().read_text()).replace('\n', '\r\n').encode()
        self.ini().write_bytes(content)
        self.launch()
        self.assertEqual(self.ini().read_bytes(), content)

    def enable_recipe_fixture(self, title):
        # A build that actually defines the route keys; the package reports
        # its keys from the same INI it places in its archive.
        files = dict(self.files)
        files['OptiScaler.ini'] = files['OptiScaler.ini'].replace(b'FGOutput=auto', b'DisableHudless=auto\nFGOutput=auto')
        archive = self.work / 'artifacts/opti.tar.xz'
        with tarfile.open(archive, 'w:xz') as output:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
        manifest = json.loads((self.work / 'manifest.json').read_text())
        manifest['optiscaler'][0]['zip_sha256_hash'] = state.digest(archive)
        (self.work / 'manifest.json').write_text(json.dumps(manifest))
        self.config['optiscaler_ini_keys']['test-opti'].append('FrameGen.DisableHudless')
        self.config['freefg'] = {'test-opti': {}}
        self.config['freefg_recipe_providers'] = {'test-opti': 'fsr4'}
        catalog = json.loads((COMMON / 'freefg-recipes.json').read_text())
        row = next(row for row in catalog['verified'] if row['title'] == title)
        appid = row['match']['steam'][0]
        self.env.update(SteamAppId=appid, SteamGameId=appid)
        self.args = ['waitforexitandrun', '/Games/' + title + '/' + row['match']['exe'][0]]

    def test_dlss_recipe_reaches_the_real_setup_and_preserves_player_input(self):
        self.enable_recipe_fixture('RoboCop: Rogue City')
        self.launch()
        self.assertEqual(self.setting('FrameGen.FGInput'), 'dlssg')
        self.assertEqual(self.setting('fakenvapi.ForceReflex'), 'auto')
        self.edit('FrameGen.FGInput', 'upscaler')
        self.launch()
        self.assertEqual(self.setting('FrameGen.FGInput'), 'upscaler')
        self.assertEqual(self.save.read_bytes(), b'preserve existing progress')

    def test_fsr_recipe_applies_hud_fix_and_keeps_game_settings_advisory(self):
        self.enable_recipe_fixture('Dead as Disco')
        self.launch()
        self.assertEqual(self.setting('FrameGen.FGInput'), 'fsrfg')
        self.assertEqual(self.setting('FrameGen.DisableHudless'), 'true')
        self.assertEqual(self.setting('fakenvapi.ForceReflex'), '2')
        with state.Session(self.prefix, self.compat) as session:
            status = session.status('steam:' + self.env['SteamAppId'])
        self.assertTrue(status['details']['recipe']['game_settings'])
        self.assertFalse((self.prefix / 'drive_c/users').exists())

    def test_managed_menu_reads_this_games_fg_choice_across_version_changes(self):
        menu = fixtures.load_script('tested_menu_state', COMMON / 'bc250-fsr4-menu.py')
        saved = self.work / 'menu-preview.ini'
        saved.write_text('[FrameGen]\nEnabled=false\n')
        env = {'BC250_MENU_GAME': 'steam:1836730', 'BC250_MENU_INI': str(saved),
               'BC250_MENU_DEFAULT': 'freefg', 'BC250_MENU_INSTALLED': ''}
        self.assertFalse(menu.state(str(self.compat), env)[2])

    def steam_game(self, appid, name, exe):
        """A Steam game in this test's own library, named as Steam records it, on a
        FreeFG variant so the catalogue applies."""
        library = self.work / 'steamapps'
        folder = library / 'common' / exe.split('/')[0]
        folder.mkdir(parents=True, exist_ok=True)
        (library / f'appmanifest_{appid}.acf').write_text(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n}}\n')
        self.env.update(SteamAppId=appid, SteamGameId=appid, STEAM_COMPAT_INSTALL_PATH=str(folder))
        self.args = ['waitforexitandrun', str(library / 'common' / exe)]
        self.config['freefg'] = {'test-opti': {}}
        self.config['freefg_recipe_providers'] = {'test-opti': 'hlx-fsr4'}

    def define(self, text):
        """The default build with these OptiScaler.ini lines added; the package
        reports the keys of the INI it places in its archive."""
        files = dict(self.files, **{'OptiScaler.ini': self.files['OptiScaler.ini'] + text})
        archive = self.work / 'artifacts/opti.tar.xz'
        with tarfile.open(archive, 'w:xz') as output:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
        manifest = json.loads((self.work / 'manifest.json').read_text())
        manifest['optiscaler'][0]['zip_sha256_hash'] = state.digest(archive)
        (self.work / 'manifest.json').write_text(json.dumps(manifest))
        section = None
        for line in text.decode().splitlines():
            if line.startswith('['):
                section = line.strip('[]')
            elif '=' in line:
                self.config['optiscaler_ini_keys']['test-opti'].append(section + '.' + line.split('=', 1)[0])

    def test_package_preset_leaves_optiscalers_own_fix_for_the_game(self):
        # OptiScaler restores the compute signature for these RE Engine games on
        # non-NVIDIA GPUs, but only while the key says auto. The shared preset's
        # explicit false, which auto already means, switched that fix off.
        self.define(b'[Hotfix]\nRestoreComputeSignature=auto\n')
        self.config['preset']['Hotfix.RestoreComputeSignature'] = 'false'
        self.steam_game('4000001', 'Monster Hunter Wilds', 'MonsterHunterWilds/MonsterHunterWilds.exe')
        self.launch()
        self.assertEqual(self.setting('Hotfix.RestoreComputeSignature'), 'auto')
        self.assertIn('Hotfix.RestoreComputeSignature', self.menu_env['BC250_MENU_ADVICE'])
        # Another game in the same prefix, with no such fix, keeps the package value.
        self.steam_game('4000002', 'Some Other Game', 'Other/Other.exe')
        self.launch()
        self.assertEqual(self.setting('Hotfix.RestoreComputeSignature'), 'false')

    def test_input_the_wiki_reports_broken_starts_frame_generation_off(self):
        self.steam_game('4000003', 'Neverness to Everness', 'NTE/Client/Binaries/Win64/HTGame.exe')
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')
        self.assertIn('reports OptiFG input broken', self.menu_env['BC250_MENU_ADVICE'])
        with state.Session(self.prefix, self.compat) as session:
            self.assertEqual(session.status('steam:4000003')['details']['recipe']['tier'], 'C')
        # The player's choice in the menu still wins, and is kept.
        self.menu = (None, {'FrameGen.Enabled': 'true'}, False)
        self.launch()
        self.menu = (None, {}, False)
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')

    def test_variant_switch_leaves_the_previous_variants_wiring_behind(self):
        self.launch()
        # Saved in this variant's overlay: an output and an upscaler it ships.
        self.edit('FrameGen.FGOutput', 'fsrfg')
        self.edit('Upscalers.Dx12Upscaler', 'xess')
        self.edit('XeFG.InterpolationCount', '3')
        self.launch()
        self.assertEqual(self.setting('FrameGen.FGOutput'), 'fsrfg')
        # Off and back again is not a switch.
        self.launch(PROTON_USE_OPTISCALER='0')
        self.launch()
        self.assertEqual(self.setting('Upscalers.Dx12Upscaler'), 'xess')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(self.setting('FrameGen.FGOutput'), 'auto')
        self.assertEqual(self.setting('Upscalers.Dx12Upscaler'), 'auto')
        self.assertEqual(self.setting('XeFG.InterpolationCount'), '3')
        self.assertEqual(self.setting('FrameGen.Enabled'), 'true')

    def test_package_update_of_the_same_variant_keeps_its_wiring(self):
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.edit('FrameGen.FGOutput', 'fsrfg')
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        # A new nightly renames every pinned version; the variant is still altbridge.
        manifest = json.loads((self.work / 'manifest.json').read_text())
        manifest['optiscaler'][1]['version'] = 'test-opti-alt-next'
        (self.work / 'manifest.json').write_text(json.dumps(manifest))
        self.config['optiscaler_aliases']['altbridge'] = 'test-opti-alt-next'
        self.config['optiscaler_ini_keys']['test-opti-alt-next'] = self.config['optiscaler_ini_keys']['test-opti-alt']
        self.launch(PROTON_USE_OPTISCALER='altbridge')
        self.assertEqual(self.setting('FrameGen.FGOutput'), 'fsrfg')

    def test_first_managed_launch_keeps_this_launchs_menu_choice(self):
        # Every existing prefix is adopted on its first managed launch; the menu
        # choice made on that launch must not be replaced by the INI it adopts.
        self.ini().parent.mkdir(parents=True)
        self.ini().write_bytes(STUB_INI.replace(b'Enabled=auto', b'Enabled=true'))
        self.menu = (None, {'FrameGen.Enabled': 'false'}, False)
        self.launch()
        self.assertEqual(self.setting('FrameGen.Enabled'), 'false')

    def test_managed_menu_wires_the_frame_generation_it_turns_on(self):
        menu = fixtures.load_script('tested_menu_wiring', COMMON / 'bc250-fsr4-menu.py')
        # FSR4 RC12 generates nothing with Enabled alone: FGInput/FGOutput default to nofg.
        result = menu.answer({'preset': 'fsr412f', 'disable_framegen': 0}, 'fsr412f', 'fsr412f',
                             {'fsr412f': False}, ini_sections={}, managed=True)
        self.assertEqual(result['changed'], 'FrameGen.Enabled=true;FrameGen.FGInput=upscaler;FrameGen.FGOutput=fsrfg')
        # On a switch the box shows the game's carried-over choice; it is what starts.
        result = menu.answer({'preset': 'fsr412f', 'disable_framegen': 0}, 'freefg', 'freefg',
                             {'freefg': True, 'fsr412f': True}, managed=True)
        self.assertEqual(result['changed'], 'FrameGen.Enabled=true;FrameGen.FGInput=upscaler;FrameGen.FGOutput=fsrfg')


class CachyOSTransactionTests(TransactionTests):
    def setUp(self):
        super().setUp()
        self.base = 'proton-cachyos'


class RecipeTests(unittest.TestCase):
    def setUp(self):
        pin = json.loads((COMMON / 'freefg-upstream.json').read_text())
        self.catalog = recipes.load(COMMON / 'freefg-recipes.json', pin['recipes']['sha256'])
        self.keys = {'FrameGen.FGInput', 'FrameGen.FGOutput', 'FrameGen.Enabled', 'Spoofing.Dxgi',
                     'Inputs.EnableFfxInputs', 'Inputs.EnableDlssInputs', 'FrameGen.DisableHudless', 'fakenvapi.ForceReflex'}
        # The package's FreeFG default, which the catalogue tempers per game.
        self.package = {'FrameGen.Enabled': 'true', 'FrameGen.FGInput': 'upscaler', 'FrameGen.FGOutput': 'xefg'}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.library = Path(temporary.name) / 'steamapps'

    def steam(self, appid, name, exe):
        """The identity of a Steam game whose appmanifest names it."""
        (self.library / 'common').mkdir(parents=True, exist_ok=True)
        (self.library / f'appmanifest_{appid}.acf').write_text(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n}}\n')
        return recipes.identity({'SteamAppId': appid}, ['waitforexitandrun', str(self.library / 'common' / exe)])

    def test_real_identity_and_generic_shortcut_do_not_cross_match(self):
        game = recipes.identity({'SteamAppId': '1836730'}, ['run', '/Games/Echo Point Nova/Greylock-Win64-Shipping.exe'])
        self.assertEqual(recipes.match(self.catalog, game)['title'], 'Echo Point Nova')
        wrong = recipes.identity({'SteamAppId': '999999'}, ['run', '/Games/Echo Point Nova/Greylock-Win64-Shipping.exe'])
        self.assertIsNone(recipes.match(self.catalog, wrong))
        shortcut = recipes.identity({'UMU_ID': 'umu-0', 'SteamAppId': '0'}, ['run', '/Games/Echo Point Nova/Greylock-Win64-Shipping.exe'])
        self.assertEqual(recipes.match(self.catalog, shortcut)['title'], 'Echo Point Nova')
        generic = recipes.identity({'UMU_ID': 'umu-0'}, ['run', '/Games/Other/Shipping.exe'])
        self.assertIsNone(recipes.match(self.catalog, generic))

    def test_native_route_is_explicitly_unavailable(self):
        row = next(row for row in self.catalog['verified'] if row['route'] == 'native')
        game = recipes.identity({'SteamAppId': row['match']['steam'][0]}, ['run', row['match']['exe'][0]])
        row = recipes.recommendation(self.catalog, game, 'hlx-fsr4', self.keys)
        self.assertFalse(row['applicable'])
        self.assertEqual(row['settings']['FrameGen.Enabled'], 'false')
        self.assertTrue(any('native XeFG' in note for note in row['notes']))

    def test_deadzone_quality_is_advisory(self):
        game = recipes.identity({'SteamAppId': '3228590'}, ['run', 'deadzonesteam-win64-shipping.exe'])
        row = recipes.recommendation(self.catalog, game, 'fsr4', self.keys)
        self.assertTrue(row['applicable'])
        self.assertTrue(any('Native' in note for note in row['notes']))
        self.assertEqual(row['game_settings'], [])

    def test_missing_build_key_is_advisory(self):
        game = recipes.identity({'SteamAppId': '3228590'}, ['run', 'deadzonesteam-win64-shipping.exe'])
        row = recipes.recommendation(self.catalog, game, 'fsr4', [])
        self.assertFalse(row['applicable'])
        self.assertEqual(row['settings'], {})

    def test_launch_args_never_go_to_launcher_or_override_graphics_api(self):
        row = {'applicable': True, 'arguments': ['-dx12'], 'executables': ['game.exe']}
        game = {'exe': 'launcher.exe'}
        self.assertEqual(recipes.launch_arguments(['run', 'launcher.exe'], row, game), ['run', 'launcher.exe'])
        game['exe'] = 'game.exe'
        self.assertEqual(recipes.launch_arguments(['run', 'game.exe', '-dx11'], row, game), ['run', 'game.exe', '-dx11'])
        self.assertEqual(recipes.launch_arguments(['run', 'game.exe'], row, game), ['run', 'game.exe', '-dx12'])

    def test_non_steam_missing_identity_requires_an_explicit_game_id(self):
        with self.assertRaisesRegex(ValueError, 'Cannot identify'):
            recipes.identity({'UMU_ID': 'umu-0'}, ['run'])

    def test_ambiguous_store_identity_refuses(self):
        self.catalog['verified'].append(copy.deepcopy(self.catalog['verified'][0]))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            recipes.match(self.catalog, recipes.identity({'SteamAppId': '3404260'}, ['run', 'game.exe']))

    def test_recipe_source_is_unchanged_and_all_rows_parse(self):
        for row in self.catalog['verified']:
            store, ids = next((store, row['match'][store]) for store in ('steam', 'gog', 'epic') if row['match'].get(store))
            game = recipes.identity({'BC250_FREEFG_GAME_ID': store + ':' + ids[0]}, ['run', row['match']['exe'][0]])
            actual = recipes.match(self.catalog, game)
            self.assertEqual(actual['title'], row['title'])
            result = recipes.recommendation(self.catalog, game, 'hlx-fsr4', self.keys)
            if result['applicable']:
                self.assertIn(result['evidence'], recipes.QUALIFIED)

    def test_wiki_titles_come_from_steams_record_of_the_game(self):
        # Wiki entries name titles and executables, never store IDs.
        game = self.steam('2322010', 'God of War Ragnarök', 'GoWR/GoWR.exe')
        self.assertIn('god of war ragnarok', game['titles'])
        self.assertEqual([(w['title'], s) for w, s in recipes.wiki_matches(self.catalog, game)],
                         [('God of War Ragnarok', 'weak')])
        bare = recipes.identity({'SteamAppId': '2322010'}, ['run', '/Games/GoWR/GoWR.exe'])
        self.assertEqual(bare['titles'], [])

    def test_optiscalers_own_fix_for_a_game_outranks_the_package_default(self):
        package = {**self.package, 'Hotfix.RestoreComputeSignature': 'false', 'XeFG.ForceBorderless': 'true',
                   'Spoofing.VulkanExtensionSpoofing': 'false'}
        keys = self.keys | set(package)
        wilds = self.steam('2246340', 'Monster Hunter Wilds', 'MHWilds/MonsterHunterWilds.exe')
        result = recipes.recommendation(self.catalog, wilds, 'hlx-fsr4', keys, package)
        self.assertEqual(result['settings'], {'Hotfix.RestoreComputeSignature': 'auto'})
        # FreeFG's installer keys stand: it measured ForceBorderless under Proton.
        exe = next(exe for exe, fixes in self.catalog['quirk_keys'].items() if 'XeFG.ForceBorderless' in fixes)
        result = recipes.recommendation(self.catalog, self.steam('4000004', 'X', 'X/' + exe), 'fsr4', keys, package)
        self.assertNotIn('XeFG.ForceBorderless', result['settings'])
        # A value this package keeps for a reason of its own is reported, not changed.
        result = recipes.recommendation(self.catalog, self.steam('1086940', "Baldur's Gate 3", 'BG3/bin/bg3.exe'),
                                        'fsr4', keys, package)
        self.assertNotIn('Spoofing.VulkanExtensionSpoofing', result['settings'])
        self.assertTrue(any('VulkanExtensionSpoofing' in note for note in result['notes']))
        # Without the package's values there is nothing to give back.
        self.assertEqual(recipes.recommendation(self.catalog, wilds, 'hlx-fsr4', keys)['settings'], {})

    def test_wiki_changes_settings_only_on_freefgs_strong_match(self):
        keys = self.keys | {'Hotfix.ColorResourceBarrier'}
        nte = self.steam('4000001', 'Neverness to Everness', 'NTE/Client/Binaries/Win64/HTGame.exe')
        result = recipes.recommendation(self.catalog, nte, 'hlx-fsr4', keys, self.package)
        self.assertEqual((result['tier'], result['settings']), ('C', {'FrameGen.Enabled': 'false'}))
        rebirth = self.steam('4000002', 'FINAL FANTASY VII REBIRTH', 'FF7R/End/Binaries/Win64/ff7rebirth_.exe')
        result = recipes.recommendation(self.catalog, rebirth, 'hlx-fsr4', keys, self.package)
        self.assertEqual((result['tier'], result['settings']), ('C', {'Hotfix.ColorResourceBarrier': '4'}))
        # The same titles without their executable are advice only.
        for appid, name in (('4000001', 'Neverness to Everness'), ('4000002', 'FINAL FANTASY VII REBIRTH')):
            result = recipes.recommendation(self.catalog, self.steam(appid, name, 'Other/Launcher.exe'), 'hlx-fsr4',
                                            keys, self.package)
            self.assertEqual((result['tier'], result['settings']), ('D', {}))
        # A curated recipe decides the input itself.
        robocop = self.steam('1681430', 'RoboCop: Rogue City', 'RoboCop/RoboCop/Binaries/Win64/RoboCop-Win64-Shipping.exe')
        result = recipes.recommendation(self.catalog, robocop, 'hlx-fsr4', self.keys, self.package)
        self.assertEqual((result['tier'], result['settings']['FrameGen.FGInput']), ('A', 'dlssg'))

    def test_wiki_preferences_are_advice(self):
        # FreeFG's Cyberpunk recipe is verified for the GOG edition only.
        game = self.steam('1091500', 'Cyberpunk 2077', 'Cyberpunk 2077/bin/x64/Cyberpunk2077.exe')
        result = recipes.recommendation(self.catalog, game, 'hlx-fsr4', self.keys, self.package)
        self.assertEqual((result['title'], result['settings']), (None, {}))
        self.assertTrue(any('FrameGen.FGInput=dlssg' in line for line in result['summary']))
        unknown = recipes.recommendation(self.catalog, self.steam('4000005', 'Some Indie Game', 'Indie/Indie.exe'),
                                         'hlx-fsr4', self.keys, self.package)
        self.assertEqual((unknown['tier'], unknown['settings']), ('D', {}))

    def test_a_launch_without_an_executable_keeps_one_identity_for_its_prefix(self):
        game = recipes.identity({'UMU_ID': 'umu-0', 'WINEPREFIX': '/prefixes/lutris'}, ['waitforexitandrun', 'setup.bat'])
        self.assertTrue(game['key'].startswith('prefix:'))
        self.assertEqual(recipes.recommendation(self.catalog, game, 'fsr4', self.keys)['settings'], {})

    def test_an_ambiguous_identity_keeps_the_defaults(self):
        self.catalog['verified'].append(copy.deepcopy(self.catalog['verified'][0]))
        game = recipes.identity({'SteamAppId': '3404260'}, ['run', 'game.exe'])
        result = recipes.recommendation(self.catalog, game, 'fsr4', self.keys)
        self.assertEqual(result['settings'], {})
        self.assertTrue(any('Ambiguous' in note for note in result['notes']))
