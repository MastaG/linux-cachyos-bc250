"""The per-game preset database: its nightly builder and the launcher's use of it."""

import gzip
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "packages/bc250-fsr4-common"


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load_script("wrapper_presets", COMMON / "bc250-fsr4-launch.py")
builder = load_script("game_presets", ROOT / "scripts/build-game-presets.py")
menu = load_script("menu_presets", COMMON / "bc250-fsr4-menu.py")

REFERENCE_INI = """[Spoofing]
Dxgi=auto
[Hotfix]
ColorResourceBarrier=auto
RestoreComputeSignature=auto
[OptiFG]
HUDFix=auto
[FrameGen]
Enabled=auto
FGInput=auto
[DLSS]
Enabled=auto
[Libraries]
XeSSPath=auto
"""

# A config shaped like the one build-fsr4-payload.py writes, for two variants.
CONFIG = {
    "proxy": "winmm.dll",
    "optiscaler_version": "v-freefg",
    "optiscaler_aliases": {"freefg-hlxfsr4": "v-freefg", "fsr412f": "v-rc12"},
    "optiscaler_variant_preset": {"v-freefg": {"XeFG.ForceBorderless": "true"}},
    "optiscaler_variant_seed": {
        "v-freefg": {"FrameGen.FGInput": "upscaler", "FrameGen.FGOutput": "xefg"},
        "v-rc12": {},
    },
    "optiscaler_ini_keys": {
        "v-freefg": ["Spoofing.Dxgi", "Hotfix.ColorResourceBarrier", "Hotfix.RestoreComputeSignature",
                     "FrameGen.FGInput", "FrameGen.Enabled", "XeFG.HighResMV", "XeFG.ForceBorderless",
                     "Libraries.XeSSPath", "Log.LogToFile"],
        "v-rc12": ["Spoofing.Dxgi", "Hotfix.ColorResourceBarrier", "FrameGen.FGInput"],
    },
}


def game(**extra):
    base = {"title": "Test Game", "match": {"title": ["test game"], "steam": ["123"], "exe": ["test.exe"]}}
    base.update(extra)
    return base


