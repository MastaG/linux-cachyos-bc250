import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "kytyps5-native-git"


class WiringTests(unittest.TestCase):
    def test_the_component_is_wired_into_ci(self):
        # A package nothing builds is a package nobody gets.
        for path, needle in (
            ("scripts/ci-build.sh", "build-kytyps5-native-git-package.sh"),
            ("scripts/source-fingerprint.sh", "kytyps5-native-git)"),
            ("scripts/finalize-repository.sh", "kytyps5-native-git-info.env"),
            (".github/workflows/build-release.yml", "BUILD_KYTYPS5_NATIVE_GIT"),
            (".github/workflows/build-release.yml", "resolve-kytyps5-native.sh"),
            (".github/workflows/build-release.yml", "-e KYTY_COMMIT"),
        ):
            with self.subTest(path=path, needle=needle):
                self.assertIn(needle, (ROOT / path).read_text())

    def test_it_is_optional_until_it_has_published(self):
        # Its first failed build must not stop everything else from publishing.
        text = (ROOT / "scripts/finalize-repository.sh").read_text()
        required = re.search(r"required_metadata=\((.*?)\)", text, re.S).group(1)
        optional = re.search(r"optional_metadata=\((.*?)\)", text, re.S).group(1)
        self.assertNotIn("kytyps5-native-git-info.env", required)
        self.assertIn("kytyps5-native-git-info.env", optional)
        workflow = (ROOT / ".github/workflows/build-release.yml").read_text()
        publish = workflow[workflow.index("required=("):]
        publish = publish[:publish.index(")")]
        self.assertNotIn("kytyps5-native-git", publish)

    def test_the_build_script_copies_every_packaged_file(self):
        pkgbuild = (PKG / "PKGBUILD.in").read_text()
        script = (ROOT / "scripts/build-kytyps5-native-git-package.sh").read_text()
        sources = re.search(r"source=\((.*?)\)", pkgbuild, re.S).group(1)
        local = re.findall(r"'([^']+)'", sources)
        self.assertTrue(local)
        for name in local + ["kytyps5-native-git.install"]:
            with self.subTest(name=name):
                self.assertTrue((PKG / name).is_file())
                self.assertIn(f'"$PKG_DIR"/{name}', script)
        # makepkg clones the git source into srcdir under its name: no local
        # file may use it (it did, and the clone failed).
        self.assertNotIn("kytyps5-native", local)


