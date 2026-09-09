"""Exercise both actual upstream modules with local payloads and no network."""

import ast
import hashlib
import importlib.util
import io
import json
import lzma
import subprocess
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
            "OptiScaler.ini": b"[FSR]\nFsr4ForceModel=auto\n",
        }
        archive = artifacts / "opti.tar.xz"
        with tarfile.open(archive, "w:xz") as tar:
            for name, data in self.files.items():
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
                }
            ],
        }
        (self.work / "manifest.json").write_text(json.dumps(manifest))
        self.config = {
            "manifest": "manifest.json",
            "proxy": "winmm.dll",
            "provider_version": "4.1.1",
            "optiscaler_version": "test-opti",
            "preset": {"FSR.Fsr4ForceModel": "2"},
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
                    "OptiScaler.ini": b"[FSR]\nFsr4ForceModel=auto\n",
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
                builder.optiscaler_artifact(args, staging)

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


if __name__ == "__main__":
    unittest.main()
