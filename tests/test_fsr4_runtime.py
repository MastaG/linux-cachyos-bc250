"""Exercise both actual upstream modules with local payloads and no network."""

import ast
import configparser
import hashlib
import importlib.util
import io
import itertools
import json
import lzma
import os
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "packages/bc250-fsr4-common"
BASES = {
    "ge-proton": "4128896c4134d865a290e2e8e62279d07157131b207f4bc7d29e8c873fe85645",
    "proton-cachyos": "c73c4827035f3db58088f66fb17b89f7b775616da8fb643d3b06474daa7ca911",
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


# Shaped like the real OptiScaler.ini in the part that matters here: every key
# ships as "auto", which is what marks a prefix as having no opinion of its own
# yet -- for the shared preset, which seeds a prefix and then leaves it alone.
STUB_INI = (
    # The pinned 20261025 nightly defines Fsr4GpuSupport (the renamed model
    # switch) and no longer Fsr4ForceModel; the old name is kept in this fixture
    # as well so the paired expectations across this file stay meaningful.
    b"[FSR]\nFsr4ForceModel=auto\nFsr4GpuSupport=auto\nUpscalerIndex=auto\n"
    b"[Spoofing]\nDxgi=auto\nVulkanExtensionSpoofing=auto\n"
    b"[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n"
    b"[Upscalers]\nDx12Upscaler=auto\n[FrameGen]\nEnabled=auto\nFGInput=auto\nFGNvngxReplacement=auto\n"
    b"FGOutput=auto\n[XeFG]\nInterpolationCount=auto\nForceBorderless=auto\n"
    b"[fakenvapi]\nForceReflex=auto\n"
)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {}
        fixtures = {
            "ge-proton": ROOT / "tests/fixtures/ge-proton11-6-upscalers.py",
            "proton-cachyos": ROOT / "tests/fixtures/cachyos-native-upscalers.py",
        }
        for base, expected_hash in BASES.items():
            original = fixtures[base].read_bytes()
            assert sha256(original) == expected_hash
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / (
                    "protonfixes/upscalers.py"
                    if base == "ge-proton"
                    else "upscalers.py"
                )
                source.parent.mkdir(exist_ok=True)
                source.write_bytes(original)
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
        self.game_dirs = itertools.count()
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
                    "proxy": "winmm.dll",
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
                    "proxy": "winmm.dll",
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
                    "proxy": "winmm.dll",
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
                "FrameGen.Enabled": "false",
                "Spoofing.Dxgi": "false",
                "Spoofing.VulkanExtensionSpoofing": "false",
            },
            # Which keys each build's own ini defines, as the builder writes it:
            # every fixture variant ships STUB_INI.
            "optiscaler_ini_keys": {version: sorted(
                f"{section}.{option}" for section, option in
                [("FrameGen", o) for o in
                 ("Enabled", "FGInput", "FGOutput", "FGNvngxReplacement")]
                + [("FSR", o) for o in ("Fsr4ForceModel", "Fsr4GpuSupport", "UpscalerIndex")]
                + [("Spoofing", o) for o in ("Dxgi", "VulkanExtensionSpoofing")]
                + [("Libraries", o) for o in ("FfxDx12Path", "FfxDx12SRPath")]
                + [("Upscalers", "Dx12Upscaler")]
                + [("XeFG", o) for o in ("InterpolationCount", "ForceBorderless")]
                + [("fakenvapi", "ForceReflex")]
            ) for version in ("test-opti", "test-opti-alt", "test-opti-alt2")},
        }

    def upscalers_module(self, base):
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
        return module

    def run_upscalers(self, base, inherited, arguments):
        game = wrapper.game_launch(arguments, inherited)
        with mock.patch.object(wrapper, "TOOL", self.work):
            # As main() does: a variant switch starts the prefix's ini fresh,
            # before environment() reads it.
            if game:
                wrapper.start_fresh_on_switch(self.config, inherited)
            env = wrapper.environment(self.config, inherited, game=game)
            # As main() does, before Proton runs protonfixes.
            if game:
                self.cleaned = wrapper.clean_other_variants(self.config, env, inherited)
        enabled = {
            feature
            for key, feature in [
                ("PROTON_FSR4_UPGRADE", "fsr4"),
                ("PROTON_USE_OPTISCALER", "optiscaler"),
            ]
            if env.get(key, "0") != "0"
        }
        module = self.upscalers_module(base)
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

    def add_variant(self, alias, files):
        """Another opt-in variant in the manifest, with files of its own."""
        version = "test-opti-" + alias
        archive = self.work / "artifacts" / (version + ".tar.xz")
        with tarfile.open(archive, "w:xz") as tar:
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        manifest = json.loads((self.work / "manifest.json").read_text())
        manifest["optiscaler"].append({
            "version": version,
            "proxy": "winmm.dll",
            "is_dev_file": False,
            "download_url": "artifacts/" + archive.name,
            "zip_sha256_hash": sha256(archive.read_bytes()),
            "sha256_hash": {n: sha256(d) for n, d in files.items() if not n.endswith(".ini")},
            "md5_hash": {n: "" if n.endswith(".ini") else hashlib.md5(d).hexdigest()
                         for n, d in files.items()},
        })
        (self.work / "manifest.json").write_text(json.dumps(manifest))
        self.config["optiscaler_aliases"][alias] = version
        return version

    def add_scaler_and_freefg(self):
        scaler = dict(self.files, **{
            "winmm.dll": b"scaler-proxy" * 128,
            "HelixSR-fsrfg/amd_fidelityfx_dx12.dll": b"helixsr" * 256,
            "HelixSR-fsrfg/helixsr.ini": b"[Log]\nEnabled = true\n",
            "HelixSR-fsrfg/helixsr-fg/310.9.16/nvngx_dlssg.dll": b"light" * 256,
            "OptiScaler/libxess_fg.dll": b"intel-xefg" * 256,
        })
        freefg = dict(self.files, **{
            "winmm.dll": b"freefg-proxy" * 128,
            "OptiScaler/libxess_fg.dll": b"freefg-wrapper" * 256,
            "OptiScaler/bc250_xefg_original.dll": b"intel-xefg" * 256,
            "OptiScaler/BC250-XeFG/layer/layer.json": b"{}" * 512,
            "OptiScaler/BC250-XeFG/shaders/waves.txt": b"waves" * 256,
        })
        versions = self.add_variant("scalerlike", scaler), self.add_variant("freefglike", freefg)
        self.config["freefg"] = {versions[1]: {
            "layer": "VK_LAYER_BC250_xefg_wave",
            "layer_dir": "OptiScaler/BC250-XeFG/layer",
            "wave_config": "OptiScaler/BC250-XeFG/shaders/waves.txt",
            "dll_path": "C:\\windows\\system32\\umu\\OptiScaler"}}
        return scaler, freefg

    def launch(self, base, variant=None, **extra):
        inherited = dict({"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)}, **extra)
        if variant:
            inherited["PROTON_USE_OPTISCALER"] = variant
        return self.run_upscalers(base, inherited, ["run"])

    def test_switching_variants_leaves_no_files_of_the_previous_one(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                scaler, freefg = self.add_scaler_and_freefg()
                umu = self.umu()
                self.launch(base, "scalerlike")
                self.assertEqual((umu / "winmm.dll").read_bytes(), scaler["winmm.dll"])
                # Written at run time, so protonfixes never knew about them.
                (umu / "HelixSR-fsrfg/helixsr.log").write_text("log")
                (umu / "HelixSR-fsrfg/helixsr-fg/310.9.16/hxfg.log").write_text("log")

                self.launch(base, "freefglike")
                self.assertFalse((umu / "HelixSR-fsrfg").exists())
                for name, data in freefg.items():
                    if not name.endswith(".ini"):
                        self.assertEqual((umu / name).read_bytes(), data, name)
                (umu / "OptiScaler/BC250-MFG.log").write_text("log")

                # Back to the plain default: FreeFG's folder and logs go too.
                self.launch(base)
                self.assertFalse((umu / "OptiScaler/BC250-XeFG").exists())
                self.assertFalse((umu / "OptiScaler/BC250-MFG.log").exists())
                self.assertFalse((umu / "OptiScaler/bc250_xefg_original.dll").exists())
                self.assertFalse((umu / "OptiScaler/libxess_fg.dll").exists())
                self.assertEqual((umu / "winmm.dll").read_bytes(), self.files["winmm.dll"])
                self.assertTrue((umu / "OptiScaler.ini").is_file())

    def test_the_selected_variants_own_files_are_left_alone(self):
        # Relaunching the same variant removes nothing, not even its logs.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.add_scaler_and_freefg()
                self.launch(base, "scalerlike")
                log = self.umu() / "HelixSR-fsrfg/helixsr.log"
                log.write_text("keep me")
                self.launch(base, "scalerlike")
                self.assertEqual(self.cleaned, [])
                self.assertEqual(log.read_text(), "keep me")

    def test_a_freefg_run_does_not_leave_frame_generation_on_for_the_default(self):
        # Ghost of Tsushima: a freefg run answers FrameGen.Enabled/FGInput/FGOutput
        # in the shared ini, seed_once then treats those as somebody's decision and
        # the default path inherits frame generation on a switch. A switch now removes
        # the prefix's ini, protonfixes re-copies it, and the preset seeds from scratch.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                # FreeFG's own OptiScaler build: its ini carries the renamed
                # Fsr4GpuSupport that the default's build does not have.
                freefg_files = dict(self.files, **{
                    "OptiScaler.ini": STUB_INI.replace(
                        b"UpscalerIndex=auto\n",
                        b"UpscalerIndex=auto\n", 1),
                    "OptiScaler/libxess_fg.dll": b"freefg-wrapper" * 512,
                })
                freefg_version = self.add_variant("freefglike", freefg_files)
                self.config["optiscaler_variant_preset"] = {freefg_version: builder.FREEFG_PRESET}
                expected = {**self.config["preset"], **builder.FREEFG_PRESET}
                expected = {k: v for k, v in expected.items() if v is not None}
                self.assertEqual(self.handed(self.launch(base, "freefglike")), expected)

                # In real use, protonfixes has put FreeFG's own wrapper in the
                # prefix by now; that is what marks the switch on disk.
                (self.umu() / "OptiScaler/libxess_fg.dll").write_bytes(b"freefg-wrapper")
                switched = self.handed(self.launch(base))
                # The switch deleted the prefix's ini, so the default re-seeds from
                # scratch and frame generation is off again (was: left on by freefg).
                self.assertEqual(switched["FrameGen.Enabled"], "false")
                # Nothing of FreeFG's layer is handed over: the fresh ini already
                # says auto for it, so there is nothing to reset.
                self.assertNotIn("XeFG.InterpolationCount", switched)
                self.assertNotIn("FrameGen.FGOutput", switched)
                self.assertNotIn("FSR.Fsr4GpuSupport", switched)

                # The next launch is no switch: the seed is the prefix's answer now.
                again = self.handed(self.launch(base))
                self.assertNotIn("FrameGen.Enabled", again)
                self.assertEqual(self.read_ini()["FrameGen"]["enabled"], "false")

    def test_a_player_answer_on_the_selected_variant_still_persists(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                env = self.launch(base)
                self.assertEqual(self.read_ini()["FrameGen"]["enabled"], "false")
                # The overlay's Save Settings writes the prefix's own ini, and the
                # handover this launch was what put the key in the file.
                self.assertIn("FrameGen.Enabled=false", env["PROTON_OPTISCALER_CONFIG"])
                ini = self.prefix / "drive_c/windows/system32/umu/OptiScaler.ini"
                parser = self.read_ini()
                parser["FrameGen"]["enabled"] = "true"
                with ini.open("w") as stream:
                    parser.write(stream)
                env = self.launch(base)
                self.assertNotIn("FrameGen.Enabled", env["PROTON_OPTISCALER_CONFIG"])
                self.assertEqual(self.read_ini()["FrameGen"]["enabled"], "true")

    def test_the_default_ships_every_frame_gen_key_at_auto(self):
        # What keeps a fresh prefix frame-generation free where no variant asks
        # for it: the shipped help says auto for Enabled is false and auto for
        # FGInput is nofg. The Scaler's frame generation keys are its seed, only
        # ever seeded (is_player_key), so the menu's box can still turn it off.
        for name in builder.SCALER_PRESET:
            if name.startswith("FrameGen."):
                self.assertTrue(builder.is_player_key(name), name)
        keys = self.config["preset"]
        self.assertEqual(keys["FrameGen.Enabled"], "false")
        ini = configparser.ConfigParser()
        ini.read_string(STUB_INI.decode())
        for option in ("enabled", "fginput", "fgoutput", "fgnvngxreplacement"):
            self.assertEqual(ini["FrameGen"][option], "auto", option)

    def test_no_preset_names_helixsrs_own_dlss_frame_generation_switch(self):
        # helixsr.ini ships [DlssFrameGeneration] Enabled = true, which its own
        # comment reads as "available when the game turns it on". We never write
        # that file, so OptiScaler's Enabled=false is what has to keep the route
        # closed -- and on board1 (2026-10-24) it does not: with FGInput set to
        # nvngxfg and FGNvngxReplacement to HelixSR, HelixSR's FG core loads while
        # Enabled stays false. Only the routing keys and helixsr.ini decide it.
        for name in self.config["preset"]:
            self.assertFalse(name.startswith("DlssFrameGeneration."), name)
        for layer in self.config.get("optiscaler_variant_preset", {}).values():
            for name in layer:
                self.assertFalse(name.startswith("DlssFrameGeneration."), name)
        for name in builder.SCALER_PRESET:
            self.assertFalse(name.startswith("DlssFrameGeneration."), name)
        for name in builder.FREEFG_PRESET:
            self.assertFalse(name.startswith("DlssFrameGeneration."), name)

    def read_ini(self):
        parser = configparser.ConfigParser()
        parser.read(self.prefix / "drive_c/windows/system32/umu/OptiScaler.ini")
        return parser

    def handed(self, env):
        """What the launcher handed protonfixes for this launch."""
        return dict(part.split("=", 1) for part in
                    env["PROTON_OPTISCALER_CONFIG"].split(";") if part)

    def test_nothing_is_cleaned_while_optiscaler_is_off(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.add_scaler_and_freefg()
                self.launch(base, "scalerlike")
                self.launch(base, PROTON_FSR4_UPGRADE="0")
                self.assertEqual(self.cleaned, [])
                self.assertTrue((self.umu() / "HelixSR-fsrfg/helixsr.ini").is_file())

    def test_a_retired_helixsr_folder_goes_whatever_the_manifest_says(self):
        # Scaler 1.1.0's HelixSR-fsrfg is in no manifest any more, and Scaler 2.0
        # would still find the HelixSR 2.0 inside it beside its proxy.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                old = self.umu() / "HelixSR-fsrfg/helixsr-fg"
                old.mkdir(parents=True)
                (old.parent / "amd_fidelityfx_dx12.dll").write_bytes(b"helixsr 2.0")
                self.launch(base)
                self.assertFalse((self.umu() / "HelixSR-fsrfg").exists())
                self.assertIn("HelixSR-fsrfg/", self.cleaned)

    def test_a_prefix_from_the_helixsr_2_default_starts_fresh(self):
        # freefg-helixsr, HelixSR 2.0 as OptiScaler's FidelityFX library, was the
        # default until 2026-10-29. Its DLL and ini are in no manifest any more,
        # and the prefix's OptiScaler.ini still points FfxDx12Path at that DLL.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                # A FreeFG variant, so OptiScaler/ itself stays and only the two
                # files go.
                self.add_scaler_and_freefg()
                self.launch(base, "freefglike")
                umu = self.umu()
                (umu / "OptiScaler/amd_fidelityfx_dx12.dll").write_bytes(b"helixsr 2.0")
                (umu / "OptiScaler/helixsr.ini").write_text("[Log]\nEnabled = true\n")
                ini = umu / "OptiScaler.ini"
                ini.write_text(ini.read_text() + "; left by freefg-helixsr\n")
                self.launch(base, "freefglike")
                self.assertFalse((umu / "OptiScaler/amd_fidelityfx_dx12.dll").exists())
                self.assertFalse((umu / "OptiScaler/helixsr.ini").exists())
                self.assertIn("OptiScaler/amd_fidelityfx_dx12.dll", self.cleaned)
                self.assertTrue((umu / "OptiScaler/libxess_fg.dll").is_file())
                self.assertTrue(ini.is_file())
                self.assertNotIn("freefg-helixsr", ini.read_text())
                # Once gone, the next launch is no switch: the ini stays.
                ini.write_text(ini.read_text() + "; the player's\n")
                self.launch(base, "freefglike")
                self.assertIn("; the player's", ini.read_text())

    def test_cleaning_does_not_follow_a_link_out_of_the_prefix(self):
        self.add_scaler_and_freefg()
        outside = self.work / "outside"
        (outside / "helixsr-fg").mkdir(parents=True)
        (outside / "helixsr.ini").write_text("not ours")
        self.umu().mkdir(parents=True)
        (self.umu() / "HelixSR-fsrfg").symlink_to(outside)
        self.launch("proton-cachyos", "freefglike")
        self.assertEqual((outside / "helixsr.ini").read_text(), "not ours")
        self.assertTrue((outside / "helixsr-fg").is_dir())

    def test_freefg_points_vulkan_at_its_layer_in_the_prefix(self):
        self.add_scaler_and_freefg()
        layer_dir = self.umu() / "OptiScaler/BC250-XeFG/layer"
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(self.config, {
                "SteamAppId": "1", "STEAM_COMPAT_DATA_PATH": str(self.compat),
                "PROTON_USE_OPTISCALER": "freefglike",
                "VK_LAYER_PATH": "/elsewhere", "VK_INSTANCE_LAYERS": "VK_LAYER_mine",
                "VKD3D_CONFIG": "dxr"}, game=True)
        self.assertEqual(env["VK_LAYER_PATH"], f"{layer_dir}:/elsewhere")
        self.assertEqual(env["VK_INSTANCE_LAYERS"], "VK_LAYER_BC250_xefg_wave:VK_LAYER_mine")
        self.assertEqual(env["XEFG_WAVE_CONFIG"],
                         str(self.umu() / "OptiScaler/BC250-XeFG/shaders/waves.txt"))
        self.assertEqual(env["VKD3D_CONFIG"], "dxr,no_staggered_submit")
        # The wrapper's forwarded exports name bc250_xefg_original, which the
        # loader only finds on the DLL search path; without this OptiScaler got
        # NULL for them and Spider-Man 2 crashed creating its swapchain.
        self.assertEqual(env["WINEPATH"], "C:\\windows\\system32\\umu\\OptiScaler")

    def test_freefg_keeps_an_existing_winepath(self):
        self.add_scaler_and_freefg()
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(self.config, {
                "SteamAppId": "1", "WINEPREFIX": str(self.prefix),
                "PROTON_USE_OPTISCALER": "freefglike", "WINEPATH": "D:\\tools"}, game=True)
        self.assertEqual(env["WINEPATH"], "C:\\windows\\system32\\umu\\OptiScaler;D:\\tools")

    def test_a_variant_can_drop_a_shared_preset_key(self):
        # A shared key the selected build's OptiScaler.ini does not define would
        # stop the launch in protonfixes, so a variant drops it with None. Both
        # pinned builds define Fsr4GpuSupport now, so the demo names a key
        # neither fixture ini has.
        self.add_scaler_and_freefg()
        version = self.config["optiscaler_aliases"]["freefglike"]
        self.config["optiscaler_variant_preset"] = {
            version: {"FSR.Fsr4RenamedAway": None, "FSR.Fsr4GpuSupport": "auto"}}
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(self.config, {
                "SteamAppId": "1", "PROTON_USE_OPTISCALER": "freefglike"}, game=True)
            other = wrapper.environment(self.config, {"SteamAppId": "1"}, game=True)
        self.assertNotIn("Fsr4RenamedAway", env["PROTON_OPTISCALER_CONFIG"])
        self.assertIn("FSR.Fsr4GpuSupport=auto", env["PROTON_OPTISCALER_CONFIG"])
        self.assertIn("FSR.Fsr4ForceModel=2", other["PROTON_OPTISCALER_CONFIG"])

    def test_freefgs_own_switch_keeps_staggered_submit(self):
        self.add_scaler_and_freefg()
        with mock.patch.object(wrapper, "TOOL", self.work):
            env = wrapper.environment(self.config, {
                "SteamAppId": "1", "WINEPREFIX": str(self.prefix),
                "PROTON_USE_OPTISCALER": "freefglike",
                "BC250_XEFG_NO_STAGGERED_SUBMIT": "0"}, game=True)
        self.assertNotIn("VKD3D_CONFIG", env)

    def test_other_variants_get_no_layer(self):
        self.add_scaler_and_freefg()
        for variant in ("", "scalerlike", "altbridge"):
            with self.subTest(variant=variant), mock.patch.object(wrapper, "TOOL", self.work):
                inherited = {"SteamAppId": "1", "WINEPREFIX": str(self.prefix)}
                if variant:
                    inherited["PROTON_USE_OPTISCALER"] = variant
                env = wrapper.environment(self.config, inherited, game=True)
                for name in ("VK_LAYER_PATH", "VK_INSTANCE_LAYERS", "XEFG_WAVE_CONFIG",
                             "VKD3D_CONFIG", "WINEPATH"):
                    self.assertNotIn(name, env)

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

    def proxy_game(self, name, **extra):
        return dict(
            {"SteamAppId": "999999998", "PROTON_OPTISCALER_NAME": name}, **extra
        )

    def umu(self):
        return self.prefix / "drive_c/windows/system32/umu"

    def test_a_requested_proxy_name_is_a_file_wine_can_redirect_to(self):
        # Wine's loader sends the imported name to umu\\<name>. The payload is
        # baked as winmm.dll, so before this a dxgi request pointed at a file
        # that was not there and Wine quietly used its builtin dxgi.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.run_upscalers(base, self.proxy_game("dxgi"), ["run"])
                link = self.umu() / "dxgi.dll"
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), "winmm.dll")
                self.assertEqual(link.read_bytes(), self.files["winmm.dll"])

    def test_the_default_name_gets_no_extra_file(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.run_upscalers(base, {"SteamAppId": "999999998"}, ["run"])
                self.assertEqual(
                    sorted(p.name for p in self.umu().glob("*.dll")), ["winmm.dll"]
                )

    def test_a_proxy_name_follows_the_variant_that_is_selected(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                self.run_upscalers(
                    base,
                    self.proxy_game("dxgi.dll", PROTON_USE_OPTISCALER="altbridge"),
                    ["run"],
                )
                self.assertEqual(
                    (self.umu() / "dxgi.dll").read_bytes(), self.variant["winmm.dll"]
                )

    def test_an_existing_proxy_link_is_left_alone(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                before = os.lstat(self.umu() / "dxgi.dll")
                self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                after = os.lstat(self.umu() / "dxgi.dll")
                self.assertEqual((before.st_ino, before.st_mtime_ns),
                                 (after.st_ino, after.st_mtime_ns))

    def test_a_stale_file_under_the_requested_name_is_replaced(self):
        # A prefix made by a package that was built with another proxy name
        # leaves a real, outdated DLL where the new name has to point at ours.
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                self.umu().mkdir(parents=True)
                (self.umu() / "dxgi.dll").write_bytes(b"outdated payload" * 128)
                self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                self.assertEqual(
                    (self.umu() / "dxgi.dll").read_bytes(), self.files["winmm.dll"]
                )

    def test_a_prefix_without_symlinks_gets_a_copy_that_stays_current(self):
        for base in BASES:
            with self.subTest(base=base):
                self.setUp()
                with mock.patch("pathlib.Path.symlink_to", side_effect=OSError("no")):
                    self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                    copy = self.umu() / "dxgi.dll"
                    self.assertFalse(copy.is_symlink())
                    self.assertEqual(copy.read_bytes(), self.files["winmm.dll"])
                    before = os.lstat(copy)
                    self.run_upscalers(base, self.proxy_game("dxgi.dll"), ["run"])
                    self.assertEqual(before.st_ino, os.lstat(copy).st_ino)
                    self.run_upscalers(
                        base,
                        self.proxy_game("dxgi.dll", PROTON_USE_OPTISCALER="altbridge"),
                        ["run"],
                    )
                    self.assertEqual(copy.read_bytes(), self.variant["winmm.dll"])

    def test_protonfixes_will_not_link_over_a_pinned_file(self):
        module = self.upscalers_module("proton-cachyos")
        expose = getattr(module, "__expose_proxy")
        item = {
            "proxy": "winmm.dll",
            "sha256_hash": {"winmm.dll": "0" * 64, "nvngx_dlss.dll": "1" * 64},
        }
        for bad in ("nvngx_dlss.dll", "NVNGX_DLSS.DLL", "a/b.dll", "dxgi", "..dll"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(RuntimeError, "not usable"):
                    expose(str(self.prefix), "umu/", item, bad)
        # The packaged name and its case variants need nothing at all.
        expose(str(self.prefix), "umu/", item, "WINMM.dll")
        self.assertFalse((self.prefix / "umu").exists())

    def test_a_manifest_without_a_recorded_proxy_links_nothing(self):
        module = self.upscalers_module("proton-cachyos")
        getattr(module, "__expose_proxy")(
            str(self.prefix), "umu/", {"sha256_hash": {}}, "dxgi.dll"
        )
        self.assertFalse((self.prefix / "umu").exists())

    def test_the_builder_records_the_proxy_it_baked_in(self):
        self.assertIn('"proxy": args.proxy', (ROOT / "scripts/build-fsr4-payload.py").read_text())

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

                # What the overlay's "Save Settings" does, for a spoofing key and
                # for one the preset used to enforce on every launch.
                parser["Spoofing"]["dxgi"] = "true"
                parser["FSR"]["fsr4forcemodel"] = "3"
                with ini.open("w") as stream:
                    parser.write(stream)

                self.run_upscalers(base, inherited, ["run"])
                parser = configparser.ConfigParser()
                parser.read(ini)
                self.assertEqual(parser["Spoofing"]["dxgi"], "true")
                self.assertEqual(parser["FSR"]["fsr4forcemodel"], "3")
                # Nobody ever touched this one, so the first launch's seed stands.
                self.assertEqual(
                    parser["Spoofing"]["vulkanextensionspoofing"], "false")

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

    def test_a_variants_own_settings_apply_only_when_it_is_selected(self):
        # A variant's own library paths must not leak into the variants that
        # share the same preset.
        paths = {"Libraries.FfxDx12Path": "C:\\x\\amd_fidelityfx_dx12.dll",
                 "Libraries.FfxDx12SRPath": "C:\\x\\amd_fidelityfx_upscaler_dx12.dll"}
        self.config["optiscaler_aliases"]["testvariant"] = "test-opti-testvariant"
        self.config["optiscaler_variant_preset"] = {"test-opti-testvariant": paths}
        default = self.applied_preset({"SteamAppId": "999999998"})
        for key in paths:
            self.assertNotIn(key, default)
        chosen = self.applied_preset(
            {"SteamAppId": "999999998", "PROTON_USE_OPTISCALER": "testvariant"})
        for key, value in paths.items():
            self.assertEqual(chosen[key], value)
        # A launch option still has the last word.
        overridden = self.applied_preset({
            "SteamAppId": "999999998", "PROTON_USE_OPTISCALER": "testvariant",
            "BC250_OPTISCALER_EXTRA": "Libraries.FfxDx12Path=auto"})
        self.assertEqual(overridden["Libraries.FfxDx12Path"], "auto")

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
        """A fresh install root per call.

        These used to share one directory and delete only the files between
        subtests, which left the marker *directories* behind -- so every case
        after the first passed on the previous case's leftovers rather than on
        its own layout, and a real gap in the scan went unnoticed until it was
        run against a game on hardware.
        """
        root = self.work / f"game-{next(self.game_dirs)}"
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
            # The Unreal Engine layout, four levels down -- the common case.
            "Game/Binaries/Win64/EasyAntiCheat/easyanticheat_x64.dll",
            "Game/Binaries/Win64/EasyAntiCheat_EOS/marker.txt",
            "Game/Binaries/Win64/start_protected_game.exe",
            "BattlEye/BEService.exe",
            "Game/Binaries/Win64/BEClient_x64.dll",
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

    def anticheat_env(self, **extra):
        inherited = dict({"SteamAppId": "999999998",
                          "STEAM_COMPAT_TOOL_PATHS": "/steam/Proton EasyAntiCheat Runtime/"},
                         **extra)
        with mock.patch.object(wrapper, "TOOL", self.work):
            return wrapper.environment(self.config, inherited, game=True)

    def test_a_player_can_ignore_the_guard_for_one_game(self):
        env = self.anticheat_env(BC250_FSR4_IGNORE_ANTICHEAT="1")
        self.assertNotEqual(env["PROTON_FSR4_UPGRADE"], "0")
        self.assertNotEqual(env["PROTON_USE_OPTISCALER"], "0")

    def test_a_file_ignores_the_guard_for_every_game(self):
        # Steam has no global environment setting, hence a file. Found under
        # XDG_CONFIG_HOME, else under HOME/.config.
        home = self.work / "home"
        for extra in ({"HOME": str(home)},
                      {"HOME": "/nonexistent", "XDG_CONFIG_HOME": str(home / ".config")}):
            with self.subTest(extra=extra):
                self.assertEqual(self.anticheat_env(**extra)["PROTON_FSR4_UPGRADE"], "0")
                switch = home / ".config/bc250-fsr4/ignore-anticheat"
                switch.parent.mkdir(parents=True, exist_ok=True)
                switch.touch()
                try:
                    env = self.anticheat_env(**extra)
                finally:
                    switch.unlink()
                self.assertNotEqual(env["PROTON_FSR4_UPGRADE"], "0")
                self.assertNotEqual(env["PROTON_USE_OPTISCALER"], "0")

    def test_only_one_means_ignore(self):
        for value in ("0", "", "yes"):
            with self.subTest(value=value):
                env = self.anticheat_env(BC250_FSR4_IGNORE_ANTICHEAT=value)
                self.assertEqual(env["PROTON_FSR4_UPGRADE"], "0")

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
        self.assertEqual(applied["FSR.Fsr4ForceModel"], "2")

        # Freshly extracted, so still "auto" -- also nobody's opinion.
        self.write_prefix_ini(STUB_INI.decode())
        applied = self.applied_preset(
            {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
        self.assertEqual(applied["Spoofing.Dxgi"], "false")

    def test_the_shipped_preset_lets_optiscaler_decide_spoofing(self):
        # FreeFG's and HelixSR Scaler's own installers leave Dxgi=auto: OptiScaler
        # spoofs when the game ships nvngx_dlss.dll, so it offers DLSS. Forced off,
        # SOTTR lost its DLSS row (2026-10-26). The menu forces it per game.
        shipped = json.loads((ROOT / "packages/bc250-fsr4-common/optiscaler-preset.json").read_text())
        self.assertEqual(shipped["preset"]["Spoofing.Dxgi"], "auto")
        # The extension spoofing stays off: that one was the "DX12 not supported" report.
        self.assertEqual(shipped["preset"]["Spoofing.VulkanExtensionSpoofing"], "false")

    def test_a_variant_can_seed_its_own_spoofing(self):
        # FreeFG and HelixSR Scaler: "auto" over the shared false in a fresh prefix,
        # and again while the ini still says "auto" (nobody has decided).
        self.config["optiscaler_variant_seed"] = {
            self.config["optiscaler_version"]: {"Spoofing.Dxgi": "auto"}}
        inherited = {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)}
        self.assertEqual(self.applied_preset(inherited)["Spoofing.Dxgi"], "auto")
        self.write_prefix_ini("[Spoofing]\nDxgi=auto\nVulkanExtensionSpoofing=auto\n")
        self.assertEqual(self.applied_preset(inherited)["Spoofing.Dxgi"], "auto")
        # The player turned it off in the overlay and saved: nothing is handed over.
        self.write_prefix_ini("[Spoofing]\nDxgi=false\nVulkanExtensionSpoofing=auto\n")
        self.assertNotIn("Spoofing.Dxgi", self.applied_preset(inherited))

    def test_a_value_the_player_chose_is_not_written_over(self):
        self.write_prefix_ini(
            "[FSR]\nFsr4ForceModel=3\n"
            "[Spoofing]\nDxgi=true\nVulkanExtensionSpoofing=auto\n"
        )
        applied = self.applied_preset(
            {"SteamAppId": "999999998", "WINEPREFIX": str(self.prefix)})
        # Left out entirely, so protonfixes keeps whatever the file says: every
        # key of the shared preset is seeded once, not enforced on top of a
        # prefix that has an answer, whatever wrote that answer.
        self.assertNotIn("Spoofing.Dxgi", applied)
        self.assertNotIn("FSR.Fsr4ForceModel", applied)
        # Still "auto", so nobody has decided and the packaged value seeds it.
        self.assertEqual(applied["Spoofing.VulkanExtensionSpoofing"], "false")

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
                               "OptiScaler.dll": b"p" * 2048,
                               "OptiScaler/libxess_fg.dll": self.INTEL_XEFG}.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        # Laid out like the fork's RC10 release: a zip (RC9 also offered a
        # tar.xz, RC10 does not) with the DLL and notices at the root plus files
        # the builder must ignore rather than trip over.
        fork = work / "fork.zip"
        with zipfile.ZipFile(fork, "w") as archive_zip:
            for name, data in {
                "amd_fidelityfx_upscaler_dx12.dll": self.FORK_BRIDGE,
                "notices/PROVENANCE.md": b"fork notices",
                "README.md": b"fork readme",
                "SHA256SUMS": b"",
                "linux/shared-cache.sh": b"#!/bin/sh\n",
            }.items():
                archive_zip.writestr(name, data)
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
    INTEL_XEFG = b"intel-xefg-runtime" * 512

    FREEFG_OPTI = b"freefg-optiscaler-fork" * 512
    # FreeFG's OptiScaler build (its fork) and the pinned 20261025 nightly now
    # define the same FSR keys; the fork's ini adds the Reprojection section.
    FORK_INI = STUB_INI + b"[Reprojection]\nFillMode=auto\n"
    FREEFG_PROXY = b"freefg-libxess-fg-proxy" * 512

    def freefg_zip(self, work, runtime_sha=None, layer_name="VK_LAYER_BC250_xefg_wave"):
        # Laid out like FreeFG 1.0.0's release zip, trimmed to what the builder
        # reads plus files it must leave out.
        path = work / "freefg-1.0.0.zip"
        pins = {"runtime": {"Files": {
            "OptiScaler/libxess_fg.dll": runtime_sha or sha256(self.INTEL_XEFG)}}}
        layer = {"file_format_version": "1.2.0", "layer": {
            "name": layer_name, "library_path": "./libxefg_wave.so"}}
        files = {
            "freefg-1.0.0/dependencies.json": json.dumps(pins).encode(),
            "freefg-1.0.0/opti/OptiScaler.dll": self.FREEFG_OPTI,
            "freefg-1.0.0/payload/libxess_fg.dll": self.FREEFG_PROXY,
            "freefg-1.0.0/payload/BC250-XeFG/layer/layer.json": json.dumps(layer).encode(),
            "freefg-1.0.0/payload/BC250-XeFG/layer/libxefg_wave.so": b"\x7fELF" + b"l" * 2048,
            "freefg-1.0.0/payload/BC250-XeFG/settings.ini": b"[BC250]\nResolutionMode=0\n",
            "freefg-1.0.0/payload/BC250-XeFG/shaders/waves.txt": b"waves",
            "freefg-1.0.0/payload/BC250-XeFG/shaders/08155f47bc92811b.dxil": b"d" * 2048,
            "freefg-1.0.0/payload/BC250-XeFG/shaders/winograd.required": b"1\n",
            "freefg-1.0.0/licenses/freefg.txt": b"mit",
            "freefg-1.0.0/licenses/OptiScaler-third-party/spdlog.txt": b"spdlog",
            "freefg-1.0.0/NOTICE.md": b"notice",
            "freefg-1.0.0/SOURCE.md": b"source",
            "freefg-1.0.0/install.py": b"print('not shipped')",
        }
        with zipfile.ZipFile(path, "w") as archive_zip:
            for name, data in files.items():
                archive_zip.writestr(name, data)
        return path

    SCALER_DLL = b"helixsr-scaler-optiscaler" * 64
    SCALER_INI = STUB_INI + b"[HelixSR]\nWaveSize=auto\nInt8=auto\n[DLSS]\nHelixSR=auto\n"
    SCALER_OPTIPATCHER = b"scaler-optipatcher" * 64
    SCALER_AMD_DLL = b"nightly-amd-ffx" * 64

    # HelixSR 3.0 after its setup: HLX DLSS with the network behind its
    # HXSRNET1 trailer, HLX FSR 4 with its shaders behind HLXFSR4D.
    NGX_DLL = b"hlx-dlss" * 1024 + b"HXSRNET1" + bytes(24)
    NGX_INI = b"; helixsr.ini\n[Upscaling]\nInt8 = auto\n"
    HLX_FSR4 = b"hlx-fsr4" * 1024 + b"HLXFSR4D" + bytes(16)

    def ngx_zip(self, work, hlx=None, dll=None):
        path = work / "HelixSR-3.0.0-network.zip"
        with zipfile.ZipFile(path, "w") as archive_zip:
            archive_zip.writestr("HelixSR-3.0.0/HelixSR/helixsr.dll", dll or self.NGX_DLL)
            archive_zip.writestr("HelixSR-3.0.0/HelixSR/helixsr.ini", self.NGX_INI)
            archive_zip.writestr("HelixSR-3.0.0/HLX-FSR4/amd_fidelityfx_upscaler_dx12.dll",
                                 hlx or self.HLX_FSR4)
            archive_zip.writestr("HelixSR-3.0.0/LICENSE", b"freeware")
            archive_zip.writestr("HelixSR-3.0.0/THIRD_PARTY_NOTICES.md", b"nvidia and amd property")
        return path

    def scaler_zip(self, work, ini=None):
        # The core of HelixSR Scaler's release: its OptiScaler.dll and ini plus
        # the licence texts.
        path = work / "scaler.zip"
        with zipfile.ZipFile(path, "w") as archive_zip:
            archive_zip.writestr("HelixSR-Scaler-2.0.0/OptiScaler.dll", self.SCALER_DLL)
            archive_zip.writestr("HelixSR-Scaler-2.0.0/OptiScaler.ini", ini or self.SCALER_INI)
            archive_zip.writestr("HelixSR-Scaler-2.0.0/Licenses/OptiScaler_LICENSE.txt", b"gpl")
            archive_zip.writestr("HelixSR-Scaler-2.0.0/OptiScaler/plugins/OptiPatcher.asi",
                                 self.SCALER_OPTIPATCHER)
            archive_zip.writestr(
                "HelixSR-Scaler-2.0.0/OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll",
                self.SCALER_AMD_DLL)
        return path

    def build_payload(self, default_name, scaler=False, scaler_ini=None,
                      freefg=None, ngx=None, hlx=None, ngx_dll=None):
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
                "--ffx-sdk-alt", "fsr411f", str(fork), "https://example/rc10",
                "--dlss", str(signed), "--licenses", str(licenses),
                "--preset", str(preset), "--manifest-rel", "upscaler-manifest.json",
                "--proton-rel", "proton", "--output", str(output),
                "--config", str(output / "cfg.json"),
            ]
            if default_name:
                command += ["--ffx-sdk-default", default_name]
            # The Scaler takes HelixSR 3.0's DLLs; without it they are opt-in.
            if ngx if ngx is not None else scaler:
                command += ["--helixsr-ngx", str(self.ngx_zip(work, hlx, ngx_dll)),
                            "https://example/helixsr3"]
            if scaler:
                command += ["--helixsr-scaler", str(self.scaler_zip(work, scaler_ini)),
                            "https://example/scaler"]
            if freefg is not None:
                fork_ini = work / "fork-OptiScaler.ini"
                fork_ini.write_bytes(self.FORK_INI)
                command += ["--freefg", str(self.freefg_zip(work, **freefg)),
                            "https://example/freefg", "--freefg-ini", str(fork_ini)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.last_result = result
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = json.loads((output / "cfg.json").read_text())
            manifest = json.loads((output / "upscaler-manifest.json").read_text())
            bridges = {}
            self.trees = {}
            for entry in manifest["optiscaler"]:
                artifact = output / "artifacts" / Path(entry["download_url"]).name
                with tarfile.open(artifact) as tar:
                    data = tar.extractfile(
                        "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").read()
                    self.trees[entry["version"]] = {
                        m.name: tar.extractfile(m).read()
                        for m in tar.getmembers() if m.isfile()
                    }
                bridges[entry["version"]] = data
                self.entries = {e["version"]: e for e in manifest["optiscaler"]}
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

    def test_an_unbuilt_hlx_dlss_fails_the_build(self):
        # The release DLL without the network runs as a plain upscale: refuse it
        # rather than ship it.
        with self.assertRaises(AssertionError):
            self.build_payload("fsr411f", ngx=True, ngx_dll=b"hlx-dlss without network" * 64)
        self.assertIn("has no network", self.last_result.stderr)

    def test_a_dll_the_setup_marked_as_built_passes_whatever_its_size(self):
        # The setup appends a 32-byte trailer starting HXSRNET1 to the DLL it
        # built, so a small one with that trailer is a built one.
        marked = b"x" * 4096 + b"HXSRNET1" + b"\0" * 24
        config, _ = self.build_payload("fsr411f", scaler=True, ngx_dll=marked)
        self.assertEqual(self.trees[config["optiscaler_aliases"]["helixsr"]]["HelixSR/helixsr.dll"],
                         marked)

    def test_freefg_is_an_opt_in_variant_laid_out_as_its_wrapper_expects(self):
        config, bridges = self.build_payload("helixsr", scaler=True,
                                             freefg={})
        version = config["optiscaler_aliases"]["freefg"]
        self.assertNotEqual(version, config["optiscaler_version"])
        tree = self.trees[version]
        # FreeFG's OptiScaler build is the proxy; the FSR4 bridge is RC11.
        self.assertEqual(tree["winmm.dll"], self.FREEFG_OPTI)
        self.assertEqual(bridges[version], self.FORK_BRIDGE)
        # OptiScaler loads libxess_fg.dll from its library folder: that is the
        # wrapper, with Intel's runtime beside it under the name it looks for.
        self.assertEqual(tree["OptiScaler/libxess_fg.dll"], self.FREEFG_PROXY)
        self.assertEqual(tree["OptiScaler/bc250_xefg_original.dll"], self.INTEL_XEFG)
        # Shaders and layer beside the wrapper; the settings file is read beside
        # the game's .exe, so it is not shipped.
        for name in ("layer/layer.json", "layer/libxefg_wave.so", "shaders/waves.txt",
                     "shaders/08155f47bc92811b.dxil", "shaders/winograd.required"):
            self.assertIn("OptiScaler/BC250-XeFG/" + name, tree)
        self.assertNotIn("OptiScaler/BC250-XeFG/settings.ini", tree)
        self.assertNotIn("install.py", tree)
        # Its own OptiScaler's ini, not the nightly's, and the renamed key.
        self.assertEqual(tree["OptiScaler.ini"], self.FORK_INI)
        variant = config["optiscaler_variant_preset"][version]
        # Both pinned builds define Fsr4GpuSupport now, and this repo does not
        # force the INT8 model on a BC-250 build (owner's ruling 2026-10-26).
        self.assertNotIn("FSR.Fsr4ForceModel", variant)
        self.assertEqual(variant["FSR.Fsr4GpuSupport"], "auto")
        # Every file pinned, the layer included.
        hashes = self.entries[version]["sha256_hash"]
        self.assertIn("OptiScaler/BC250-XeFG/layer/libxefg_wave.so", hashes)
        self.assertIn("OptiScaler/bc250_xefg_original.dll", hashes)
        # Its notices, the GPL source pointer among them, under its own folder.
        notices = {n.rsplit("/", 1)[1] for n in tree if n.startswith(f"Licenses/{version}/")}
        self.assertTrue({"freefg.txt", "OptiScaler-third-party-spdlog.txt",
                         "FreeFG-NOTICE.md", "FreeFG-SOURCE.md"} <= notices)
        self.assertIn("daniel-h-0/OptiScaler",
                      tree["Licenses/THIRD-PARTY-UPSCALER.txt"].decode())
        # Its frame generation settings, for it alone, and the layer for the
        # launcher.
        preset = dict(config["optiscaler_variant_preset"][version])
        preset.update(config["optiscaler_variant_seed"][version])  # frame-gen seeds there now
        self.assertEqual(preset["FrameGen.FGOutput"], "xefg")
        self.assertEqual(preset["FrameGen.Enabled"], "true")
        self.assertNotIn("FrameGen.FGOutput",
                         config["optiscaler_variant_preset"][config["optiscaler_version"]])
        layer = {
            "layer": "VK_LAYER_BC250_xefg_wave",
            "layer_dir": "OptiScaler/BC250-XeFG/layer",
            "wave_config": "OptiScaler/BC250-XeFG/shaders/waves.txt",
            "dll_path": "C:\\windows\\system32\\umu\\OptiScaler"}
        hlx = config["optiscaler_aliases"]["freefg-hlxfsr4"]
        self.assertEqual(config["freefg"], {version: layer, hlx: layer})
        # The default is untouched.
        default = self.trees[config["optiscaler_version"]]
        self.assertNotIn("OptiScaler/bc250_xefg_original.dll", default)
        self.assertEqual(default["OptiScaler/libxess_fg.dll"], self.INTEL_XEFG)

    def test_freefg_hlxfsr4_can_be_the_default(self):
        # What the three packages pass since 2026-10-29.
        config, _ = self.build_payload("freefg-hlxfsr4", scaler=True,
                                       freefg={})
        aliases = config["optiscaler_aliases"]
        default = config["optiscaler_version"]
        self.assertEqual(aliases["freefg-hlxfsr4"], default)
        self.assertIn("OptiScaler/libxess_fg.dll", self.trees[default])
        # The others stay reachable by name, each its own version.
        for name in ("freefg", "helixsr", "fsr412f" if "fsr412f" in aliases else "fsr411f"):
            self.assertNotEqual(aliases[name], default, name)
        self.assertEqual(config["optiscaler_variant_seed"][default]["FrameGen.Enabled"], "true")
        self.assertIn(default, config["freefg"])
        # Spoofing is the shared preset's (auto, OptiScaler decides) and the
        # menu's; no variant forces it.
        for layer in (config["optiscaler_variant_seed"], config["optiscaler_variant_preset"]):
            for values in layer.values():
                self.assertNotIn("Spoofing.Dxgi", values)

    def test_freefg_without_its_ini_fails_the_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, fork, fakenvapi, signed, provider, licenses, preset = self.payload_inputs(work)
            (work / "out").mkdir()
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/build-fsr4-payload.py"),
                "--optiscaler", str(archive), "--optiscaler-version", "v",
                "--optipatcher", str(signed), "--fakenvapi", str(fakenvapi),
                "--provider", str(provider), "--ffx-sdk", str(signed),
                "--ffx-sdk-alt", "fsr411f", str(fork), "https://example/rc11",
                "--freefg", str(self.freefg_zip(work)), "https://example/freefg",
                "--dlss", str(signed), "--licenses", str(licenses), "--preset", str(preset),
                "--manifest-rel", "m.json", "--proton-rel", "proton",
                "--output", str(work / "out"), "--config", str(work / "out/c.json")],
                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--freefg-ini", result.stderr)

    def test_without_helixsr_3_there_is_no_freefg_hlxfsr4(self):
        config, _ = self.build_payload("fsr411f", freefg={})
        self.assertIn("freefg", config["optiscaler_aliases"])
        self.assertNotIn("freefg-hlxfsr4", config["optiscaler_aliases"])
        # Nor its old name.
        self.assertNotIn("freefg-helixsr", config["optiscaler_aliases"])

    def test_freefg_refuses_a_nightly_whose_intel_runtime_it_would_reject(self):
        with self.assertRaises(AssertionError):
            self.build_payload("fsr411f", freefg={"runtime_sha": "0" * 64})
        self.assertIn("FreeFG would refuse it", self.last_result.stderr)

    def test_freefg_refuses_an_unexpected_layer(self):
        with self.assertRaises(AssertionError):
            self.build_payload("fsr411f", freefg={"layer_name": "VK_LAYER_other"})

    def test_without_freefg_the_config_names_no_layer(self):
        config, _ = self.build_payload("fsr411f")
        self.assertEqual(config["freefg"], {})
        self.assertNotIn("freefg", config["optiscaler_aliases"])

    def test_helixsr_scaler_can_be_the_default_with_its_own_files(self):
        config, bridges = self.build_payload("helixsr", scaler=True)
        default = config["optiscaler_version"]
        aliases = config["optiscaler_aliases"]
        tree = self.trees[default]
        self.assertEqual(aliases["helixsr"], default)
        # Its own OptiScaler as the proxy and its own ini, not the nightly's.
        self.assertEqual(tree["winmm.dll"], self.SCALER_DLL)
        self.assertEqual(tree["OptiScaler.ini"], self.SCALER_INI)
        # HLX DLSS where the Scaler looks for it, beside its own DLL; HLX FSR 4 as
        # OptiScaler's FidelityFX upscaler, the nightly's AMD DLL beside it, and
        # the Scaler's own OptiPatcher over the pinned one.
        self.assertEqual(tree["HelixSR/helixsr.dll"], self.NGX_DLL)
        self.assertEqual(tree["HelixSR/helixsr.ini"], self.NGX_INI)
        self.assertEqual(bridges[default], self.HLX_FSR4)
        self.assertEqual(tree["OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll"], self.SCALER_AMD_DLL)
        self.assertEqual(tree["OptiScaler/plugins/OptiPatcher.asi"], self.SCALER_OPTIPATCHER)
        # Nothing of HelixSR 2.0's layout.
        self.assertFalse(any(n.startswith("HelixSR-fsrfg/") for n in tree))
        hashes = self.entries[default]["sha256_hash"]
        self.assertIn("HelixSR/helixsr.dll", hashes)
        self.assertNotIn("OptiScaler.ini", hashes)
        # HLX FSR 4 (ffx) with FSR frame generation is where it starts, but only
        # seeded: the Scaler's menu offers HLX DLSS too, and a switch there has
        # to stick. [DLSS] HelixSR is wiring, enforced, so HLX DLSS stays listed.
        self.assertEqual(config["optiscaler_variant_preset"][default],
                         {"DLSS.HelixSR": "true", "HelixSR.Int8": "off"})
        self.assertEqual(config["optiscaler_variant_seed"][default],
                         {"Upscalers.Dx12Upscaler": "ffx", "FrameGen.Enabled": "true",
                          "FrameGen.FGInput": "upscaler", "FrameGen.FGOutput": "fsrfg"})
        # The stock nightly and every bridge stay reachable by name, and none
        # of them carries the Scaler.
        for name in ("optiscaler", "fsr411f", "signed"):
            other = self.trees[aliases[name]]
            self.assertNotEqual(aliases[name], default)
            self.assertEqual(other["winmm.dll"], b"p" * 2048)
            self.assertNotIn("HelixSR/helixsr.dll", other)
        self.assertEqual(aliases["optiscaler"], aliases["fsr411f"])
        self.assertEqual(bridges[aliases["optiscaler"]], self.FORK_BRIDGE)
        self.assertEqual(bridges[aliases["signed"]], self.SIGNED_BRIDGE)
        # Licences of everything it ships, GPL text included.
        notices = {n for n in tree if n.startswith(f"Licenses/{default}/")}
        self.assertIn(f"Licenses/{default}/OptiScaler_LICENSE.txt", notices)
        self.assertIn(f"Licenses/{default}/HelixSR-LICENSE", notices)
        self.assertIn("GPL-3.0", tree["Licenses/THIRD-PARTY-UPSCALER.txt"].decode())

    def test_the_scaler_gets_a_version_of_its_own_when_not_the_default(self):
        # Prefixes that ran Scaler 1.1.0 keep that build's ini until the pinned
        # version string changes; the bare short name would not change it.
        config, _ = self.build_payload("fsr411f", scaler=True)
        self.assertEqual(config["optiscaler_aliases"]["helixsr"], "test-opti-helixsr-scaler2")

    def test_the_scaler_needs_helixsr_3(self):
        with self.assertRaises(AssertionError):
            self.build_payload("fsr411f", scaler=True, ngx=False)
        self.assertIn("--helixsr-ngx", self.last_result.stderr)

    def test_an_unbuilt_hlx_fsr4_fails_the_build(self):
        with self.assertRaises(AssertionError):
            self.build_payload("fsr411f", ngx=True, hlx=b"hlx-fsr4 without shaders" * 64)
        self.assertIn("HLX FSR 4 is not built", self.last_result.stderr)

    def test_freefg_hlxfsr4_puts_hlx_fsr4_in_the_bridge_place(self):
        config, bridges = self.build_payload("freefg-hlxfsr4", scaler=True,
                                             freefg={})
        aliases = config["optiscaler_aliases"]
        version = aliases["freefg-hlxfsr4"]
        tree = self.trees[version]
        plain = self.trees[aliases["freefg"]]
        self.assertEqual(bridges[version], self.HLX_FSR4)
        # FreeFG's own files are those of the plain variant; no HelixSR folder.
        for name in ("winmm.dll", "OptiScaler.ini", "OptiScaler/libxess_fg.dll",
                     "OptiScaler/bc250_xefg_original.dll"):
            self.assertEqual(tree[name], plain[name], name)
        self.assertFalse(any(n.startswith("HelixSR") for n in tree))
        self.assertIn(version, config["freefg"])
        self.assertEqual(config["optiscaler_variant_seed"][version]["FrameGen.FGOutput"], "xefg")
        notices = {n.rsplit("/", 1)[1] for n in tree if n.startswith(f"Licenses/{version}/")}
        self.assertTrue({"freefg.txt", "HelixSR-LICENSE"} <= notices)

    def test_the_helixsr_2_names_select_their_successors(self):
        # freefg-helixsr and helixsr-ffx went with HelixSR 2.0 (2026-10-29); a
        # launch option or saved choice that names one gets FreeFG + HLX FSR 4 or
        # HelixSR Scaler, and no variant ships HelixSR 2.0's files any more.
        config, _ = self.build_payload("freefg-hlxfsr4", scaler=True, freefg={})
        aliases = config["optiscaler_aliases"]
        self.assertEqual(aliases["freefg-helixsr"], config["optiscaler_version"])
        self.assertEqual(aliases["helixsr-ffx"], aliases["helixsr"])
        for version, tree in self.trees.items():
            self.assertNotIn("OptiScaler/amd_fidelityfx_dx12.dll", tree, version)
            self.assertNotIn("OptiScaler/helixsr.ini", tree, version)
        for values in config["optiscaler_variant_preset"].values():
            self.assertNotIn("Libraries.FfxDx12Path", values)
            self.assertNotIn("FSR.UpscalerIndex", values)

    def test_the_scaler_ini_has_to_take_the_variant_preset_it_ships_with(self):
        with self.assertRaises(AssertionError):
            # An ini without the [DLSS] section cannot take the variant preset.
            self.build_payload("helixsr", scaler=True,
                               scaler_ini=STUB_INI + b"[HelixSR]\nInt8=auto\n")
        self.assertIn("Unknown OptiScaler preset option", self.last_result.stderr)

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

    def test_a_preset_key_the_shipped_ini_lacks_fails_the_build(self):
        # Nothing is exempt any more: every preset key is validated against the
        # ini it ships with, because protonfixes refuses a launch on a key the
        # build does not define, and a shared key the variant ini lacks has to
        # come out of what the launcher is given (see the null in its preset).
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            ini = work / "OptiScaler.ini"
            ini.write_text("[Spoofing]\nDxgi=auto\n")
            preset = work / "preset.json"
            preset.write_text(json.dumps({"preset": {"Spoofing.Dxgi": "false"}}))
            self.assertEqual(
                builder.validate_preset(preset, ini), {"Spoofing.Dxgi": "false"}
            )
            preset.write_text(json.dumps({
                "preset": {"Spoofing.Dxgi": "false", "Spoofing.Vulkan": "false"},
            }))
            with self.assertRaisesRegex(RuntimeError, "Unknown OptiScaler preset option"):
                builder.validate_preset(preset, ini)

    def test_a_newer_bridge_from_the_fork_becomes_its_own_variant(self):
        """PROTON_USE_OPTISCALER=fsr412f: the RC12 zip added as one more
        --ffx-sdk-alt. It has the same layout as RC11's, so the builder has to
        give it its own version, its own DLL, its own origin on record and its
        own notices, without touching the preset the other variants share."""
        with tempfile.TemporaryDirectory(prefix="payload-rc12-") as temporary:
            work = Path(temporary)
            archive, fork, fakenvapi, signed, provider, licenses, preset = self.payload_inputs(work)
            rc12 = work / "rc12.zip"
            with zipfile.ZipFile(rc12, "w") as zf:
                zf.writestr("amd_fidelityfx_upscaler_dx12.dll", b"bc250-fork-rc12" * 512)
                zf.writestr("notices/PROVENANCE.md", b"rc12 notices")
                zf.writestr("README.md", b"rc12 readme")
                zf.writestr("SHA256SUMS", b"")
                zf.writestr("linux/shared-cache.sh", b"#!/bin/sh\n")
            out = work / "out"
            out.mkdir()
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/build-fsr4-payload.py"),
                "--optiscaler", str(archive), "--optiscaler-version", "test-opti",
                "--optipatcher", str(signed), "--fakenvapi", str(fakenvapi),
                "--provider", str(provider), "--ffx-sdk", str(signed),
                "--ffx-sdk-alt", "fsr411f", str(fork), "https://example/rc11",
                "--ffx-sdk-alt", "fsr412f", str(rc12), "https://example/rc12",
                "--dlss", str(signed), "--licenses", str(licenses), "--preset", str(preset),
                "--manifest-rel", "upscaler-manifest.json", "--proton-rel", "proton",
                "--output", str(out), "--config", str(out / "cfg.json")],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = json.loads((out / "cfg.json").read_text())
            manifest = json.loads((out / "upscaler-manifest.json").read_text())
            entries = {e["version"]: e for e in manifest["optiscaler"]}
            aliases = config["optiscaler_aliases"]
            self.assertIn("fsr412f", aliases)
            self.assertNotEqual(aliases["fsr412f"], aliases["fsr411f"])
            trees = {}
            for version, entry in entries.items():
                artifact = out / "artifacts" / Path(entry["download_url"]).name
                with tarfile.open(artifact) as tar:
                    trees[version] = {
                        m.name: tar.extractfile(m).read()
                        for m in tar.getmembers() if m.isfile()
                    }
            new = trees[aliases["fsr412f"]]
            old = trees[aliases["fsr411f"]]
            self.assertEqual(new["OptiScaler/amd_fidelityfx_upscaler_dx12.dll"],
                             b"bc250-fork-rc12" * 512)
            self.assertEqual(old["OptiScaler/amd_fidelityfx_upscaler_dx12.dll"],
                             self.FORK_BRIDGE)
            # Its notices ship beside it, as that release asks, and its origin is
            # on record with the other unsigned builds.
            self.assertEqual(new[f"Licenses/{aliases['fsr412f']}/PROVENANCE.md"],
                             b"rc12 notices")
            self.assertTrue(any(b"https://example/rc12" in data
                                for name, data in new.items()
                                if name.startswith("Licenses/")))
            # No ini of its own anywhere in the zip, so the shared preset applies
            # to it unchanged and it adds no per-variant keys for anybody else.
            document = json.loads(preset.read_text())
            self.assertEqual(config["preset"],
                             document["preset"] if "preset" in document else document)
            self.assertEqual(config["optiscaler_variant_preset"].get(aliases["fsr412f"], {}), {})


class FirstLaunchMenuStateTests(unittest.TestCase):
    """The menu's state logic. The window itself (GTK4 + SDL3 through the HIDAPI,
    Steam's filter lifted for its own process) was verified on the board; these
    pin what the launcher acts on."""

    def load(self):
        import importlib.util, pathlib
        path = pathlib.Path(__file__).resolve().parents[1] / "packages/bc250-fsr4-common/bc250-fsr4-menu.py"
        spec = importlib.util.spec_from_file_location("bc250_menu", path)
        menu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(menu)
        return menu

    def prefix(self, ini_lines):
        import pathlib, tempfile
        root = pathlib.Path(tempfile.mkdtemp())
        ini = root / "pfx/drive_c/windows/system32/umu/OptiScaler.ini"
        ini.parent.mkdir(parents=True)
        ini.write_text("\n".join(ini_lines) + "\n")
        return str(root), ini

    def test_shows_on_every_launch_until_saved(self):
        menu = self.load()
        root, _ = self.prefix(["[FrameGen]", "enabled = auto"])
        self.assertEqual(menu.decide(root, {})[0], True)
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "helixsr", "remember": 1}')
        self.assertEqual(menu.decide(root, {})[0], False)

    def test_a_launch_option_by_name_skips_the_menu(self):
        menu = self.load()
        root, _ = self.prefix(["[FrameGen]", "enabled = auto"])
        self.assertEqual(menu.decide(root, {"PROTON_USE_OPTISCALER": "fsr412f"})[0], False)

    def test_the_menu_shows_again_for_one_launch_and_clears_the_save(self):
        menu = self.load()
        root, _ = self.prefix(["[FrameGen]", "enabled = auto"])
        open(menu.store_path(root), "w").write('{"variant": "helixsr", "remember": 1}')
        self.assertEqual(menu.decide(root, {"PROTON_OPTISCALER_MENU": "1"})[0], True)

    def test_the_frame_gen_row_reads_the_prefix_real_state(self):
        menu = self.load()
        # The Scaler 2.0: [FrameGen] Enabled, like the stock nightly (HelixSR 3.0
        # has no frame generation of its own). The old routing pair of Scaler
        # 1.1.0 no longer counts.
        root, _ = self.prefix(["[FrameGen]", "enabled = true"])
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "helixsr", "remember": 1}')
        # decide() reports (show, current, fg_on, saved) for the variant the store
        # says the prefix is on.
        self.assertEqual(menu.decide(root, {"PROTON_OPTISCALER_MENU": "1",
                                            "BC250_MENU_INSTALLED": "helixsr"})[2], True)
        # Another variant (or an older package's) on disk: the launch starts the
        # pick fresh, so the row shows the fresh seed, here the Scaler's on;
        # RC12's seed is off.
        self.assertEqual(menu.decide(root, {"PROTON_OPTISCALER_MENU": "1"})[2], True)
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "fsr412f", "remember": 1}')
        self.assertEqual(menu.decide(root, {"PROTON_OPTISCALER_MENU": "1"})[2], False)
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "helixsr", "remember": 1}')
        self.assertEqual(menu.fg_state("helixsr", menu.read_ini_sections(root + "/pfx/drive_c/windows/system32/umu/OptiScaler.ini")), True)
        old, _ = self.prefix(["[FrameGen]", "enabled = false", "fginput = nvngxfg",
                              "fgnvngxreplacement = HelixSR"])
        self.assertEqual(menu.fg_state("helixsr", menu.read_ini_sections(old + "/pfx/drive_c/windows/system32/umu/OptiScaler.ini")), False)
        self.assertEqual(menu.fg_state("freefg-hlxfsr4", menu.read_ini_sections(old + "/pfx/drive_c/windows/system32/umu/OptiScaler.ini")), False)
        root2, _ = self.prefix(["[FrameGen]", "enabled = true", "fginput = upscaler",
                                "fgoutput = xefg"])
        self.assertEqual(menu.fg_state("freefg-hlxfsr4", menu.read_ini_sections(root2 + "/pfx/drive_c/windows/system32/umu/OptiScaler.ini")), True)
        self.assertEqual(menu.fg_state("fsr412f", menu.read_ini_sections(root2 + "/pfx/drive_c/windows/system32/umu/OptiScaler.ini")), True)

    def test_only_a_change_is_written(self):
        menu = self.load()
        wired = menu.read_ini_sections(self.prefix(["[FrameGen]", "enabled = true",
                                                    "fginput = upscaler", "fgoutput = fsrfg"])[1])
        self.assertEqual(menu.change("helixsr", True, True, menu.DEFINABLE["helixsr"], wired), {})
        self.assertEqual(menu.change("freefg", True, True, menu.DEFINABLE["freefg"]), {})
        # Turning it off writes the one switch, and nothing else.
        self.assertEqual(menu.change("helixsr", True, False, menu.DEFINABLE["helixsr"]),
                         {"FrameGen.Enabled": "false"})
        self.assertEqual(menu.change("freefg-hlxfsr4", False, True, menu.DEFINABLE["freefg-hlxfsr4"]),
                         {"FrameGen.Enabled": "true"})
        # A key this build's ini does not define is not handed over: protonfixes
        # refuses the launch on it.
        self.assertEqual(menu.change("fsr412f", False, True, set()), {})
        self.assertEqual(menu.change("freefg", False, True, menu.DEFINABLE["freefg"]),
                         {"FrameGen.Enabled": "true"})
    def test_frame_generation_on_brings_its_wiring(self):
        # Enabled=true alone is nofg in the Scaler and the stock nightly: turning it
        # on also picks OptiFG into FSR FG, wherever the ini has not picked yet.
        menu = self.load()
        wiring = {"FrameGen.FGInput": "upscaler", "FrameGen.FGOutput": "fsrfg"}
        for variant in ("helixsr", "fsr412f"):
            self.assertEqual(menu.change(variant, False, True, menu.DEFINABLE[variant]),
                             {"FrameGen.Enabled": "true", **wiring})
            # Off writes the switch only; the wiring is harmless with it off.
            self.assertEqual(menu.change(variant, True, False, menu.DEFINABLE[variant]),
                             {"FrameGen.Enabled": "false"})
        # A prefix that got Enabled=true without the wiring (the first Scaler 2.0
        # package) is repaired by pressing Start with the box as it is.
        broken = menu.read_ini_sections(self.prefix(["[FrameGen]", "enabled = true",
                                                     "fginput = auto", "fgoutput = nofg"])[1])
        self.assertEqual(menu.fg_state("helixsr", broken), True)
        self.assertEqual(menu.change("helixsr", True, True, menu.DEFINABLE["helixsr"], broken), wiring)
        # An output the player picked in the overlay stays.
        xefg = menu.read_ini_sections(self.prefix(["[FrameGen]", "enabled = false",
                                                   "fginput = auto", "fgoutput = xefg"])[1])
        self.assertEqual(menu.change("helixsr", False, True, menu.DEFINABLE["helixsr"], xefg),
                         {"FrameGen.Enabled": "true", "FrameGen.FGInput": "upscaler"})
        # FreeFG's wiring is its variant preset, enforced every launch.
        self.assertEqual(menu.change("freefg-hlxfsr4", False, True, menu.DEFINABLE["freefg-hlxfsr4"]),
                         {"FrameGen.Enabled": "true"})
        # answer() reads the prefix's ini only for the variant it belongs to.
        pick = {"preset": "helixsr", "disable_framegen": 0}
        self.assertEqual(menu.answer(pick, "helixsr", "helixsr", {"helixsr": True}, {}, broken)["changed"],
                         "FrameGen.FGInput=upscaler;FrameGen.FGOutput=fsrfg")
        wired = menu.read_ini_sections(self.prefix(["[FrameGen]", "fginput = upscaler",
                                                    "fgoutput = fsrfg"])[1])
        self.assertIn("FrameGen.FGOutput=fsrfg",
                      menu.answer(pick, "freefg", "freefg", {"helixsr": False}, {}, wired)["changed"])

    def test_a_fresh_prefix_shows_what_the_variant_seeds(self):
        # No answer in the ini yet: FreeFG and the Scaler seed frame generation on,
        # FSR4 RC12 off, so a player who just presses Start changes nothing.
        menu = self.load()
        for lines in ([], ["[FrameGen]", "enabled = auto", "fginput = auto"]):
            sections = menu.read_ini_sections(self.prefix(lines)[1]) if lines else {}
            self.assertEqual(menu.fg_state("freefg-hlxfsr4", sections), True)
            self.assertEqual(menu.fg_state("freefg", sections), True)
            self.assertEqual(menu.fg_state("helixsr", sections), True)
            self.assertEqual(menu.fg_state("fsr412f", sections), False)
        # The player's own answer from the overlay wins over the seed.
        sections = menu.read_ini_sections(self.prefix(["[FrameGen]", "enabled = false"])[1])
        self.assertEqual(menu.fg_state("freefg-hlxfsr4", sections), False)

    def test_the_prefix_variant_is_preselected_unless_a_choice_is_saved(self):
        menu = self.load()
        root, _ = self.prefix(["[FrameGen]", "enabled = auto"])
        env = {"BC250_MENU_INSTALLED": "helixsr", "BC250_MENU_DEFAULT": "freefg-hlxfsr4"}
        self.assertEqual(menu.decide(root, {"BC250_MENU_DEFAULT": "freefg-hlxfsr4"})[1], "freefg-hlxfsr4")
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "fsr412f", "remember": 0}')
        # What is on disk is what runs; the last pick only fills in when nothing is.
        self.assertEqual(menu.decide(root, env)[1], "helixsr")
        self.assertEqual(menu.decide(root, {})[1], "fsr412f")
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "fsr412f", "remember": 1}')
        self.assertEqual(menu.decide(root, env)[:2], (False, "fsr412f"))
        # A choice saved by an older package names a variant that is gone now:
        # it selects what took that variant's place, saved as before.
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "freefg-helixsr", "remember": 1}')
        self.assertEqual(menu.decide(root, env)[:2], (False, "freefg-hlxfsr4"))

    def test_the_installed_variant_comes_from_protonfixes_record(self):
        import tempfile
        data = Path(tempfile.mkdtemp())
        config = {"manifest": "m.json"}
        (data / "m.json").write_text(json.dumps({"optiscaler": [
            {"version": "v1", "md5_hash": {"a": ""}}, {"version": "v1-freefg", "md5_hash": {"a": ""}}]}))
        env = {"STEAM_COMPAT_DATA_PATH": str(data)}
        with mock.patch.object(wrapper, "TOOL", data):
            self.assertIsNone(wrapper.installed_variant(config, env))
            (data / "upscaler_files").write_text(json.dumps({"opti_files": {
                "x": {"version": "v1-freefg"}, "y": {"version": "v1-freefg"}, "z": {"version": "v1"}}}))
            self.assertEqual(wrapper.installed_variant(config, env), "v1-freefg")
            # An older package's version is nobody this package can name.
            (data / "upscaler_files").write_text(json.dumps({"opti_files": {"x": {"version": "v0"}}}))
            self.assertIsNone(wrapper.installed_variant(config, env))

    def test_spoofing_is_written_only_when_the_player_changes_it(self):
        menu = self.load()
        for lines, shown in (([], "auto"), (["[Spoofing]", "dxgi = true"], "true"),
                             (["[Spoofing]", "dxgi = False"], "false"), (["[Spoofing]", "dxgi = 1"], "auto")):
            sections = menu.read_ini_sections(self.prefix(lines)[1]) if lines else {}
            self.assertEqual(menu.spoof_state(sections), shown)
        fg = dict(menu.FRESH_ON)
        pick = {"preset": "freefg-hlxfsr4", "disable_framegen": 0, "spoof": "true"}
        # The prefix already says true: Start changes nothing.
        same = menu.answer(pick, "freefg-hlxfsr4", "freefg-hlxfsr4", fg, {"freefg-hlxfsr4": "true"})
        self.assertEqual(same["changed"], "")
        # Auto in the prefix, On in the menu: forced on.
        on = menu.answer(pick, "freefg-hlxfsr4", "freefg-hlxfsr4", fg, {"freefg-hlxfsr4": "auto"})
        self.assertEqual(on["changed"], "Spoofing.Dxgi=true")
        # A switch starts from auto, so Off is handed over; No upscaling hands nothing.
        off = menu.answer(dict(pick, preset="fsr412f", spoof="false", disable_framegen=1),
                          "freefg-hlxfsr4", "freefg-hlxfsr4", fg, {"freefg-hlxfsr4": "true"})
        self.assertEqual((off["switched"], off["changed"]), (1, "Spoofing.Dxgi=false"))
        none = menu.answer(dict(pick, preset="off", spoof="false"), "freefg-hlxfsr4",
                           "freefg-hlxfsr4", fg, {})
        self.assertEqual(none["changed"], "")

    def test_no_upscaling_is_a_pick_that_keeps_the_prefix(self):
        menu = self.load()
        root, _ = self.prefix(["[FrameGen]", "enabled = false"])
        env = {"BC250_MENU_INSTALLED": "freefg-hlxfsr4", "BC250_MENU_DEFAULT": "freefg-hlxfsr4"}
        with open(menu.store_path(root), "w") as stream:
            stream.write('{"variant": "off", "remember": 0}')
        # The files still say FreeFG, but the last pick was No upscaling.
        self.assertEqual(menu.decide(root, env)[:2], (True, "off"))
        states = dict(menu.FRESH_ON, **{"freefg-hlxfsr4": False})
        # Off: nothing switched, nothing written into the ini.
        self.assertEqual(menu.answer({"preset": "off", "disable_framegen": 1}, "freefg-hlxfsr4",
                                     "freefg-hlxfsr4", states),
                         {"preset": "off", "disable_framegen": 1, "remember": 0, "switched": 0, "changed": "",
                          "apply_preset": ""})
        # Back to the variant the files belong to: not a switch, the overlay's FG off stays.
        back = menu.answer({"preset": "freefg-hlxfsr4", "disable_framegen": 1}, "off", "freefg-hlxfsr4", states)
        self.assertEqual((back["switched"], back["changed"]), (0, ""))
        # Another variant is a switch and starts from its seed.
        other = menu.answer({"preset": "freefg", "disable_framegen": 0}, "off", "freefg-hlxfsr4", states)
        self.assertEqual((other["switched"], other["changed"]), (1, ""))

    def test_no_upscaling_launches_with_the_documented_opt_out(self):
        import tempfile
        tool = Path(tempfile.mkdtemp())
        (tool / "bc250-fsr4-config.json").write_text('{"proton": "proton"}')
        seen = {}
        with mock.patch.object(wrapper, "menu_choice", return_value=("off", {}, False, None)), \
                mock.patch.object(wrapper, "game_launch", return_value=True), \
                mock.patch.object(wrapper, "start_fresh_on_switch"), \
                mock.patch.object(wrapper, "clean_other_variants"), \
                mock.patch.object(wrapper, "environment",
                                  lambda config, inherited, **_: seen.update(inherited) or {}), \
                mock.patch.object(wrapper.os, "execve", lambda *_: None), \
                mock.patch.dict(wrapper.os.environ, {}, clear=True), \
                mock.patch.object(wrapper, "TOOL", tool):
            wrapper.main()
        self.assertEqual(seen["PROTON_FSR4_UPGRADE"], "0")
        self.assertEqual(seen["PROTON_USE_OPTISCALER"], "0")

    def test_an_anticheat_game_gets_no_menu_unless_the_guard_is_off(self):
        import tempfile
        game = Path(tempfile.mkdtemp())
        (game / "EasyAntiCheat").mkdir()
        prefix = tempfile.mkdtemp()
        tool = Path(tempfile.mkdtemp())
        # A menu that would answer if it were asked.
        (tool / "bc250-fsr4-menu.py").write_text('print("show=0")\nprint("current=freefg")\n')
        config = {"optiscaler_version": "v", "manifest": "m.json"}
        env = {"STEAM_COMPAT_DATA_PATH": prefix, "STEAM_COMPAT_INSTALL_PATH": str(game)}
        with mock.patch.object(wrapper, "TOOL", tool):
            self.assertEqual(wrapper.menu_choice(config, env), (None, {}, False, None))
            env["BC250_FSR4_IGNORE_ANTICHEAT"] = "1"
            self.assertEqual(wrapper.menu_choice(config, env), ("freefg", {}, False, None))

    def test_the_launcher_asks_no_menu_when_the_launch_already_says(self):
        import tempfile
        prefix = tempfile.mkdtemp()
        for extra in ({"PROTON_USE_OPTISCALER": "freefg"}, {"PROTON_FSR4_UPGRADE": "0"}):
            self.assertEqual(
                wrapper.menu_choice({}, dict({"STEAM_COMPAT_DATA_PATH": prefix}, **extra)),
                (None, {}, False, None))


if __name__ == "__main__":
    unittest.main()
