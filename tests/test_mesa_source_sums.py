"""Tests for scripts/check-mesa-source-sums.py and the checksum half of
scripts/fetch-mesa-tarball.sh.

Both exist because of upstream CachyOS commit c442588745 ("mesa: 26.2.5-2",
2026-10-22): it bumped mesa and mesa/lib32-mesa in one commit and declared two
different sha256 for the same "https://archive.mesa3d.org/mesa-$_pkgver.tar.xz"
entry (794b3d17... in mesa, dca42e0c... in lib32-mesa). The file on the host is
794b3d17..., which Mesa's own release notes confirm, so every lib32-mesa build
from that commit failed with makepkg's "One or more files did not pass the
validity check!" after a complete 68 MB download -- a wrong number in a PKGBUILD
looking exactly like a bad mirror.
"""

import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-mesa-source-sums.py"
FETCH = ROOT / "scripts" / "fetch-mesa-tarball.sh"

_spec = importlib.util.spec_from_file_location("bc250_mesa_source_sums", CHECKER)
sums = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sums)

TARBALL_SUM = "7" * 64
GAMESCOPE_SUM = "9" * 64
CRATE_SUM = "a" * 64

# The real mesa PKGBUILD shape: a two-entry initial source array, then its NVK
# crates appended by a top-level loop BETWEEN the source and sha256sums arrays,
# so only the initial arrays can be paired by index.
MESA_64 = f"""\
pkgver=26.2.5
_pkgver=${{pkgver/[a-z]/-&}}
pkgrel=1
source=(
  "https://archive.mesa3d.org/mesa-$_pkgver.tar.xz"
  "gamescope-fps-limiter.patch"
)
# Rust crates for NVK, used as Meson subprojects
declare -A _crates=(
  bitflags         2.9.1
)
for _c in "${{!_crates[@]}}"; do
  source+=("https://static.crates.io/crates/${{_c}}/${{_c}}-${{_crates[$_c]}}.crate")
done
sha256sums=('{TARBALL_SUM}'
            '{GAMESCOPE_SUM}'
            '{CRATE_SUM}')
prepare() {{
  source+=( "indented-append-must-not-be-parsed" )
}}
"""

# The sibling from the same commit: same URL text, different declared sum.
LIB32_WRONG = MESA_64.replace(TARBALL_SUM, "d" * 64, 1)


