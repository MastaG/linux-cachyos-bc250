"""Exercise both actual upstream modules with local payloads and no network."""

import ast
import configparser
import hashlib
import importlib.util
import io
import json
import lzma
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "packages/bc250-fsr4-common"
BASES = {
    "ge-proton": "4128896c4134d865a290e2e8e62279d07157131b207f4bc7d29e8c873fe85645",
    "proton-cachyos": "3380cea841b3a52de9fdfe151631e1c24b7ec9707d7d77fb0eea68d42aa6140c",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load_script("wrapper", COMMON / "bc250-fsr4-launch.py")
builder = load_script("builder", ROOT / "scripts/build-fsr4-payload.py")


# Shaped like the real OptiScaler.ini in the part that matters here: every
# spoofing key ships as "auto", which is what marks a prefix as having no
# opinion of its own yet.
STUB_INI = (
    b"[FSR]\nFsr4ForceModel=auto\n"
    b"[Spoofing]\nDxgi=auto\nVulkanExtensionSpoofing=auto\n"
)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {}
        original = (ROOT / "tests/fixtures/ge-proton11-6-upscalers.py").read_bytes()
        assert sha256(original) == BASES["ge-proton"]
        for base, expected_hash in BASES.items():
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / (
                    "protonfixes/upscalers.py"
                    if base == "ge-proton"
                    else "upscalers.py"
                )
                source.parent.mkdir(exist_ok=True)
                source.write_bytes(original)
                if base == "proton-cachyos":
                    subprocess.run(
                        [
                            "patch",
                            "--batch",
                            "--fuzz=0",
                            "-p1",
                            "-i",
                            str(ROOT / "tests/fixtures/ge-to-cachyos-native.patch"),
                        ],
                        cwd=root,
                        check=True,
                        capture_output=True,
                    )
                assert sha256(source.read_bytes()) == expected_hash
                subprocess.run(
                    [
                        "patch",
                        "--batch",
                        "--fuzz=0",
                        "-p1",
                        "-i",
                        str(
                            COMMON
                            / "patches"
                            / base
                            / "0001-pinned-upscaler-manifest.patch"
                        ),
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                cls.sources[base] = source.read_text()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.compat = self.work / "compat"
        self.prefix = self.compat / "pfx"
        self.prefix.mkdir(parents=True)
        self.save = self.prefix / "synthetic-save"
        self.save.write_bytes(b"preserve existing progress")
        artifacts = self.work / "artifacts"
        artifacts.mkdir()
        # protonfixes rejects DLL placeholders smaller than 1 KiB.
        self.provider = bytes(range(256)) * 16
        provider = artifacts / "provider.xz"
        provider.write_bytes(lzma.compress(self.provider))
        self.files = {
            "winmm.dll": bytes(range(255, -1, -1)) * 16,
            "OptiScaler.ini": STUB_INI,
        }
        archive = artifacts / "opti.tar.xz"
        with tarfile.open(archive, "w:xz") as tar:
            for name, data in self.files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        # A second, opt-in variant of the same tree, as the packages ship for an
        # alternate FidelityFX bridge. Only one file differs.
        self.variant = dict(self.files, **{"winmm.dll": bytes(range(128)) * 32})
        variant_archive = artifacts / "opti-alt.tar.xz"
        with tarfile.open(variant_archive, "w:xz") as tar:
            for name, data in self.variant.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        # A second opt-in variant, because the packages now ship two and each
        # alias has to resolve to its own payload rather than to whichever
        # entry happens to come first.
        self.second = dict(self.files, **{"winmm.dll": bytes(range(64)) * 64})
        second_archive = artifacts / "opti-alt2.tar.xz"
        with tarfile.open(second_archive, "w:xz") as tar:
            for name, data in self.second.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        manifest = {
            "fsr_40_drv": [
                {
                    "version": "4.1.1",
                    "is_dev_file": False,
                    "download_url": "artifacts/provider.xz",
                    "zip_sha256_hash": sha256(provider.read_bytes()),
                    "sha256_hash": sha256(self.provider),
                    "md5_hash": hashlib.md5(self.provider).hexdigest(),
                }
            ],
            "optiscaler": [
                {
                    "version": "test-opti",
                    "is_dev_file": False,
                    "download_url": "artifacts/opti.tar.xz",
                    "zip_sha256_hash": sha256(archive.read_bytes()),
                    "sha256_hash": {"winmm.dll": sha256(self.files["winmm.dll"])},
                    "md5_hash": {
                        "winmm.dll": hashlib.md5(self.files["winmm.dll"]).hexdigest(),
                        "OptiScaler.ini": "",
                    },
                },
                {
                    "version": "test-opti-alt",
                    "is_dev_file": False,
                    "download_url": "artifacts/opti-alt.tar.xz",
                    "zip_sha256_hash": sha256(variant_archive.read_bytes()),
                    "sha256_hash": {"winmm.dll": sha256(self.variant["winmm.dll"])},
                    "md5_hash": {
                        "winmm.dll": hashlib.md5(self.variant["winmm.dll"]).hexdigest(),
                        "OptiScaler.ini": "",
                    },
                },
                {
                    "version": "test-opti-alt2",
                    "is_dev_file": False,
                    "download_url": "artifacts/opti-alt2.tar.xz",
                    "zip_sha256_hash": sha256(second_archive.read_bytes()),
                    "sha256_hash": {"winmm.dll": sha256(self.second["winmm.dll"])},
                    "md5_hash": {
                        "winmm.dll": hashlib.md5(self.second["winmm.dll"]).hexdigest(),
                        "OptiScaler.ini": "",
                    },
                },
            ],
        }
        (self.work / "manifest.json").write_text(json.dumps(manifest))
        self.config = {
            "manifest": "manifest.json",
            "proxy": "winmm.dll",
            "provider_version": "4.1.1",
            "optiscaler_version": "test-opti",
            "optiscaler_aliases": {
                "altbridge": "test-opti-alt",
                "altbridge2": "test-opti-alt2",
            },
            "preset": {
                "FSR.Fsr4ForceModel": "2",
                "Spoofing.Dxgi": "false",
                "Spoofing.VulkanExtensionSpoofing": "false",
            },
            "seed_once": ["Spoofing.Dxgi", "Spoofing.VulkanExtensionSpoofing"],
        }

    def run_upscalers(self, base, inherited, arguments):
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config, inherited, game=wrapper.game_launch(arguments, inherited)
            )
        enabled = {
            feature
            for key, feature in [
                ("PROTON_FSR4_UPGRADE", "fsr4"),
                ("PROTON_USE_OPTISCALER", "optiscaler"),
            ]
            if env.get(key, "0") != "0"
        }
        tree = ast.parse(self.sources[base])
        tree.body = [
            node
            for node in tree.body
            if not (isinstance(node, ast.ImportFrom) and node.level)
        ]
        module = types.ModuleType("tested_upscalers")
        module.log = mock.Mock()
        module.config = types.SimpleNamespace(
            path=types.SimpleNamespace(cache_dir=self.work / "cache")
        )
        # Execute the hash-verified upstream regression module.
        exec(compile(tree, "upscalers.py", "exec"), module.__dict__)  # noqa: S102
        with mock.patch.object(
            module.urllib.request,
            "urlopen",
            side_effect=AssertionError("Unexpected network access"),
        ) as network:
            module.setup_upscalers(enabled, env, str(self.compat), str(self.prefix))
            network.assert_not_called()
        self.assertEqual(self.save.read_bytes(), b"preserve existing progress")
        return env

    def test_both_tools_install_the_pinned_payload_for_games(self):
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                self.assertEqual(env["WINE_OPTISCALER_NAME"], "winmm.dll")
                self.assertEqual(
                    (
                        self.prefix / "drive_c/windows/system32/amdxcffx64.dll"
                    ).read_bytes(),
                    self.provider,
                )

    def test_the_requested_proxy_reaches_wine_through_real_protonfixes(self):
        # The wrapper setting the variable is only half of it: upstream is what
        # turns PROTON_OPTISCALER_NAME into the name Wine matches, and it
        # defaults to dxgi.dll on its own, so this has to be checked against the
        # real module rather than inferred.
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(
                    base,
                    {"SteamAppId": "999999998", "PROTON_OPTISCALER_NAME": "dxgi"},
                    ["run"],
                )
                self.assertEqual(env["WINE_OPTISCALER_NAME"], "dxgi.dll")
                self.assertEqual(env["WINEDLLOVERRIDES"], "dxgi=n,b")

    def test_a_spoofing_toggle_survives_the_next_launch(self):
        # The whole point, end to end through the real protonfixes module: the
        # first launch seeds the packaged value, the player changes it in the
        # OptiScaler overlay, and the launch after that leaves it alone. Before
        # this, the preset was written back over the top every time.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                inherited = {
                    "SteamAppId": "999999998",
                    "WINEPREFIX": str(self.prefix),
                }
                self.run_upscalers(base, inherited, ["run"])
                ini = self.prefix / "drive_c/windows/system32/umu/OptiScaler.ini"
                parser = configparser.ConfigParser()
                parser.read(ini)
                self.assertEqual(parser["Spoofing"]["dxgi"], "false")

                # What the overlay's "Save Settings" does.
                parser["Spoofing"]["dxgi"] = "true"
                with ini.open("w") as stream:
                    parser.write(stream)

                self.run_upscalers(base, inherited, ["run"])
                parser = configparser.ConfigParser()
                parser.read(ini)
                self.assertEqual(parser["Spoofing"]["dxgi"], "true")
                # Everything else is still enforced on that same launch.
                self.assertEqual(parser["FSR"]["fsr4forcemodel"], "2")

    def test_documented_opt_out_stops_hooks_without_erasing_retained_files(self):
        for base in BASES:
            with self.subTest(base=base):
                self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                before = {
                    str(p): p.read_bytes() for p in self.work.rglob("*") if p.is_file()
                }
                env = self.run_upscalers(
                    base,
                    {
                        "SteamAppId": "999999998",
                        "PROTON_FSR4_UPGRADE": "0",
                        "WINE_OPTISCALER_NAME": "stale.dll",
                        "WINE_UPSCALER_REPLACE": "fsr4",
                        "FSR4_UPGRADE": "1",
                    },
                    ["run"],
                )
                for name in (
                    "WINE_OPTISCALER_NAME",
                    "WINE_UPSCALER_REPLACE",
                    "FSR4_UPGRADE",
                ):
                    self.assertNotIn(name, env)
                self.assertEqual(
                    {
                        str(p): p.read_bytes()
                        for p in self.work.rglob("*")
                        if p.is_file()
                    },
                    before,
                )

    def test_utilities_and_zero_ids_do_not_download_or_install_upscalers(self):
        for base in BASES:
            for arguments, appid in [(["getcompatpath"], "999999998"), (["run"], "0")]:
                with self.subTest(base=base, arguments=arguments, appid=appid):
                    before = {
                        str(p): p.read_bytes()
                        for p in self.work.rglob("*")
                        if p.is_file()
                    }
                    env = self.run_upscalers(
                        base,
                        {
                            "SteamAppId": appid,
                            "PROTON_FSR4_UPGRADE": "1",
                            "PROTON_USE_OPTISCALER": "1",
                            "PROTON_DLSS_UPGRADE": "1",
                        },
                        arguments,
                    )
                    self.assertNotIn("WINE_OPTISCALER_NAME", env)
                    self.assertNotIn("WINE_UPSCALER_REPLACE", env)
                    self.assertEqual(
                        {
                            str(p): p.read_bytes()
                            for p in self.work.rglob("*")
                            if p.is_file()
                        },
                        before,
                    )

    def test_the_optiscaler_proxy_is_loaded_from_disk_not_from_wine(self):
        # Wine defaults winmm to builtin-first, so without this the proxy is
        # mapped and then discarded and the game runs with no upscaler at all.
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                self.assertIn("winmm=n,b", env["WINEDLLOVERRIDES"].split(";"))

    def test_an_inherited_proxy_override_and_dll_list_are_left_alone(self):
        for inherited, expected in [
            ("winmm=b", "winmm=b"),
            ("dxgi,winmm=b;d3d11=n", "dxgi,winmm=b;d3d11=n"),
            ("d3d11=n", "d3d11=n;winmm=n,b"),
            ("", "winmm=n,b"),
        ]:
            with self.subTest(inherited=inherited):
                with mock.patch.object(wrapper, "TOOL", self.work):
                    env = wrapper.environment(
                        self.config,
                        {"SteamAppId": "999999998", "WINEDLLOVERRIDES": inherited},
                        game=True,
                    )
                self.assertEqual(env["WINEDLLOVERRIDES"], expected)

    def test_a_launch_option_can_override_individual_preset_keys(self):
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config,
                {
                    "SteamAppId": "999999998",
                    "BC250_OPTISCALER_EXTRA":
                        "FSR.Fsr4ForceModel=3; Spoofing.Dxgi=auto ;",
                },
                game=True,
            )
        applied = dict(
            part.split("=", 1) for part in env["PROTON_OPTISCALER_CONFIG"].split(";")
        )
        # overrides win over the preset, and unrelated keys survive untouched
        self.assertEqual(applied["FSR.Fsr4ForceModel"], "3")
        self.assertEqual(applied["Spoofing.Dxgi"], "auto")
        for key, value in self.config["preset"].items():
            if key not in ("FSR.Fsr4ForceModel", "Spoofing.Dxgi"):
                self.assertEqual(applied[key], value)

    def test_a_malformed_override_names_the_entry_rather_than_being_ignored(self):
        for bad in ("Fsr4ForceModel=3", "FSR.Fsr4ForceModel", "nonsense"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(RuntimeError, "Section.Option=value"):
                    wrapper.extra_preset(bad)

    def test_an_absent_or_empty_override_changes_nothing(self):
        with mock.patch.object(wrapper, "TOOL", self.work):
            plain = wrapper.environment(
                self.config, {"SteamAppId": "999999998"}, game=True)
            empty = wrapper.environment(
                self.config,
                {"SteamAppId": "999999998", "BC250_OPTISCALER_EXTRA": "  ;  "},
                game=True)
        self.assertEqual(
            plain["PROTON_OPTISCALER_CONFIG"], empty["PROTON_OPTISCALER_CONFIG"])

    def applied_preset(self, inherited):
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(self.config, inherited, game=True)
        return dict(
            part.split("=", 1) for part in env["PROTON_OPTISCALER_CONFIG"].split(";")
        )

    def write_prefix_ini(self, text):
        ini = self.prefix / "drive_c/windows/system32/umu/OptiScaler.ini"
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text(text)
        return ini

    def game_dir(self, *relative):
        root = self.work / "game"
        for path in relative:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("marker")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_an_anticheat_game_gets_the_documented_opt_out(self):
        # Injecting into EAC or BattlEye is what gets accounts banned, and this
        # package injects by default, so it steps aside when it sees one.
        for marker in (
            "EasyAntiCheat/easyanticheat_x64.dll",
            "Game/Binaries/Win64/EasyAntiCheat_EOS/marker.txt",
            "Game/Binaries/Win64/start_protected_game.exe",
            "BattlEye/BEService.exe",
        ):
            with self.subTest(marker=marker):
                root = self.game_dir(marker)
                with mock.patch.object(wrapper, "TOOL", self.work):
                    env = wrapper.environment(
                        self.config,
                        {"SteamAppId": "999999998",
                         "STEAM_COMPAT_INSTALL_PATH": str(root)},
                        game=True,
                    )
                self.assertEqual(env["PROTON_FSR4_UPGRADE"], "0")
                self.assertEqual(env["PROTON_USE_OPTISCALER"], "0")
                # and no proxy override, so nothing is loaded from the prefix
                self.assertNotIn("WINEDLLOVERRIDES", env)
                for path in root.rglob("*"):
                    if path.is_file():
                        path.unlink()

    def test_steams_layered_runtimes_are_enough_on_their_own(self):
        for inherited in (
            {"PROTON_EAC_RUNTIME": "/steam/eac"},
            {"PROTON_BATTLEYE_RUNTIME": "/steam/be"},
            {"STEAM_COMPAT_TOOL_PATHS": "/steam/Proton EasyAntiCheat Runtime/:/x"},
        ):
            with self.subTest(inherited=inherited):
                with mock.patch.object(wrapper, "TOOL", self.work):
                    env = wrapper.environment(
                        self.config, dict(inherited, SteamAppId="999999998"), game=True)
                self.assertEqual(env["PROTON_FSR4_UPGRADE"], "0")

    def test_an_ordinary_game_is_untouched_by_the_guard(self):
        root = self.game_dir("Game/Binaries/Win64/game.exe", "steam_api64.dll")
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config,
                {"SteamAppId": "999999998", "STEAM_COMPAT_INSTALL_PATH": str(root)},
                game=True,
            )
        self.assertNotEqual(env["PROTON_FSR4_UPGRADE"], "0")
        self.assertNotEqual(env["PROTON_USE_OPTISCALER"], "0")

    def test_the_player_can_still_force_it_on(self):
        # Detection can be wrong -- a game that ships EAC files without running
        # them would otherwise lose its upscaler with no way back.
        root = self.game_dir("EasyAntiCheat/easyanticheat_x64.dll")
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config,
                {"SteamAppId": "999999998",
                 "STEAM_COMPAT_INSTALL_PATH": str(root),
                 "PROTON_FSR4_UPGRADE": "1"},
                game=True,
            )
        self.assertNotEqual(env["PROTON_FSR4_UPGRADE"], "0")
        self.assertNotEqual(env["PROTON_USE_OPTISCALER"], "0")

    def test_the_scan_does_not_walk_a_whole_game_library(self):
        # Every launch pays for this, so it is bounded in both directions.
        root = self.work / "deep"
        path = root
        for level in range(8):
            path = path / f"level{level}"
        (path / "EasyAntiCheat").mkdir(parents=True)
        self.assertIsNone(
            wrapper.anticheat_reason({"STEAM_COMPAT_INSTALL_PATH": str(root)}))

    def test_a_prefix_with_no_opinion_gets_the_packaged_spoofing(self):
        # Nothing written yet: the package decides, as it always has.
        applied = self.applied_preset(
            {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
        self.assertEqual(applied["Spoofing.Dxgi"], "false")
        self.assertEqual(applied["Spoofing.VulkanExtensionSpoofing"], "false")

        # Freshly extracted, so still "auto" -- also nobody's opinion.
        self.write_prefix_ini(STUB_INI.decode())
        applied = self.applied_preset(
            {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
        self.assertEqual(applied["Spoofing.Dxgi"], "false")

    def test_a_value_the_player_chose_is_not_written_over(self):
        self.write_prefix_ini(
            "[FSR]\nFsr4ForceModel=auto\n"
            "[Spoofing]\nDxgi=true\nVulkanExtensionSpoofing=auto\n"
        )
        applied = self.applied_preset(
            {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
        # Left out entirely, so protonfixes keeps whatever the file says.
        self.assertNotIn("Spoofing.Dxgi", applied)
        # The key they did not touch is still seeded, and so is the rest of the
        # preset -- this loosens two keys, not the whole configuration.
        self.assertEqual(applied["Spoofing.VulkanExtensionSpoofing"], "false")
        self.assertEqual(applied["FSR.Fsr4ForceModel"], "2")

    def test_a_launch_option_still_wins_over_the_prefix(self):
        self.write_prefix_ini(
            "[FSR]\nFsr4ForceModel=auto\n"
            "[Spoofing]\nDxgi=true\nVulkanExtensionSpoofing=auto\n"
        )
        applied = self.applied_preset({
            "SteamAppId": "999999998",
            "WINEPREFIX": str(self.prefix),
            "BC250_OPTISCALER_EXTRA": "Spoofing.Dxgi=false",
        })
        self.assertEqual(applied["Spoofing.Dxgi"], "false")

    def test_an_unreadable_prefix_keeps_the_packaged_value(self):
        # Being wrong in this direction gives a launch that behaves the way the
        # package documents, which is the one safe way to be wrong here.
        for text in ("[Spoofing\nDxgi=true\n", "nonsense without a section\n"):
            with self.subTest(text=text):
                self.write_prefix_ini(text)
                applied = self.applied_preset(
                    {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
                self.assertEqual(applied["Spoofing.Dxgi"], "false")

    def test_steam_supplies_the_prefix_as_a_compat_data_path(self):
        # Steam exports this rather than WINEPREFIX, and Proton has not run yet.
        self.write_prefix_ini(
            "[FSR]\nFsr4ForceModel=auto\n[Spoofing]\nDxgi=true\n"
            "VulkanExtensionSpoofing=auto\n"
        )
        applied = self.applied_preset({
            "SteamAppId": "999999998",
            "STEAM_COMPAT_DATA_PATH": str(self.prefix.parent),
        })
        self.assertNotIn("Spoofing.Dxgi", applied)

    def test_a_game_that_needs_another_proxy_can_ask_for_one(self):
        # Reported from the field: a game that already uses winmm for a mod or
        # ASI loader gets its own loader back and OptiScaler never loads. Such a
        # game needs a different import, usually dxgi.
        for requested, expected in (("dxgi.dll", "dxgi.dll"), ("dxgi", "dxgi.dll")):
            with self.subTest(requested=requested):
                with mock.patch.object(wrapper, "TOOL", self.work):
                    env = wrapper.environment(
                        self.config,
                        {
                            "SteamAppId": "999999998",
                            "PROTON_OPTISCALER_NAME": requested,
                        },
                        game=True,
                    )
                self.assertEqual(env["PROTON_OPTISCALER_NAME"], expected)
                # The override has to follow the name, or Wine loads its own
                # builtin dxgi and the proxy is bypassed exactly as before.
                self.assertEqual(env["WINEDLLOVERRIDES"], "dxgi=n,b")

    def test_the_packaged_proxy_is_still_what_an_ordinary_launch_gets(self):
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config, {"SteamAppId": "999999998"}, game=True)
        self.assertEqual(env["PROTON_OPTISCALER_NAME"], self.config["proxy"])
        self.assertEqual(env["WINEDLLOVERRIDES"], "winmm=n,b")

    def test_a_proxy_name_that_is_not_a_bare_dll_stops_the_launch(self):
        for bad in ("../../evil", "C:\\windows\\dxgi.dll", "dxgi.dll;winmm.dll"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(RuntimeError, "bare DLL name"):
                    wrapper.proxy_name(bad, "winmm.dll")

    def test_the_documented_opt_out_leaves_wines_own_defaults_in_place(self):
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(
                self.config,
                {"SteamAppId": "999999998", "PROTON_FSR4_UPGRADE": "0"},
                game=True,
            )
        self.assertNotIn("WINEDLLOVERRIDES", env)

    def test_umu_launchers_get_the_payload_despite_a_zero_steam_id(self):
        # Heroic's GOG launch, verbatim: umu sets both ids from GAMEID=umu-0.
        heroic = {
            "SteamAppId": "0",
            "SteamGameId": "0",
            "UMU_ID": "umu-0",
            "STEAM_COMPAT_APP_ID": "0",
        }
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(base, heroic, ["waitforexitandrun"])
                self.assertEqual(env["WINE_OPTISCALER_NAME"], "winmm.dll")
                self.assertNotEqual(env["PROTON_FSR4_UPGRADE"], "0")
                self.assertEqual(
                    (
                        self.prefix / "drive_c/windows/system32/amdxcffx64.dll"
                    ).read_bytes(),
                    self.provider,
                )

    def test_umu_does_not_turn_steam_utility_calls_into_game_launches(self):
        for arguments in (["getcompatpath"], ["getnativepath"], ["destroyprefix"]):
            with self.subTest(arguments=arguments):
                self.assertFalse(
                    wrapper.game_launch(arguments, {"UMU_ID": "umu-0"})
                )
        # No umu, no ids: still a utility call, which is the Steam-side rule.
        self.assertFalse(wrapper.game_launch(["run"], {"SteamAppId": "0"}))
        self.assertFalse(wrapper.game_launch(["run"], {"UMU_ID": ""}))
        self.assertFalse(wrapper.game_launch(["run"], {}))

    def test_the_default_variant_is_what_a_plain_launch_installs(self):
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                self.assertEqual(env["PROTON_USE_OPTISCALER"], "test-opti")
                proxy = self.prefix / "drive_c/windows/system32/umu/winmm.dll"
                self.assertEqual(proxy.read_bytes(), self.files["winmm.dll"])

    def test_an_opt_in_variant_is_selected_by_its_short_name(self):
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(
                    base,
                    {"SteamAppId": "999999998", "PROTON_USE_OPTISCALER": "altbridge"},
                    ["run"],
                )
                self.assertEqual(env["PROTON_USE_OPTISCALER"], "test-opti-alt")
                proxy = self.prefix / "drive_c/windows/system32/umu/winmm.dll"
                self.assertEqual(proxy.read_bytes(), self.variant["winmm.dll"])

    def test_each_variant_selects_its_own_payload(self):
        # Two opt-in variants ship now (fsr411b and fsr411f). Selecting one must
        # install that one's files, not the first entry in the manifest.
        for base in BASES:
            for alias, version, expected in (
                ("altbridge", "test-opti-alt", self.variant),
                ("altbridge2", "test-opti-alt2", self.second),
            ):
                with self.subTest(base=base, alias=alias):
                    env = self.run_upscalers(
                        base,
                        {"SteamAppId": "999999998", "PROTON_USE_OPTISCALER": alias},
                        ["run"],
                    )
                    self.assertEqual(env["PROTON_USE_OPTISCALER"], version)
                    proxy = self.prefix / "drive_c/windows/system32/umu/winmm.dll"
                    self.assertEqual(proxy.read_bytes(), expected["winmm.dll"])

    def test_a_bare_one_still_means_this_packages_default(self):
        # protonfixes maps "1" to "default", which matches no entry by name once
        # the manifest carries a variant -- that would refuse the launch.
        for requested in ("1", "default"):
            with self.subTest(requested=requested):
                self.assertEqual(
                    wrapper.optiscaler_version(self.config, requested), "test-opti"
                )
        for base in BASES:
            with self.subTest(base=base):
                env = self.run_upscalers(
                    base,
                    {"SteamAppId": "999999998", "PROTON_USE_OPTISCALER": "1"},
                    ["run"],
                )
                self.assertEqual(env["PROTON_USE_OPTISCALER"], "test-opti")

    def test_an_unknown_version_is_refused_rather_than_silently_replaced(self):
        self.assertEqual(
            wrapper.optiscaler_version(self.config, "9.9.9-nope"), "9.9.9-nope"
        )
        for base in BASES:
            with self.subTest(base=base):
                with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
                    self.run_upscalers(
                        base,
                        {
                            "SteamAppId": "999999998",
                            "PROTON_USE_OPTISCALER": "9.9.9-nope",
                        },
                        ["run"],
                    )

    def test_corrupt_requested_payload_is_refused_before_prefix_writes(self):
        provider = self.work / "artifacts/provider.xz"
        provider.write_bytes(b"corrupted archive")
        before = {str(p): p.read_bytes() for p in self.work.rglob("*") if p.is_file()}
        for base in BASES:
            with self.subTest(base=base):
                with self.assertRaisesRegex(
                    RuntimeError, "failed validation; refusing launch"
                ):
                    self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                self.assertEqual(
                    {
                        str(p): p.read_bytes()
                        for p in self.work.rglob("*")
                        if p.is_file()
                    },
                    before,
                )


class PresetTests(unittest.TestCase):
    def test_fakenvapi_is_bundled_beside_the_other_optiscaler_libraries(self):
        # fakenvapi has to land inside OptiDllPath, because that is "the main
        # folder for OptiScaler to check dll files below" and Libraries.NvapiPath
        # is left at auto. Anywhere else and OptiScaler silently never finds it.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive = work / "opti.tar"
            with tarfile.open(archive, "w") as tar:
                for name in ("OptiScaler", "Licenses"):
                    entry = tarfile.TarInfo(name)
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    tar.addfile(entry)
                for name, data in {
                    "OptiScaler.ini": STUB_INI,
                    "OptiScaler.dll": b"p" * 2048,
                }.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    tar.addfile(entry, io.BytesIO(data))
            # bsdtar detects the format from content, so a plain tar stands in
            # for upstream's .7z without needing 7z tooling here.
            fakenvapi_dll = b"f" * 4096
            fakenvapi = work / "fakenvapi.7z"
            with tarfile.open(fakenvapi, "w") as tar:
                entry = tarfile.TarInfo("fakenvapi.dll")
                entry.size = len(fakenvapi_dll)
                tar.addfile(entry, io.BytesIO(fakenvapi_dll))
            licenses = work / "licenses"
            licenses.mkdir()
            for name in ("NVIDIA-DLSS.txt", "FidelityFX-SDK-4.0.2.txt"):
                (licenses / name).write_text("synthetic test notice")
            payload = work / "payload.dll"
            payload.write_bytes(b"s" * 2048)
            preset = work / "preset.json"
            preset.write_text(json.dumps({"FSR.Fsr4ForceModel": "2"}))
            staging = work / "staging"
            staging.mkdir()
            args = types.SimpleNamespace(
                optiscaler=archive,
                preset=preset,
                proxy="winmm.dll",
                dlss=payload,
                ffx_sdk=payload,
                optipatcher=payload,
                fakenvapi=fakenvapi,
                licenses=licenses,
                optiscaler_version="test-opti",
            )
            _, entry = builder.optiscaler_artifact(args, staging, payload, "test-opti")

        self.assertIn("OptiScaler/fakenvapi.dll", entry["sha256_hash"])
        self.assertEqual(
            entry["sha256_hash"]["OptiScaler/fakenvapi.dll"], sha256(fakenvapi_dll)
        )

    def test_a_bundled_fakenvapi_wins_over_ours(self):
        # Upstream says fakenvapi ships inside OptiScaler 0.9+; the nightly we
        # pin does not, so we add it. If a later build does, theirs must be the
        # one that survives -- ours overwriting it would diverge silently.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            theirs = b"upstream fakenvapi" * 256
            archive = work / "opti.tar"
            with tarfile.open(archive, "w") as tar:
                for name in ("OptiScaler", "Licenses"):
                    entry = tarfile.TarInfo(name)
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    tar.addfile(entry)
                for name, data in {
                    "OptiScaler.ini": STUB_INI,
                    "OptiScaler.dll": b"p" * 2048,
                    "OptiScaler/fakenvapi.dll": theirs,
                }.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    tar.addfile(entry, io.BytesIO(data))
            fakenvapi = work / "fakenvapi.7z"
            with tarfile.open(fakenvapi, "w") as tar:
                ours = b"ours" * 1024
                entry = tarfile.TarInfo("fakenvapi.dll")
                entry.size = len(ours)
                tar.addfile(entry, io.BytesIO(ours))
            licenses = work / "licenses"
            licenses.mkdir()
            for name in ("NVIDIA-DLSS.txt", "FidelityFX-SDK-4.0.2.txt"):
                (licenses / name).write_text("synthetic test notice")
            payload = work / "payload.dll"
            payload.write_bytes(b"s" * 2048)
            preset = work / "preset.json"
            preset.write_text(json.dumps({"FSR.Fsr4ForceModel": "2"}))
            staging = work / "staging"
            staging.mkdir()
            args = types.SimpleNamespace(
                optiscaler=archive, preset=preset, proxy="winmm.dll", dlss=payload,
                ffx_sdk=payload, optipatcher=payload, fakenvapi=fakenvapi,
                licenses=licenses, optiscaler_version="test-opti",
            )
            _, entry = builder.optiscaler_artifact(args, staging, payload, "test-opti")

        self.assertEqual(
            entry["sha256_hash"]["OptiScaler/fakenvapi.dll"], sha256(theirs)
        )

    def test_payload_assembly_fails_if_the_fakenvapi_archive_has_no_dll(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive = work / "opti.tar"
            with tarfile.open(archive, "w") as tar:
                for name in ("OptiScaler", "Licenses"):
                    entry = tarfile.TarInfo(name)
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    tar.addfile(entry)
                for name, data in {
                    "OptiScaler.ini": STUB_INI,
                    "OptiScaler.dll": b"p" * 2048,
                }.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    tar.addfile(entry, io.BytesIO(data))
            fakenvapi = work / "fakenvapi.7z"
            with tarfile.open(fakenvapi, "w") as tar:
                entry = tarfile.TarInfo("README.md")
                entry.size = 4
                tar.addfile(entry, io.BytesIO(b"nope"))
            licenses = work / "licenses"
            licenses.mkdir()
            for name in ("NVIDIA-DLSS.txt", "FidelityFX-SDK-4.0.2.txt"):
                (licenses / name).write_text("synthetic test notice")
            payload = work / "payload.dll"
            payload.write_bytes(b"s" * 2048)
            preset = work / "preset.json"
            preset.write_text(json.dumps({"FSR.Fsr4ForceModel": "2"}))
            staging = work / "staging"
            staging.mkdir()
            args = types.SimpleNamespace(
                optiscaler=archive, preset=preset, proxy="winmm.dll", dlss=payload,
                ffx_sdk=payload, optipatcher=payload, fakenvapi=fakenvapi,
                licenses=licenses, optiscaler_version="test-opti",
            )
            # An upstream rename must stop the build, not ship a payload that
            # quietly lacks the DLL this package advertises.
            with self.assertRaises(Exception):
                builder.optiscaler_artifact(args, staging, payload, "test-opti")

    def test_fallback_payload_assembly_rejects_an_unknown_preset_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive = work / "opti.tar"
            with tarfile.open(archive, "w") as tar:
                for name in ("OptiScaler", "Licenses"):
                    entry = tarfile.TarInfo(name)
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    tar.addfile(entry)
                for name, data in {
                    "OptiScaler.ini": STUB_INI,
                    "OptiScaler.dll": b"p" * 2048,
                }.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    tar.addfile(entry, io.BytesIO(data))
            licenses = work / "licenses"
            licenses.mkdir()
            for name in ("NVIDIA-DLSS.txt", "FidelityFX-SDK-4.0.2.txt"):
                (licenses / name).write_text("synthetic test notice")
            payload = work / "payload.dll"
            payload.write_bytes(b"s" * 2048)
            preset = work / "preset.json"
            preset.write_text(json.dumps({"FSR.MissingKey": "2"}))
            staging = work / "staging"
            staging.mkdir()
            # Exercise the real archive assembly entry, not just the selector
            # that --force-fallback skips in normal package builds.
            args = types.SimpleNamespace(
                optiscaler=archive,
                preset=preset,
                proxy="winmm.dll",
                dlss=payload,
                ffx_sdk=payload,
                optipatcher=payload,
                licenses=licenses,
                optiscaler_version="test-opti",
            )
            with self.assertRaisesRegex(
                RuntimeError, "Unknown OptiScaler preset option"
            ):
                builder.optiscaler_artifact(args, staging, payload, "test-opti")

    def test_preset_uses_protonfixes_case_and_delimiter_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            ini = work / "OptiScaler.ini"
            ini.write_text("[Plugins]\nLoadReshade=auto\n")
            preset = work / "preset.json"
            preset.write_text(json.dumps({"Plugins.LoadReShade": "true"}))
            self.assertEqual(
                builder.validate_preset(preset, ini), {"Plugins.LoadReShade": "true"}
            )
            for key, value in [
                ("plugins.LoadReShade", "true"),
                ("Plugins.LoadReShade", "true;FSR.Fsr4ForceModel=2"),
            ]:
                preset.write_text(json.dumps({key: value}))
                with self.assertRaises(RuntimeError):
                    builder.validate_preset(preset, ini)

    def payload_inputs(self, work):
        """The smallest set of real inputs build-fsr4-payload.py accepts."""
        archive = work / "opti.tar"
        with tarfile.open(archive, "w") as tar:
            for name in ("OptiScaler", "Licenses"):
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                tar.addfile(entry)
            for name, data in {"OptiScaler.ini": STUB_INI,
                               "OptiScaler.dll": b"p" * 2048}.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        fork = work / "fork.tar.xz"
        with tarfile.open(fork, "w:xz") as tar:
            for name, data in {
                "amd_fidelityfx_upscaler_dx12.dll": self.FORK_BRIDGE,
                "notices/PROVENANCE.md": b"fork notices",
            }.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        fakenvapi = work / "fn.7z"
        with tarfile.open(fakenvapi, "w") as tar:
            entry = tarfile.TarInfo("fakenvapi.dll")
            entry.size = 64
            tar.addfile(entry, io.BytesIO(b"f" * 64))
        signed = work / "signed.dll"
        signed.write_bytes(self.SIGNED_BRIDGE)
        provider = work / "prov.xz"
        provider.write_bytes(lzma.compress(b"provider" * 64))
        licenses = work / "lic"
        licenses.mkdir()
        for name in ("NVIDIA-DLSS.txt", "FidelityFX-SDK-4.0.2.txt"):
            (licenses / name).write_text("notice")
        preset = work / "preset.json"
        preset.write_text(json.dumps({"preset": {"FSR.Fsr4ForceModel": "2"}}))
        return archive, fork, fakenvapi, signed, provider, licenses, preset

    SIGNED_BRIDGE = b"signed-amd-bridge" * 512
    FORK_BRIDGE = b"bc250-fork-bridge" * 512

    def build_payload(self, default_name):
        with tempfile.TemporaryDirectory(prefix="payload-default-") as temporary:
            work = Path(temporary)
            archive, fork, fakenvapi, signed, provider, licenses, preset = \
                self.payload_inputs(work)
            output = work / "out"
            output.mkdir()
            command = [
                sys.executable, str(ROOT / "scripts/build-fsr4-payload.py"),
                "--optiscaler", str(archive), "--optiscaler-version", "test-opti",
                "--optipatcher", str(signed), "--fakenvapi", str(fakenvapi),
                "--provider", str(provider), "--ffx-sdk", str(signed),
                "--ffx-sdk-alt", "fsr411f", str(fork), "https://example/rc9",
                "--dlss", str(signed), "--licenses", str(licenses),
                "--preset", str(preset), "--manifest-rel", "upscaler-manifest.json",
                "--proton-rel", "proton", "--output", str(output),
                "--config", str(output / "cfg.json"),
            ]
            if default_name:
                command += ["--ffx-sdk-default", default_name]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = json.loads((output / "cfg.json").read_text())
            manifest = json.loads((output / "upscaler-manifest.json").read_text())
            bridges = {}
            for entry in manifest["optiscaler"]:
                artifact = output / "artifacts" / Path(entry["download_url"]).name
                with tarfile.open(artifact) as tar:
                    data = tar.extractfile(
                        "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").read()
                bridges[entry["version"]] = data
            return config, bridges

    def test_the_shipped_default_bridge_is_the_one_that_was_asked_for(self):
        # Which DLL a player gets without setting anything is the single most
        # consequential thing this builder decides, so it is checked by content
        # rather than by which flag was passed.
        config, bridges = self.build_payload("fsr411f")
        default = config["optiscaler_version"]
        self.assertEqual(bridges[default], self.FORK_BRIDGE)
        # The signed build stays reachable, and the variant's own name still
        # resolves now that it is the default.
        aliases = config["optiscaler_aliases"]
        self.assertEqual(aliases["fsr411f"], default)
        self.assertEqual(bridges[aliases["signed"]], self.SIGNED_BRIDGE)

    def test_without_the_flag_the_signed_bridge_is_still_the_default(self):
        config, bridges = self.build_payload("")
        self.assertEqual(bridges[config["optiscaler_version"]], self.SIGNED_BRIDGE)
        self.assertNotIn("signed", config["optiscaler_aliases"])

    def test_a_default_naming_no_variant_fails_the_build(self):
        with self.assertRaises(AssertionError):
            self.build_payload("nosuchvariant")

    def test_fakenvapi_does_not_log_unless_asked(self):
        # fakenvapi's compiled default is enable_logs=true, and it reads
        # fakenvapi.ini from its own directory -- one this package did not ship.
        # So it logged on every launch while BC250_FSR4_DEBUG was presented as
        # the way to ask for logs.
        with tempfile.TemporaryDirectory() as temporary:
            extracted = Path(temporary) / "extracted"
            (extracted / "OptiScaler").mkdir(parents=True)
            (extracted / "OptiScaler/fakenvapi.dll").write_bytes(b"f" * 16)
            settings = builder.seed_fakenvapi_settings(extracted)
            self.assertEqual(settings, extracted / "OptiScaler/fakenvapi.ini")
            parser = configparser.ConfigParser()
            parser.read(settings)
            self.assertEqual(parser["fakenvapi"]["enable_logs"], "0")
            self.assertEqual(parser["fakenvapi"]["enable_trace_logs"], "0")

    def test_a_bundled_fakenvapi_keeps_its_own_settings(self):
        # If OptiScaler starts shipping fakenvapi, its ini belongs to that build.
        with tempfile.TemporaryDirectory() as temporary:
            extracted = Path(temporary) / "extracted"
            (extracted / "OptiScaler").mkdir(parents=True)
            (extracted / "OptiScaler/nvapi64.dll").write_bytes(b"f" * 16)
            (extracted / "OptiScaler/fakenvapi.ini").write_text(
                "[fakenvapi]\nenable_logs=1\n")
            builder.seed_fakenvapi_settings(extracted)
            parser = configparser.ConfigParser()
            parser.read(extracted / "OptiScaler/fakenvapi.ini")
            self.assertEqual(parser["fakenvapi"]["enable_logs"], "1")

    def test_no_fakenvapi_means_no_settings_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            extracted = Path(temporary) / "extracted"
            (extracted / "OptiScaler").mkdir(parents=True)
            self.assertIsNone(builder.seed_fakenvapi_settings(extracted))
            self.assertFalse((extracted / "OptiScaler/fakenvapi.ini").exists())

    def test_a_seed_once_key_the_preset_does_not_set_fails_the_build(self):
        # The launcher looks these up in the preset it was handed. A name that
        # is not there would quietly seed nothing, and the packaged spoofing
        # default would silently become OptiScaler's instead of ours.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            ini = work / "OptiScaler.ini"
            ini.write_text("[Spoofing]\nDxgi=auto\n")
            preset = work / "preset.json"
            preset.write_text(json.dumps({
                "preset": {"Spoofing.Dxgi": "false"},
                "seed_once": ["Spoofing.Dxgi"],
            }))
            self.assertEqual(
                builder.validate_preset(preset, ini), {"Spoofing.Dxgi": "false"}
            )
            preset.write_text(json.dumps({
                "preset": {"Spoofing.Dxgi": "false"},
                "seed_once": ["Spoofing.Vulkan"],
            }))
            with self.assertRaisesRegex(RuntimeError, "seed_once names a key"):
                builder.validate_preset(preset, ini)


if __name__ == "__main__":
    unittest.main()
