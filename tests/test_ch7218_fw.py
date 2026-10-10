import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "bc250-ch7218-fw"
FW = PKG / "firmware"

ORIGINAL = "CH7218A-IMG.G000.07.00.54.IMG"
TMDS = "CH7218A-IMG.G000.07.00.54.nowatchdog-tmds.IMG"
TMDS_FRL = "CH7218A-IMG.G000.07.00.54.nowatchdog-tmds+frl.IMG"
UGREEN_69 = "CH7218A-IMG.G000.07.00.69.IMG"

ORIGINAL_SHA = "a0d2643fed0c17b6b2cbdb27b5b77533745aa578e545217e9d13ad868a0dcb80"
UGREEN_69_SHA = "d9164ad45fc3219501828c422c7d1d62d8442459ea8066f805d2cb526483ed6d"
FWU_SHA = "79a87d9d0f4def58a3792661c1055de26d8f9cf29f0537ab316d31826bc42788"

TMDS_OFFSET = 0x1A4E
FRL_OFFSET = 0x27C0

# Resolved before any test puts a fake `unshare` first on PATH.
REAL_UNSHARE = shutil.which("unshare")


def rebuild(original, offsets):
    """The documented change: NOP the watchdog countdowns, fix the checksum."""
    d = bytearray(original)
    for off in offsets:
        assert d[off] == 0x14
        d[off] = 0x00
    length = int.from_bytes(d[:2], "little")
    d[length:length + 2] = (sum(d[2:length]) & 0xFFFF).to_bytes(2, "little")
    return bytes(d)


class FirmwareImageTests(unittest.TestCase):
    def test_original_is_the_unmodified_vendor_image(self):
        data = (FW / ORIGINAL).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), ORIGINAL_SHA)

    def test_ugreen_69_is_the_unmodified_vendor_image(self):
        data = (FW / UGREEN_69).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), UGREEN_69_SHA)
        self.assertIn(UGREEN_69_SHA, (PKG / "README.md").read_text())

    def test_fixed_images_are_the_original_plus_exactly_the_documented_bytes(self):
        original = (FW / ORIGINAL).read_bytes()
        self.assertEqual((FW / TMDS).read_bytes(), rebuild(original, [TMDS_OFFSET]))
        self.assertEqual((FW / TMDS_FRL).read_bytes(),
                         rebuild(original, [TMDS_OFFSET, FRL_OFFSET]))

    def test_every_image_obeys_the_length_and_checksum_rule(self):
        for name in (ORIGINAL, TMDS, TMDS_FRL, UGREEN_69):
            d = (FW / name).read_bytes()
            self.assertEqual(len(d), 65536, name)
            n = int.from_bytes(d[:2], "little")
            self.assertEqual(sum(d[2:n]) & 0xFFFF, int.from_bytes(d[n:n + 2], "little"), name)

    def test_sha256sums_matches_the_files(self):
        listed = {}
        for line in (FW / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split(None, 1)
            listed[name.lstrip("*")] = digest
        self.assertEqual(set(listed), {ORIGINAL, TMDS, TMDS_FRL, UGREEN_69})
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256((FW / name).read_bytes()).hexdigest(), digest, name)

    def test_vendor_updater_is_the_one_the_readme_names(self):
        self.assertEqual(hashlib.sha256((PKG / "ch7218_fwu").read_bytes()).hexdigest(), FWU_SHA)
        self.assertIn(FWU_SHA, (PKG / "README.md").read_text())


class PackagingTests(unittest.TestCase):
    def test_pkgbuild_ships_every_file_the_wrapper_needs(self):
        pkgbuild = (PKG / "PKGBUILD").read_text()
        for name in ("bc250-ch7218-flash", "ch7218_fwu", "README.md", "SHA256SUMS",
                     ORIGINAL, TMDS, TMDS_FRL, UGREEN_69):
            self.assertIn(name, pkgbuild)
        self.assertIn("!strip", pkgbuild, "the vendor binary must not be modified")

    def test_it_is_opt_in(self):
        meta = (ROOT / "packages" / "linux-cachyos-bc250-meta" / "PKGBUILD").read_text()
        self.assertNotIn("bc250-ch7218-fw", meta)

    def test_ci_knows_the_package(self):
        for rel in (".github/workflows/build-release.yml", "scripts/ci-build.sh",
                    "scripts/source-fingerprint.sh", "scripts/finalize-repository.sh"):
            self.assertIn("ch7218", (ROOT / rel).read_text().lower(), rel)
        self.assertTrue((ROOT / "scripts" / "build-bc250-ch7218-fw-package.sh").exists())

    def test_fingerprint_follows_the_images_and_the_updater(self):
        text = (ROOT / "scripts" / "source-fingerprint.sh").read_text()
        block = text[text.index("bc250-ch7218-fw)\n        # Our wrapper"):]
        block = block[:block.index("protonge-latest-bc250)")]
        for name in ("ch7218_fwu", "bc250-ch7218-flash", "firmware/*"):
            self.assertIn(name, block)