class NothingChangesOnInstallTests(unittest.TestCase):
    """The owner's rule: the package changes nothing on the system.

    Kernel parameters, the helper service and group membership are
    documented steps the user takes, never something an install does.
    """

    def test_install_script_enables_and_edits_nothing(self):
        text = (PKG / "kytyps5-native-git.install").read_text()
        code = "\n".join(l for l in text.splitlines()
                         if not l.lstrip().startswith(("#", "echo")))
        for forbidden in ("usermod", "gpasswd", "systemctl enable", "limine",
                          "modprobe", "kargs", "/etc/"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_package_ships_nothing_under_etc(self):
        text = (PKG / "PKGBUILD.in").read_text()
        self.assertNotIn('"$pkgdir/etc', text)
        self.assertNotIn("modprobe.d", text)
        self.assertNotIn("backup=", text)


class HelperServiceTests(unittest.TestCase):
    def test_socket_belongs_to_the_render_group(self):
        unit = (PKG / "kyty-lodhw.service").read_text()
        self.assertIn("getent group render", unit)
        # kyty-lodhw falls back to a world-writable socket without a gid:
        # the unit must refuse to start instead.
        exec_start = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
        self.assertIn("exit 1", exec_start)

    def test_no_group_is_created(self):
        # The owner's rule: not even a group. render already exists.
        self.assertNotIn("sysusers", (PKG / "PKGBUILD.in").read_text())
        self.assertFalse(list(PKG.glob("*.sysusers")))

    def test_unit_is_not_enabled_by_the_package(self):
        text = (PKG / "PKGBUILD.in").read_text()
        self.assertNotIn("multi-user.target.wants", text)


class LauncherTests(unittest.TestCase):
    def test_the_program_runs_from_a_copy_in_the_users_folder(self):
        pkgbuild = (PKG / "PKGBUILD.in").read_text()
        # The program runs from a copy in the user's folder, where it can write
        # next to itself. Upstream is changed only by whole patch files that
        # git apply refuses on a changed context, never by text replacement.
        self.assertNotIn("_replace", pkgbuild)
        for patch in re.findall(r"'([^']+\.patch)'", pkgbuild):
            with self.subTest(patch=patch):
                self.assertIn(f'git apply "$srcdir/{patch}"', pkgbuild)
        wrapper = (PKG / "kytyps5-native-wrapper.sh").read_text()
        self.assertIn("KytyPS5-Native/package", wrapper)
        self.assertIn('"$src/VERSION"', wrapper)
        # The root helper must never run from a folder the user can write.
        copied = re.search(r"for item in ([^;]+);", wrapper).group(1)
        self.assertNotIn("kyty-lodhw", copied)
        unit = (PKG / "kyty-lodhw.service").read_text()
        self.assertIn("exec /usr/lib/kytyps5-native/kyty-lodhw", unit)

    def test_no_self_updater_or_bundled_qt(self):
        script = (ROOT / "scripts/build-kytyps5-native-git-package.sh").read_text()
        self.assertIn("kyty_updater", script)
        self.assertIn("plugins/", script)


class ResolverTests(unittest.TestCase):
    def test_a_tag_outside_upstreams_scheme_is_refused(self):
        env = dict(os.environ, KYTY_TAG="v1.0")
        result = subprocess.run([str(ROOT / "scripts/resolve-kytyps5-native.sh")],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected KytyPS5-Native tag", result.stderr)


class ReadmeTests(unittest.TestCase):
    def test_the_manual_steps_are_documented(self):
        text = (ROOT / "README.md").read_text()
        start = text.index("## KytyPS5-Native")
        section = text[start:text.index("\n## ", start + 1)]
        for needle in ("ttm.pages_limit=3670016",
                       "amdgpu.sched_policy=2 amdgpu.vm_update_mode=0 amdgpu.cwsr_enable=0",
                       "sudo limine-mkinitcpio",
                       'sudo usermod -aG render "$USER"',
                       "sudo systemctl enable --now kyty-lodhw.service",
                       "changes nothing on your system"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)


if __name__ == "__main__":
    unittest.main()


class DualSenseLevelTests(unittest.TestCase):
    """The wrappers set a connected DualSense's speaker and haptics levels."""

    def run_wrapper_levels(self, env_extra):
        import tempfile
        wrapper = (PKG / "kytyps5-native-wrapper.sh").read_text()
        body = wrapper[wrapper.index("ds_levels() {"):wrapper.index("\nds_levels\n")]
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp)
            log = stub / "calls"
            (stub / "pactl").write_text(
                "#!/bin/sh\n"
                'if [ "$1 $2 $3" = "list sinks short" ]; then\n'
                '  printf "77\\talsa_output.pci-0000_01_00.1.hdmi-stereo\\tPipeWire\\n"\n'
                '  printf "225\\talsa_output.usb-Sony_Interactive_Entertainment_DualSense_Wireless_Controller-00.Direct__Direct__sink\\tPipeWire\\n"\n'
                f'else echo "pactl $*" >> {log}; fi\n')
            (stub / "amixer").write_text(f'#!/bin/sh\necho "amixer $*" >> {log}\n')
            for f in ("pactl", "amixer"):
                (stub / f).chmod(0o755)
            env = {"PATH": f"{stub}:/usr/bin:/bin", **env_extra}
            subprocess.run(["sh", "-c", body + "\nds_levels"], env=env, check=True)
            return log.read_text().splitlines() if log.exists() else []

    def test_speaker_50_and_haptics_90_on_the_dualsense_only(self):
        calls = self.run_wrapper_levels({})
        self.assertEqual(calls, ["pactl set-sink-volume alsa_output.usb-Sony_Interactive_Entertainment_"
                                 "DualSense_Wireless_Controller-00.Direct__Direct__sink 50% 50% 90% 90%"])

    def test_levels_can_be_chosen_or_left_alone(self):
        calls = self.run_wrapper_levels({"KYTYPS5_DS_SPEAKER": "70", "KYTYPS5_DS_HAPTICS": "100"})
        self.assertTrue(calls[0].endswith(" 70% 70% 100% 100%"))
        self.assertEqual(self.run_wrapper_levels({"KYTYPS5_DS_SPEAKER": "off"}), [])


def _png(path, w, h):
    """A valid, tiny RGB PNG of w x h without Pillow."""
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * w for _ in range(h))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class SteamSyncTests(unittest.TestCase):
    """kytyps5-steam-sync against a throwaway HOME: Steam is never touched
    (systemctl and pgrep are stubs that report it stopped)."""

    TOOL = PKG / "kytyps5-steam-sync"

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.cfg = self.home / ".local/share/Steam/userdata/1234/config"
        (self.cfg / "grid").mkdir(parents=True)
        # one ordinary non-Steam shortcut, as Steam writes the file
        entry = (b"\x02appid\x00" + (0x8000_0001 - (1 << 32)).to_bytes(4, "little", signed=True)
                 + b"\x01appname\x00Some Game\x00\x01exe\x00\"/usr/bin/true\"\x00"
                 + b"\x01LaunchOptions\x00\x00\x00tags\x00\x08\x08")
        (self.cfg / "shortcuts.vdf").write_bytes(b"\x00shortcuts\x00\x000\x00" + entry + b"\x08\x08")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("systemctl", "echo inactive"), ("pgrep", "exit 1")):
            (self.bin / name).write_text(f"#!/bin/sh\n{body}\n")
            (self.bin / name).chmod(0o755)
        self.runner = self.tmp / "kytyps5-run"
        self.runner.write_text("#!/bin/sh\n")
        self.games = self.tmp / "games"
        self.add_game("PPSA00001-app0", "First Game")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def add_game(self, folder, title):
        sce = self.games / folder / "sce_sys"
        sce.mkdir(parents=True)
        (sce / "param.json").write_text(
            '{"titleId": "%s", "localizedParameters": {"en-US": {"titleName": "%s"}}}'
            % (folder[:9], title))
        _png(sce / "pic0.png", 64, 36)
        _png(sce / "icon0.png", 16, 16)
        return self.games / folder

    def sync(self, *args):
        env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:{os.environ['PATH']}")
        env.pop("STEAM_PATH", None)
        return subprocess.run(["python3", str(self.TOOL), str(self.games), "--runner",
                               str(self.runner), *args], env=env, text=True,
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=60)

    def shortcuts(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("kss", str(self.TOOL))
        spec = importlib.util.spec_from_loader("kss", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        top, entries = mod.vdf_read(str(self.cfg / "shortcuts.vdf"))  # round-trips byte for byte
        return mod, entries

    def test_adds_a_game_with_its_name_and_artwork_once(self):
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mod, entries = self.shortcuts()
        self.assertEqual(list(entries), ["0", "1"])
        e = entries["1"]
        game = str(self.games / "PPSA00001-app0")
        self.assertEqual(e["appname"], "First Game (PS5)")
        self.assertEqual(e["exe"], f'"{self.runner}"')
        self.assertEqual(e["StartDir"], f'"{game}"')
        self.assertEqual(e["LaunchOptions"], f'"{game}"')
        appid = mod.entry_appid(e)
        self.assertTrue(appid & 0x8000_0000)
        grid = self.cfg / "grid"
        for name in ("%d.png", "%d_hero.png", "%d_icon.png", "%dp.png"):
            self.assertTrue((grid / (name % appid)).is_file(), name)
        self.assertEqual(e["icon"], str(grid / f"{appid}_icon.png"))
        before = (self.cfg / "shortcuts.vdf").read_bytes()
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.cfg / "shortcuts.vdf").read_bytes(), before)
        self.assertIn("0 copied, 4 already there", r.stdout)

    def test_a_symlinked_game_folder_is_not_added_twice(self):
        elsewhere = self.tmp / "other-drive"
        elsewhere.mkdir()
        import shutil
        shutil.move(str(self.games / "PPSA00001-app0"), str(elsewhere / "PPSA00001-app0"))
        (self.games / "PPSA00001-app0").symlink_to(elsewhere / "PPSA00001-app0")
        self.sync()
        self.sync()
        _, entries = self.shortcuts()
        self.assertEqual(len(entries), 2)

    def test_a_gone_game_is_kept_without_a_terminal_and_removed_with_prune(self):
        self.sync()
        mod, entries = self.shortcuts()
        appid = mod.entry_appid(entries["1"])
        import shutil
        shutil.rmtree(self.games / "PPSA00001-app0")
        r = self.sync()
        self.assertIn("its folder is gone", r.stdout)
        self.assertIn("no terminal here -> no", r.stdout)
        self.assertEqual(len(self.shortcuts()[1]), 2)
        self.add_game("PPSA00002-app0", "Second Game")
        r = self.sync("--prune")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, entries = self.shortcuts()
        self.assertEqual([e["appname"] for e in entries.values()], ["Some Game", "Second Game (PS5)"])
        self.assertEqual(list(entries), ["0", "1"])
        self.assertFalse(list((self.cfg / "grid").glob(f"{appid}*")))

    def test_the_default_folder_is_games_ps5(self):
        r = subprocess.run(["python3", str(self.TOOL), "--help"], text=True, capture_output=True)
        self.assertIn("~/Games/PS5", r.stdout)
        self.assertIn("--prune", r.stdout)