class BuilderTests(unittest.TestCase):
    def keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "OptiScaler.ini"
            path.write_text(REFERENCE_INI)
            return builder.reference_keys([path])

    def test_a_bare_wiki_key_gets_its_section_unless_two_sections_have_it(self):
        keys = self.keys()
        self.assertEqual(keys["dxgi"], "Spoofing.Dxgi")
        self.assertIsNone(keys["enabled"])  # FrameGen and DLSS both define it

    def test_spans_carry_the_condition_their_sentence_states(self):
        keys = self.keys()
        found = builder.spans(
            "* `ColorResourceBarrier=4`\n"
            "* `Dxgi=false` for AMD/Intel\n"
            "* `RestoreComputeSignature=true` for *DLSS inputs* to work\n"
            "* +++<s>`HUDFix=true`</s>+++\n"
            "* `Enabled=true` (which one?)\n"
            "* `HUDFix = true` only if the HUD flickers\n", keys)
        self.assertEqual(found, [
            ("Hotfix.ColorResourceBarrier", "4", {}, False),
            ("Spoofing.Dxgi", "false", {"gpu": "amd/intel"}, False),
            ("Hotfix.RestoreComputeSignature", "true", {"upscaler_input": "dlss"}, False),
            ("OptiFG.HUDFix", "true", {"condition": "* `HUDFix = true` only if the HUD flickers"}, False),
        ])

    def test_what_optiscaler_applies_itself_is_marked(self):
        found = builder.spans("* *Automatically applied options since 0.9.3*:\n** `Dxgi=false`\n", self.keys())
        self.assertEqual(found, [("Spoofing.Dxgi", "false", {}, True)])

    def test_a_page_table_reads_by_label(self):
        rows = builder.page_rows('[cols="1,1"]\n|===\n|**Filename**\n|`dxgi.dll`, `winmm.dll`\n\n'
                                 '|**Settings**\na|\n* `Dxgi=false`\n\n|**Notes**\n|-\n|===\n')
        self.assertEqual(rows["Filename"], "`dxgi.dll`, `winmm.dll`")
        self.assertIn("`Dxgi=false`", rows["Settings"])
        self.assertEqual(builder.proxies(rows["Filename"]), ["dxgi.dll", "winmm.dll"])

    def test_titles_match_however_they_are_punctuated(self):
        self.assertEqual(builder.norm("Assassin’s Creed® Mirage"), builder.norm("Assassins Creed Mirage"))
        self.assertEqual(builder.norm("Atelier & Co."), "atelier and co")
        self.assertEqual(builder.norm("Grand Theft Auto V"), wrapper.norm_title("Grand Theft Auto V"))
        self.assertEqual(builder.norm("God of War Ragnarök"), "god of war ragnarok")
        self.assertEqual(wrapper.norm_title("God of War Ragnarök"), "god of war ragnarok")

    def test_wiki_rows_bring_their_store_ids(self):
        games = {}
        builder.from_freefg(games, {"wiki": [{"title": "God of War Ragnarok", "match": {
            "title": ["god of war ragnarok"], "steam": ["2322010"], "exe": ["GoWR.exe"]},
            "ini": [{"key": "Spoofing.Dxgi", "value": "false"}]}]}, {"dxgi": "Spoofing.Dxgi"}, [])
        game = builder.finish(games)[0]
        self.assertEqual(game["match"]["steam"], ["2322010"])
        self.assertEqual(game["match"]["exe"], ["gowr.exe"])
        self.assertIs(wrapper.find_game({"games": [game]}, [], {"SteamAppId": "2322010"}), game)

    def test_our_own_bc250_results_win_over_the_wiki(self):
        games = {}
        builder.from_freefg(games, {"wiki": [{"title": "Shadow of the Tomb Raider",
            "ini": [{"key": "Spoofing.Dxgi", "value": "false", "when": {"gpu": "amd/intel"}}]}]}, {"dxgi": "Spoofing.Dxgi"}, [])
        builder.from_overrides(games, {"schema": 1, "games": [{"title": "Shadow of the Tomb Raider",
            "match": {"steam": ["750920"]}, "settings": {"Spoofing.Dxgi": "true"}, "tested": "t"}]},
            {"dxgi": "Spoofing.Dxgi"})
        game = builder.finish(games)[0]
        self.assertEqual([(s["key"], s["value"], s["source"]) for s in game["settings"]],
                         [("Spoofing.Dxgi", "true", "bc250")])
        self.assertEqual(game["match"]["steam"], ["750920"])
        self.assertIn("tested on a BC-250", wrapper.describe_game(game))
        with self.assertRaises(SystemExit):  # a typo never reaches players
            builder.from_overrides({}, {"schema": 1, "games": [{"title": "x", "settings": {"Spoofing.Dxgii": "1"}}]},
                                   {"dxgi": "Spoofing.Dxgi"})

    def test_the_overrides_file_names_only_keys_optiscaler_has(self):
        data = json.loads((ROOT / "scripts/game-presets-bc250.json").read_text())
        keys = builder.reference_keys([ROOT / "tests/fixtures/OptiScaler.ini"]) if (ROOT / "tests/fixtures/OptiScaler.ini").exists() else None
        for row in data["games"]:
            self.assertTrue(row["match"].get("steam") or row["match"].get("exe"), row["title"])
            for key in row["settings"]:
                self.assertRegex(key, r"^[A-Za-z0-9]+\.[A-Za-z0-9]+$")
                if keys is not None:
                    self.assertIsNotNone(builder.canonical(keys, key), key)

    def test_bc250_settings_win_over_the_wiki(self):
        games = {}
        entry = builder.entry(games, "Test Game")
        builder.add_setting(entry, "Spoofing.Dxgi", "true", "wiki")
        builder.add_setting(entry, "Spoofing.Dxgi", "false", "bc250")
        builder.add_setting(entry, "Hotfix.ColorResourceBarrier", "4", "wiki")
        out = builder.finish(games)
        self.assertEqual([(s["key"], s["value"]) for s in out[0]["settings"]],
                         [("Spoofing.Dxgi", "false"), ("Hotfix.ColorResourceBarrier", "4")])

    def test_the_mechanical_reading_does_not_repeat_freefgs(self):
        games = {}
        entry = builder.entry(games, "Test Game")
        builder.add_setting(entry, "Spoofing.Dxgi", "false", "wiki", {"gpu": "amd, intel"})
        builder.add_setting(entry, "Spoofing.Dxgi", "false", "wiki", {"gpu": "amd/intel"}, scraped=True)
        self.assertEqual(len(entry["settings"]), 1)

    def test_a_full_build_is_deterministic_and_gzipped(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            wiki = folder / "wiki"
            wiki.mkdir()
            (wiki / "Compatibility-List.md").write_text(
                "| Game | Compatibility | Inputs | OptiPatcher | Notes | Images |\n"
                "| ---- | :-: | :-: | :-: | ---- | :-: |\n"
                "| [Test Game](Test-Game) | ✅ | DLSS |  | Install as `version.dll`. |  |\n")
            (wiki / "Test-Game.asciidoc").write_text(
                "|===\n|**Filename**\n|`version.dll`\n\n|**Upscaler Inputs**\n|DLSS\n\n"
                "|**Settings**\na|\n* `ColorResourceBarrier=4`\n|===\n")
            (folder / "ini").write_text(REFERENCE_INI)
            (folder / "recipes.json").write_text(json.dumps({"schema": 1, "verified": [
                {"title": "Test Game", "match": {"steam": ["123"], "exe": ["Test.exe"]}, "status": "verified-bc250",
                 "route": "opti", "fg_input": "dlssg", "ini": {"Spoofing.Dxgi": "false"}, "launch_args": ["-dx12"],
                 "game_settings": [], "note": "n", "evidence": "generates", "observed": "2.0"}], "wiki": []}))
            outputs = []
            for name in ("a.gz", "b.gz"):
                with mock.patch("sys.argv", ["b", "--freefg", str(folder / "recipes.json"), "--freefg-commit", "f",
                                             "--wiki", str(wiki), "--wiki-commit", "w", "--ini", str(folder / "ini"),
                                             "--generated", "now", "--output", str(folder / name)]), \
                        mock.patch("sys.stderr"):
                    builder.main()
                outputs.append((folder / name).read_bytes())
            self.assertEqual(outputs[0], outputs[1])
            data = json.loads(gzip.decompress(outputs[0]))
            (entry,) = data["games"]
            self.assertEqual(entry["match"]["steam"], ["123"])
            self.assertEqual(entry["match"]["exe"], ["test.exe"])
            self.assertEqual(entry["proxy"], ["version.dll"])
            self.assertEqual({s["key"]: s["value"] for s in entry["settings"]},
                             {"Spoofing.Dxgi": "false", "FrameGen.FGInput": "dlssg",
                              "Hotfix.ColorResourceBarrier": "4"})
            self.assertEqual(entry["launch_args"], [{"arg": "-dx12", "source": "bc250"}])
            self.assertIn("content_sha256", data)


class MatchTests(unittest.TestCase):
    PRESETS = {"schema": 1, "games": [game(), {"title": "Other", "match": {"title": ["other game"]}}]}

    def test_by_steam_id_then_exe_then_title(self):
        self.assertEqual(wrapper.find_game(self.PRESETS, ["run", "x.exe"], {"SteamAppId": "123"})["title"],
                         "Test Game")
        self.assertEqual(wrapper.find_game(self.PRESETS, ["run", "C:\\Games\\TEST.exe"], {})["title"],
                         "Test Game")
        with tempfile.TemporaryDirectory() as library:
            install = Path(library) / "steamapps/common/Other"
            install.mkdir(parents=True)
            (Path(library) / "steamapps/appmanifest_77.acf").write_text('"AppState"\n{\n\t"name"\t\t"Other: Game™"\n}\n')
            env = {"SteamAppId": "77", "STEAM_COMPAT_INSTALL_PATH": str(install)}
            self.assertEqual(wrapper.find_game(self.PRESETS, ["run", "o.exe"], env)["title"], "Other")
        self.assertIsNone(wrapper.find_game(self.PRESETS, ["run", "none.exe"], {"SteamAppId": "9"}))


class PresetSelectionTests(unittest.TestCase):
    GAME = game(settings=[
        {"key": "Spoofing.Dxgi", "value": "true", "source": "wiki", "when": {"gpu": "nvidia"}},
        {"key": "Spoofing.Dxgi", "value": "false", "source": "wiki", "when": {"gpu": "amd/intel"}},
        {"key": "Hotfix.ColorResourceBarrier", "value": "4", "source": "wiki"},
        {"key": "Hotfix.RestoreComputeSignature", "value": "true", "source": "wiki",
         "when": {"upscaler_input": "dlss"}},
        {"key": "XeFG.HighResMV", "value": "true", "source": "wiki", "when": {"fg_output": "xefg"}},
        {"key": "FrameGen.Enabled", "value": "true", "source": "wiki"},
        {"key": "Log.LogToFile", "value": "true", "source": "wiki"},
        {"key": "Libraries.XeSSPath", "value": ".\\libxess.dll", "source": "wiki"},
        {"key": "Unknown.Key", "value": "1", "source": "wiki"},
        {"key": "Hotfix.RestoreComputeSignature", "value": "false", "source": "wiki", "auto": True},
    ], launch_args=[{"arg": "-dx12", "source": "wiki"},
                    {"arg": "-safe", "source": "wiki", "when": {"condition": "if it crashes"}}],
        proxy=["dxgi.dll", "version.dll"])

    def test_matching_takes_what_holds_here(self):
        settings, arguments, proxy = wrapper.game_preset(CONFIG, "v-freefg", self.GAME, "matching")
        self.assertEqual(settings, {"Spoofing.Dxgi": "false", "Hotfix.ColorResourceBarrier": "4",
                                    "XeFG.HighResMV": "true"})
        self.assertEqual(arguments, ["-dx12"])
        self.assertEqual(proxy, "dxgi.dll")  # the first name the tester confirmed

    def test_the_packages_proxy_stays_when_the_wiki_lists_it(self):
        both = game(proxy=["dxgi.dll", "winmm.dll"])
        for mode in wrapper.PRESET_MODES:
            self.assertIsNone(wrapper.game_preset(CONFIG, "v-freefg", both, mode)[2])

    def test_everything_ignores_conditions_but_prefers_the_matching_value(self):
        settings, arguments, _ = wrapper.game_preset(CONFIG, "v-freefg", self.GAME, "everything")
        self.assertEqual(settings["Spoofing.Dxgi"], "false")
        self.assertEqual(settings["Hotfix.RestoreComputeSignature"], "true")
        self.assertEqual(arguments, ["-dx12", "-safe"])

    def test_never_the_package_wiring_or_a_key_this_build_lacks(self):
        for mode in wrapper.PRESET_MODES:
            settings, _, _ = wrapper.game_preset(CONFIG, "v-freefg", self.GAME, mode)
            for key in ("FrameGen.Enabled", "Log.LogToFile", "Libraries.XeSSPath", "Unknown.Key"):
                self.assertNotIn(key, settings)
        settings, _, _ = wrapper.game_preset(CONFIG, "v-rc12", self.GAME, "everything")
        self.assertNotIn("XeFG.HighResMV", settings)

    def test_bc250_settings_apply_and_their_fg_input_sets_the_context(self):
        tested = game(settings=[
            {"key": "FrameGen.FGInput", "value": "dlssg", "source": "bc250"},
            {"key": "Libraries.XeSSPath", "value": ".\\libxess.dll", "source": "bc250"},
            {"key": "Hotfix.ColorResourceBarrier", "value": "4", "source": "wiki", "when": {"fg_input": "dlssg"}},
            {"key": "Spoofing.Dxgi", "value": "true", "source": "wiki", "when": {"fg_input": "upscaler"}},
        ], proxy=["winmm.dll"])
        settings, _, proxy = wrapper.game_preset(CONFIG, "v-freefg", tested, "matching")
        self.assertEqual(settings, {"FrameGen.FGInput": "dlssg", "Libraries.XeSSPath": ".\\libxess.dll",
                                    "Hotfix.ColorResourceBarrier": "4"})
        self.assertIsNone(proxy)  # the package's own proxy is in the list

    def test_variant_scoped_settings(self):
        scoped = game(settings=[{"key": "Spoofing.Dxgi", "value": "false", "source": "bc250",
                                 "variants": ["helixsr"]}])
        self.assertEqual(wrapper.game_preset(CONFIG, "v-freefg", scoped, "everything")[0], {})

    def test_unknown_conditions_never_match(self):
        self.assertFalse(wrapper.condition_met({"game_patch": ">=3.4"}, {}))
        self.assertFalse(wrapper.condition_met({"gpu": "nvidia without DLSS-FG support"}, {}))
        self.assertTrue(wrapper.condition_met({"gpu": "AMD, Intel", "os": "linux"}, {"os": "linux"}))


class ApplyTests(unittest.TestCase):
    PRESETS = {"schema": 1, "content_sha256": "abc", "games": [game(
        settings=[{"key": "Spoofing.Dxgi", "value": "false", "source": "bc250"},
                  {"key": "XeFG.ForceBorderless", "value": "false", "source": "wiki"},
                  {"key": "Hotfix.ColorResourceBarrier", "value": "4", "source": "wiki",
                   "when": {"condition": "if it flickers"}}],
        launch_args=[{"arg": "-dx12", "source": "bc250"}])]}

    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.ini = self.data / "pfx/drive_c/windows/system32/umu/OptiScaler.ini"
        self.env = {"STEAM_COMPAT_DATA_PATH": str(self.data), "SteamAppId": "123"}

    def apply(self, force=None, env=None):
        with mock.patch("sys.stderr"):
            return wrapper.apply_game_preset(CONFIG, "v-freefg", self.PRESETS, ["run", "test.exe"],
                                             env or self.env, force)

    def test_a_fresh_prefix_gets_the_matching_preset_and_records_it(self):
        settings, launch, _ = self.apply()
        self.assertEqual(settings, {"Spoofing.Dxgi": "false", "XeFG.ForceBorderless": "false"})
        self.assertEqual(launch, ["-dx12"])
        record = json.loads((self.data / wrapper.PRESET_RECORD).read_text())
        self.assertEqual((record["mode"], record["database"]), ("matching", "abc"))

    def test_later_launches_keep_the_ini_and_repeat_only_what_lives_nowhere_else(self):
        self.apply()
        self.ini.parent.mkdir(parents=True)
        self.ini.write_text("[Spoofing]\nDxgi=true\n")  # the player changed it in the overlay
        settings, launch, _ = self.apply()
        # ForceBorderless is enforced by the variant every launch, so it goes in again.
        self.assertEqual(settings, {"XeFG.ForceBorderless": "false"})
        self.assertEqual(launch, ["-dx12"])

    def test_forcing_applies_again_in_the_chosen_mode_and_a_fresh_ini_keeps_it(self):
        self.ini.parent.mkdir(parents=True)
        self.ini.write_text("[Spoofing]\nDxgi=true\n")
        settings, _, _ = self.apply(force="everything")
        self.assertEqual(settings["Hotfix.ColorResourceBarrier"], "4")
        self.ini.unlink()  # a variant switch starts fresh
        settings, _, _ = self.apply()
        self.assertIn("Hotfix.ColorResourceBarrier", settings)

    def test_switched_off_by_launch_option_or_for_no_upscaling(self):
        self.assertEqual(self.apply(env=dict(self.env, BC250_GAME_PRESET="0")), ({}, [], None))
        with mock.patch("sys.stderr"):
            self.assertEqual(wrapper.apply_game_preset(CONFIG, "0", self.PRESETS, ["run", "test.exe"],
                                                       self.env), ({}, [], None))

    def test_a_launch_option_can_force_a_mode(self):
        self.ini.parent.mkdir(parents=True)
        self.ini.write_text("")
        settings, _, _ = self.apply(env=dict(self.env, BC250_GAME_PRESET="everything"))
        self.assertIn("Hotfix.ColorResourceBarrier", settings)

    def test_launch_options_are_appended_once(self):
        self.assertEqual(wrapper.with_launch_options(["waitforexitandrun", "g.exe", "-DX12"], ["-dx12", "-x"]),
                         ["waitforexitandrun", "g.exe", "-DX12", "-x"])
        self.assertEqual(wrapper.with_launch_options(["getcompatpath", "a"], ["-dx12"]), ["getcompatpath", "a"])


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.env = {"HOME": str(self.home)}
        self.cache = self.home / ".cache/bc250-fsr4/game-presets.json.gz"

    def body(self, title="A"):
        return gzip.compress(json.dumps({"schema": 1, "games": [{"title": title}]}).encode())

    def test_a_fresh_cache_is_used_without_the_network(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(self.body())
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            self.assertEqual(wrapper.load_presets(self.env)["games"][0]["title"], "A")

    def test_a_failed_download_keeps_the_old_copy_and_waits_a_day(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(self.body())
        old = time.time() - 2 * wrapper.PRESETS_MAX_AGE
        os.utime(self.cache, (old, old))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")), mock.patch("sys.stderr"):
            self.assertEqual(wrapper.load_presets(self.env)["games"][0]["title"], "A")
        self.assertGreater(self.cache.stat().st_mtime, old)

    def test_a_broken_download_never_replaces_a_good_copy(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(self.body())
        os.utime(self.cache, (0, 0))
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>rate limited</html>"
        with mock.patch("urllib.request.urlopen", return_value=response), mock.patch("sys.stderr"):
            self.assertEqual(wrapper.load_presets(self.env)["games"][0]["title"], "A")

    def test_a_new_copy_is_stored(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = self.body("B")
        with mock.patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(wrapper.load_presets(self.env)["games"][0]["title"], "B")
        self.assertTrue(self.cache.is_file())

    def test_no_copy_and_no_network_is_no_presets(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")), mock.patch("sys.stderr"):
            self.assertIsNone(wrapper.load_presets(self.env))


class LaunchNeverBlockedTests(unittest.TestCase):
    def test_a_failing_preset_step_still_starts_the_game(self):
        tool = Path(tempfile.mkdtemp())
        (tool / "bc250-fsr4-config.json").write_text('{"proton": "proton"}')
        started = []
        with mock.patch.object(wrapper, "load_presets", side_effect=RuntimeError("boom")), \
                mock.patch.object(wrapper, "menu_choice", return_value=(None, {}, False, None)), \
                mock.patch.object(wrapper, "game_launch", return_value=True), \
                mock.patch.object(wrapper, "start_fresh_on_switch"), \
                mock.patch.object(wrapper, "clean_other_variants"), \
                mock.patch.object(wrapper, "environment", lambda *a, **k: {}), \
                mock.patch.object(wrapper.os, "execve", lambda *a: started.append(a)), \
                mock.patch.dict(wrapper.os.environ, {}, clear=True), \
                mock.patch.object(wrapper, "TOOL", tool), mock.patch("sys.stderr"):
            wrapper.main()
        self.assertEqual(len(started), 1)


class ReservedProxyTests(unittest.TestCase):
    """A local build can keep DLL names for the player's own loaders."""
    RESERVED = dict(CONFIG, proxy="dxgi.dll", reserved_proxies=["version.dll", "winmm.dll"])

    def test_a_reserved_name_falls_back_to_the_builds_proxy(self):
        for names in (["version.dll"], ["winmm.dll", "version.dll"]):
            self.assertIsNone(wrapper.game_preset(self.RESERVED, "v-freefg", game(proxy=names), "matching")[2])

    def test_another_name_the_wiki_gives_still_applies(self):
        self.assertEqual(wrapper.game_preset(self.RESERVED, "v-freefg", game(proxy=["winmm.dll", "dbghelp.dll"]),
                                             "everything")[2], "dbghelp.dll")

    def test_a_record_from_before_the_reservation_is_held_to_it(self):
        self.assertEqual(wrapper.reserved_proxy(self.RESERVED, "WINMM.dll"), "WINMM.dll")
        self.assertIsNone(wrapper.reserved_proxy(self.RESERVED, "dbghelp.dll"))
        self.assertIsNone(wrapper.reserved_proxy(CONFIG, "winmm.dll"))  # nothing reserved

    def test_the_payload_builder_checks_the_names(self):
        payload = load_script("payload_builder", ROOT / "scripts/build-fsr4-payload.py")
        self.assertEqual(payload.reserved_proxies("Version.dll, winmm.dll", "dxgi.dll"),
                         ["version.dll", "winmm.dll"])
        self.assertEqual(payload.reserved_proxies("", "winmm.dll"), [])
        for bad in ("../x.dll", "winmm"):
            with self.assertRaises(SystemExit):
                payload.reserved_proxies(bad, "dxgi.dll")
        with self.assertRaises(SystemExit):
            payload.reserved_proxies("winmm.dll", "winmm.dll")

    def test_the_option_reaches_the_payload_builder(self):
        for path, needle in (("scripts/build-proton-tarball.sh", "-e BC250_OPTISCALER_RESERVE="),
                             ("scripts/local-build-inside.sh", "BC250_OPTISCALER_RESERVE="),
                             ("scripts/prepare-proton-cachyos-native-pkgbuild.sh", "--reserve")):
            with self.subTest(path=path):
                self.assertIn(needle, (ROOT / path).read_text())


class MenuTests(unittest.TestCase):
    def test_the_force_choice_reaches_the_launcher(self):
        pick = {"preset": "freefg-hlxfsr4", "enable_framegen": 1, "apply_preset": "everything"}
        self.assertEqual(menu.answer(pick, "freefg-hlxfsr4", "freefg-hlxfsr4", {})["apply_preset"], "everything")
        self.assertEqual(menu.answer(dict(pick, preset="off"), "freefg-hlxfsr4", "freefg-hlxfsr4", {})
                         ["apply_preset"], "")
        self.assertEqual(menu.answer({"preset": "fsr412f", "enable_framegen": 0}, "fsr412f", "fsr412f", {})
                         ["apply_preset"], "")

    def test_the_launcher_passes_the_game_to_the_menu(self):
        self.assertIn("BC250_MENU_GAME_PRESET", wrapper.MENU_ENV)


if __name__ == "__main__":
    unittest.main()