def pkgbuild_fixture(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "PKGBUILD"
    path.write_text(text, encoding="utf-8")
    return path


class ParserTests(unittest.TestCase):
    def test_tarball_sum_comes_from_the_initial_arrays(self):
        path = pkgbuild_fixture(MESA_64)
        self.assertEqual(sums.declared(path, "archive.mesa3d.org")[1], TARBALL_SUM)

    def test_appended_sources_are_not_paired_with_later_sums(self):
        # 3 sums, 2 static sources: pairing past the initial array would hand the
        # gamescope patch the crate checksum.
        pairs = sums.source_sums(pkgbuild_fixture(MESA_64))
        self.assertEqual(len(pairs), 2)
        self.assertIn("gamescope-fps-limiter.patch", pairs[1][0])
        self.assertEqual(pairs[1][1], GAMESCOPE_SUM)

    def test_more_static_sources_than_sums_is_an_error(self):
        text = MESA_64.replace(
            f"  \"gamescope-fps-limiter.patch\"\n",
            f"  \"gamescope-fps-limiter.patch\"\n  'x.patch'\n",
        ).replace(f"            '{CRATE_SUM}'", "", 1)
        with self.assertRaises(sums.PkgbuildError):
            sums.source_sums(pkgbuild_fixture(text))

    def test_non_hex_sum_is_rejected(self):
        path = pkgbuild_fixture(MESA_64.replace(TARBALL_SUM, "nothex" + "0" * 58, 1))
        with self.assertRaises(sums.PkgbuildError):
            sums.source_sums(path)

    def test_rc_version_expands_like_the_pkgbuild_does(self):
        # pkgver=26.2.1rc1 -> _pkgver=26.2.1-rc1, so a literal filename written by
        # one PKGBUILD must still compare equal to the templated one.
        rc = MESA_64.replace("pkgver=26.2.5", "pkgver=26.2.1rc1", 1)
        templated = sums.normalise("mesa-$_pkgver.tar.xz", sums._expansions(rc))
        self.assertEqual(templated, "mesa-26.2.1-rc1.tar.xz")
        plain = sums.normalise("mesa-26.2.5.tar.xz", sums._expansions(MESA_64))
        self.assertEqual(plain, "mesa-26.2.5.tar.xz")

    def test_python_and_bash_expand_the_version_identically(self):
        # Two implementations of ${pkgver/[a-z]/-&} exist: here, and the sed in
        # scripts/fetch-mesa-tarball.sh. If they drift, the fetch script asks for
        # one filename while the checker normalised another -- and this is exactly
        # the bug the first version of this checker had (26.2.1-r-c1).
        for version in ("26.2.5", "26.2.1rc1", "27.0.0rc1", "26.2.5.1"):
            text = MESA_64.replace("pkgver=26.2.5", f"pkgver={version}", 1)
            mine = sums._expansions(text)["_pkgver"]
            theirs = subprocess.run(
                ["sed", "-E", "s/([a-z])/-\\1/", "-"],
                input=version, capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(mine, theirs, version)


class InvariantTests(unittest.TestCase):
    def test_same_url_two_sums_is_reported(self):
        a = pkgbuild_fixture(MESA_64)
        b = pkgbuild_fixture(LIB32_WRONG)
        found = sums.clashes([a, b])
        self.assertEqual(len(found), 1)
        source, hits = found[0]
        self.assertEqual(source, "https://archive.mesa3d.org/mesa-26.2.5.tar.xz")
        self.assertEqual({s for _, s in hits}, {TARBALL_SUM, "d" * 64})

    def test_agreeing_pkgbuilds_pass(self):
        a = pkgbuild_fixture(MESA_64)
        b = pkgbuild_fixture(MESA_64.replace("pkgrel=1", "pkgrel=1", 1))
        self.assertEqual(sums.clashes([a, b]), [])

    def test_check_cli_exits_nonzero_on_a_clash(self):
        a = pkgbuild_fixture(MESA_64)
        b = pkgbuild_fixture(LIB32_WRONG)
        out = subprocess.run(
            ["python3", "-B", str(CHECKER), "check", str(a), str(b)],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("SAME SOURCE, DIFFERENT SUMS", out.stdout)

    def test_set_rewrites_only_the_tarball_entry(self):
        path = pkgbuild_fixture(LIB32_WRONG)
        old, new = sums.set_declared(path, "archive.mesa3d.org", TARBALL_SUM)
        self.assertEqual(old, "d" * 64)
        text = path.read_text(encoding="utf-8")
        self.assertIn(TARBALL_SUM, text)
        self.assertNotIn("d" * 64, text)
        # The other entries keep their place, so makepkg's index pairing holds.
        self.assertEqual(sums.source_sums(path)[1][1], GAMESCOPE_SUM)
        self.assertEqual(sums.declared(path, "archive.mesa3d.org")[1], TARBALL_SUM)

    def test_set_refuses_an_ambiguous_or_bad_value(self):
        path = pkgbuild_fixture(MESA_64)
        with self.assertRaises(sums.PkgbuildError):
            sums.set_declared(path, "archive.mesa3d.org", "not-a-hash")
        duplicated = pkgbuild_fixture(MESA_64 + f"\n# seen twice: {TARBALL_SUM}\n")
        with self.assertRaises(sums.PkgbuildError):
            sums.set_declared(duplicated, "archive.mesa3d.org", "e" * 64)


class MesaPublishedTests(unittest.TestCase):
    # Rendered from the real docs.mesa3d.org/relnotes/26.2.5.html "SHA
    # checksums" section (fetched 2026-10-23), tags and all.
    PAGE = (
        '<section id="sha-checksums">\n'
        '<h2>SHA checksums<a class="headerlink" href="#sha-checksums">¶</a></h2>\n'
        '<div class="highlight"><pre><span></span>'
        f"SHA256: {TARBALL_SUM}  mesa-26.2.5.tar.xz\n"
        f"SHA512: {'0' * 128}  mesa-26.2.5.tar.xz\n"
        "</pre></div></section>\n"
    )

    def test_reads_the_tarball_sha256_out_of_the_markup(self):
        self.assertEqual(sums.mesa_published(self.PAGE, "mesa-26.2.5.tar.xz"), TARBALL_SUM)

    def test_missing_file_raises_rather_than_guessing(self):
        with self.assertRaises(sums.PkgbuildError):
            sums.mesa_published(self.PAGE, "mesa-99.9.9.tar.xz")


class FetchScriptChecksumTests(unittest.TestCase):
    """The fetch script runs with its own download (the file is already there)
    and reads Mesa's checksums from a fixture, so this needs no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.build = self.tmp / "build"
        self.build.mkdir()
        self.payload = b"not really an xz stream, but a fixed one\n"
        self.actual = hashlib.sha256(self.payload).hexdigest()
        (self.build / "mesa-26.2.5.tar.xz").write_bytes(self.payload)
        self.page = self.tmp / "relnotes.html"
        self.page.write_text(
            MesaPublishedTests.PAGE.replace(TARBALL_SUM, self.actual), encoding="utf-8"
        )

    def run_fetch(self, declared_sum: str):
        (self.build / "PKGBUILD").write_text(
            MESA_64.replace(TARBALL_SUM, declared_sum, 1), encoding="utf-8"
        )
        env = {"BC250_MESA_RELNOTES_HTML": str(self.page), "PATH": "/usr/bin:/bin"}
        out = subprocess.run(
            ["bash", str(FETCH), str(self.build), "c442588745"],
            capture_output=True, text=True, env=env,
        )
        return out, (self.build / "PKGBUILD").read_text(encoding="utf-8")

    def test_matching_declared_sum_is_left_alone(self):
        out, text = self.run_fetch(self.actual)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("Checksum matches the PKGBUILD", out.stdout)
        self.assertIn(self.actual, text)
        env = (self.build / "bc250-mesa-tarball.env").read_text()
        self.assertIn("MESA_TARBALL_SUM_SOURCE=pkgbuild-declared", env)
        self.assertNotIn("MESA_TARBALL_REJECTED_SUM", env)

    def test_wrong_declared_sum_is_replaced_on_mesa_s_authority(self):
        wrong = "d" * 64
        out, text = self.run_fetch(wrong)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("WARNING", out.stderr)
        self.assertIn("c442588745", out.stderr)
        self.assertNotIn(wrong, text)
        self.assertIn(self.actual, text)
        env = (self.build / "bc250-mesa-tarball.env").read_text()
        self.assertIn("MESA_TARBALL_SUM_SOURCE=mesa-relnotes", env)
        self.assertIn(f"MESA_TARBALL_REJECTED_SUM={wrong}", env)
        self.assertIn(f"MESA_TARBALL_SHA256={self.actual}", env)

    def test_if_mesa_disagrees_too_the_build_fails_before_compiling(self):
        wrong = "d" * 64
        # Mesa's page names a third value: nobody agrees, so nothing is rewritten
        # and makepkg is not allowed to discover this 40 minutes later.
        self.page.write_text(
            MesaPublishedTests.PAGE.replace(TARBALL_SUM, "e" * 64), encoding="utf-8"
        )
        out, text = self.run_fetch(wrong)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("does not match the checksum Mesa publishes", out.stderr)
        self.assertIn(wrong, out.stderr)
        self.assertIn("e" * 64, out.stderr)
        self.assertIn(self.actual, out.stderr)
        self.assertIn(wrong, text)  # PKGBUILD untouched


if __name__ == "__main__":
    unittest.main()