@unittest.skipUnless(shutil.which("unshare"), "needs unshare to get a fake root")
class WrapperTests(unittest.TestCase):
    """Run the real wrapper as namespace-root against fake aux nodes and a fake updater."""

    SIGNATURE = bytes.fromhex("2b02f0434837323138")

    @classmethod
    def setUpClass(cls):
        probe = subprocess.run([REAL_UNSHARE, "-r", "true"], capture_output=True)
        if probe.returncode != 0:
            raise unittest.SkipTest("unprivileged user namespaces are not available")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.aux = self.tmp / "dev"
        self.lib = self.tmp / "lib"
        self.img = self.tmp / "img"
        self.state = self.tmp / "state"
        self.bin = self.tmp / "bin"
        for d in (self.aux, self.lib, self.img, self.bin):
            d.mkdir()
        for f in FW.iterdir():
            shutil.copy(f, self.img / f.name)
        self.log = self.tmp / "fwu.log"
        self.version = "07:00:54"
        self.write_fwu(success=True)
        # Stand-ins for what needs real root: the namespace, mount and mknod.
        self.script(self.bin / "mount", "exit 0")
        self.script(self.bin / "mknod", "exit 0")
        self.script(self.bin / "unshare", 'while [ "$1" != -- ]; do shift; done; shift; exec "$@"')

    def script(self, path, body):
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def write_fwu(self, success):
        self.script(self.lib / "ch7218_fwu", f'''
echo "$@" >> "{self.log}"
case "$1" in
  -v) echo "FW Version: {self.version.replace(":", ":")}" ;;
  -f) {'echo "CT412 FW Update Success !"' if success else 'echo "CT412 FW Update Fail !"; exit 1'} ;;
esac
''')

    def adapter(self, n, present=True):
        node = self.aux / f"drm_dp_aux{n}"
        node.write_bytes((b"\0" * 0x500) + (self.SIGNATURE if present else b"\xff" * 9) + b"\0" * 16)

    def run_flash(self, *args, stdin=""):
        env = dict(os.environ,
                   PATH=f"{self.bin}:{os.environ['PATH']}",
                   BC250_CH7218_LIBDIR=str(self.lib), BC250_CH7218_IMGDIR=str(self.img),
                   BC250_CH7218_AUXDIR=str(self.aux), BC250_CH7218_STATE_DIR=str(self.state))
        return subprocess.run([REAL_UNSHARE, "-r", "bash", str(PKG / "bc250-ch7218-flash"), *args],
                              input=stdin, capture_output=True, text=True, env=env)

    def test_dry_run_does_every_check_and_writes_nothing(self):
        self.adapter(0)
        r = self.run_flash("flash", "tmds", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertNotIn("-f", self.log.read_text().split())

    def test_flash_needs_the_confirmation_word(self):
        self.adapter(0)
        r = self.run_flash("flash", "tmds", stdin="no\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("-f", self.log.read_text().split())

    def test_flash_writes_the_chosen_image_and_records_it(self):
        self.adapter(0)
        r = self.run_flash("flash", "tmds-frl", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn(str(self.img / TMDS_FRL), self.log.read_text())
        self.assertIn("tmds-frl", (self.state / "last-flash").read_text())

    def test_failed_update_is_reported_and_not_recorded(self):
        self.adapter(0)
        self.write_fwu(success=False)
        r = self.run_flash("flash", "tmds", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DID NOT REPORT SUCCESS", r.stderr)
        self.assertFalse((self.state / "last-flash").exists())

    def test_other_firmware_lines_and_newer_builds_are_refused(self):
        for version in ("07:08:19", "07:00:70", "07:00:99", "08:00:10", "06:00:10"):
            with self.subTest(version=version):
                self.adapter(0)
                self.version = version
                self.write_fwu(success=True)
                self.log.write_text("")
                r = self.run_flash("flash", "tmds", "--yes")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("Not flashing", r.stderr)
                self.assertNotIn("-f", self.log.read_text().split())

    def test_an_older_build_on_the_same_line_is_updated(self):
        for version in ("07:00:40", "07:00:01", "07:00:54"):
            with self.subTest(version=version):
                self.adapter(0)
                self.version = version
                self.write_fwu(success=True)
                r = self.run_flash("flash", "original", "--yes")
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertEqual("older build" in r.stdout, version != "07:00:54")

    def test_the_69_image_flashes_and_a_54_image_can_go_back_over_it(self):
        self.adapter(0)
        r = self.run_flash("flash", "ugreen-69", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn(str(self.img / UGREEN_69), self.log.read_text())
        self.assertNotIn("downgrade", r.stdout)
        self.version = "07:00:69"
        self.write_fwu(success=True)
        self.log.write_text("")
        back = self.run_flash("flash", "original", "--yes")
        self.assertEqual(back.returncode, 0, back.stderr + back.stdout)
        self.assertIn("downgrade", back.stdout)
        self.assertIn(str(self.img / ORIGINAL), self.log.read_text())

    def test_a_modified_image_is_refused(self):
        self.adapter(0)
        data = bytearray((self.img / TMDS).read_bytes())
        data[100] ^= 0xFF
        (self.img / TMDS).write_bytes(bytes(data))
        r = self.run_flash("flash", "tmds", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHA256SUMS", r.stderr)

    def test_no_adapter_is_refused(self):
        self.adapter(0, present=False)
        r = self.run_flash("flash", "original", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no CH7218", r.stderr)

    def test_several_adapters_need_an_explicit_choice(self):
        self.adapter(0)
        self.adapter(1)
        r = self.run_flash("flash", "original", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--aux", r.stderr)
        ok = self.run_flash("flash", "original", "--yes", "--aux", "1")
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)

    def test_aux_must_be_a_ch7218(self):
        self.adapter(0)
        self.adapter(1, present=False)
        r = self.run_flash("flash", "original", "--yes", "--aux", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a CH7218", r.stderr)

    def test_unknown_image_name_is_refused(self):
        self.adapter(0)
        r = self.run_flash("flash", "../../etc/passwd", "--yes")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
