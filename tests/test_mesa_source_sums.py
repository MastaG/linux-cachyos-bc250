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

Run 40026235876 (the first with the sha256 fix) then failed one step later, and
that is the second half of the story: it rewrote the sha256, passed the sha256
group, and died in "Validating source files with b2sums" -- the same upstream
commit also wrote a wrong b2sums entry in lib32-mesa (347f1e11... where the file
is cfcc4d72..., measured on the runner's own copy, and the sibling mesa PKGBUILD
agrees with the file). So the PKGBUILD can declare ANY checksum array for the
tarball, and every one of them that disagrees with a file Mesa has confirmed is
rewritten from the file; the relnotes page's SHA512 line is used as a second
opinion on the file before anything is rewritten.
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

# The real failing shape, copied from the runner's own lib32-mesa PKGBUILD after
# run 40026235876: the tarball carries BOTH a sha256sums and a b2sums entry, and
# upstream wrote the wrong value in both. The values below are the real ones
# (declared on the left, what the file actually is on the right).
REAL_LIB32_SHA256_DECLARED = "dca42e0c590aa896e820e43a23c72775055f4f0eaa237b30c877abfc25703a01"
REAL_LIB32_SHA256_FILE = "794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5"
REAL_LIB32_B2_DECLARED = (
    "347f1e11f96eca97a676fb0954342c81957f4326ab4c15e75e2b4f7ee48a94d5"
    "f6e42091139c9b792ed8291779ebce4b1e37d57357ffd8c23106dd37982ce00a"
)
REAL_LIB32_B2_FILE = (
    "cfcc4d72c5e6f54904c77b98c65df8159c41ebe9c4b8f82a18a38983bfe06e25"
    "c02ea20ba613753838f2455edb156a2d79938f28328313a8eb79fe67d2ea9624"
)
GAMESCOPE_B2 = "5" * 128

LIB32_MULTI = f"""\
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
  sha256sums+=("SKIP")
  b2sums+=("SKIP")
done
sha256sums=('{REAL_LIB32_SHA256_DECLARED}'
            '{GAMESCOPE_SUM}')
b2sums=('{REAL_LIB32_B2_DECLARED}'
        '{GAMESCOPE_B2}')
prepare() {{
  :
}}
"""


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


class MultiArrayTests(unittest.TestCase):
    """The parser half of the 2026-10-23 lesson: one source, several arrays."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.payload = b"the tarball, small on purpose\n"
        self.file = self.tmp / "mesa-26.2.5.tar.xz"
        self.file.write_bytes(self.payload)
        self.sha256 = hashlib.sha256(self.payload).hexdigest()
        self.b2 = hashlib.blake2b(self.payload).hexdigest()
        self.path = pkgbuild_fixture(LIB32_MULTI)

    def test_every_array_for_the_entry_is_compared(self):
        found = sums.mismatches(self.path, self.file, "archive.mesa3d.org")
        self.assertEqual(
            found,
            [("sha256sums", 0, REAL_LIB32_SHA256_DECLARED, self.sha256),
             ("b2sums", 0, REAL_LIB32_B2_DECLARED, self.b2)],
        )

    def test_sync_rewrites_every_array_and_nothing_else(self):
        changes = sums.sync_rewrite(self.path, self.file, "archive.mesa3d.org")
        self.assertEqual(
            [(name, old, new) for name, _i, old, new in changes],
            [("sha256sums", REAL_LIB32_SHA256_DECLARED, self.sha256),
             ("b2sums", REAL_LIB32_B2_DECLARED, self.b2)],
        )
        text = self.path.read_text(encoding="utf-8")
        self.assertIn(self.sha256, text)
        self.assertIn(self.b2, text)
        # The patch entries keep their places, so makepkg's index pairing holds,
        # and so do the sums appended by the crate loop.
        self.assertIn(GAMESCOPE_SUM, text)
        self.assertIn(GAMESCOPE_B2, text)
        self.assertIn("sha256sums+=(\"SKIP\")", text)

    def test_an_array_it_cannot_compute_is_a_refusal_not_a_partial_fix(self):
        # BLAKE3 is real in newer makepkg; if a PKGBUILD declares it for this
        # source, rewriting sha256 and b2sums and leaving b3sums wrong would just
        # move the failure.
        text = f"b3sums=('{'0' * 64}'\n         '{'1' * 64}')\n" + LIB32_MULTI
        path = pkgbuild_fixture(text)
        with self.assertRaises(sums.PkgbuildError):
            sums.mismatches(path, self.file, "archive.mesa3d.org")

    def test_an_entry_of_the_wrong_length_is_a_refusal(self):
        path = pkgbuild_fixture(
            LIB32_MULTI.replace(REAL_LIB32_B2_DECLARED, "abc", 1)
        )
        with self.assertRaises(sums.PkgbuildError):
            sums.mismatches(path, self.file, "archive.mesa3d.org")

    def test_the_page_answers_with_every_digest_it_lists(self):
        found = sums.published_checksums(MesaPublishedTests.PAGE, "mesa-26.2.5.tar.xz")
        self.assertEqual(found["sha256"], TARBALL_SUM)
        self.assertEqual(found["sha512"], "0" * 128)
        # And the old single-digest view still works for its callers.
        self.assertEqual(sums.mesa_published(MesaPublishedTests.PAGE,
                                             "mesa-26.2.5.tar.xz"), TARBALL_SUM)


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
        self.sha512 = hashlib.sha512(self.payload).hexdigest()
        (self.build / "mesa-26.2.5.tar.xz").write_bytes(self.payload)
        self.page = self.tmp / "relnotes.html"
        self.page.write_text(
            MesaPublishedTests.PAGE.replace(TARBALL_SUM, self.actual).replace(
                "0" * 128, self.sha512
            ),
            encoding="utf-8",
        )

    def run_fetch(self, declared_sum: str):
        (self.build / "PKGBUILD").write_text(
            MESA_64.replace(TARBALL_SUM, declared_sum, 1), encoding="utf-8"
        )
        return self.run_fetch_pkgbuild()

    def run_fetch_pkgbuild(self):
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

    def test_every_declared_array_is_rewritten_from_the_verified_file(self):
        # The real lib32-mesa case: sha256 AND b2sums both wrong. The old code
        # fixed one and makepkg aborted on the other; now one WARNING names both.
        (self.build / "PKGBUILD").write_text(LIB32_MULTI, encoding="utf-8")
        out, text = self.run_fetch_pkgbuild()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(self.actual, text)
        self.assertIn(hashlib.blake2b(self.payload).hexdigest(), text)
        self.assertNotIn(REAL_LIB32_SHA256_DECLARED, text)
        self.assertNotIn(REAL_LIB32_B2_DECLARED, text)
        # The patch's own entries are not ours to touch.
        self.assertIn(GAMESCOPE_SUM, text)
        self.assertIn(GAMESCOPE_B2, text)
        self.assertIn("WARNING", out.stderr)
        self.assertIn("sha256sums[0]", out.stderr)
        self.assertIn("b2sums[0]", out.stderr)
        self.assertIn("c442588745", out.stderr)
        env = (self.build / "bc250-mesa-tarball.env").read_text()
        self.assertIn("MESA_TARBALL_SUM_SOURCE=mesa-relnotes", env)
        self.assertIn("MESA_TARBALL_REPLACED_ARRAYS=sha256sums,b2sums", env)
        self.assertIn(f"MESA_TARBALL_REJECTED_SUM={REAL_LIB32_SHA256_DECLARED}", env)
        self.assertIn(
            f"MESA_TARBALL_REJECTED_SUM_B2SUMS={REAL_LIB32_B2_DECLARED}", env
        )
        self.assertIn(f"MESA_TARBALL_SHA512_MATCHES_MESA=Y", env)

    def test_a_wrong_b2sums_alone_still_goes_through_mesa_s_authority(self):
        # sha256 agrees with the file, so nothing is trusted blindly here: the
        # b2sums entry is the one that would have failed the build.
        text = LIB32_MULTI.replace(REAL_LIB32_SHA256_DECLARED, self.actual, 1)
        (self.build / "PKGBUILD").write_text(text, encoding="utf-8")
        out, written = self.run_fetch_pkgbuild()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("asking Mesa", out.stderr)
        self.assertIn(hashlib.blake2b(self.payload).hexdigest(), written)
        self.assertNotIn(REAL_LIB32_B2_DECLARED, written)
        env = (self.build / "bc250-mesa-tarball.env").read_text()
        self.assertIn("MESA_TARBALL_REPLACED_ARRAYS=b2sums", env)
        self.assertIn(f"MESA_TARBALL_REJECTED_SUM_B2SUMS={REAL_LIB32_B2_DECLARED}", env)
        self.assertNotIn("MESA_TARBALL_REJECTED_SUM=", env)

    def test_the_page_sha512_is_a_second_opinion_and_it_vetoes(self):
        # Mesa's page lists SHA512 as well; if the file does not match it, the
        # file is not Mesa's release and no array may be rewritten from it.
        (self.build / "PKGBUILD").write_text(LIB32_MULTI, encoding="utf-8")
        self.page.write_text(
            MesaPublishedTests.PAGE.replace(TARBALL_SUM, self.actual).replace(
                "0" * 128, "f" * 128
            ),
            encoding="utf-8",
        )
        out, text = self.run_fetch_pkgbuild()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("SHA512", out.stderr)
        self.assertIn("f" * 128, out.stderr)
        self.assertIn(REAL_LIB32_SHA256_DECLARED, text)  # nothing rewritten
        self.assertIn(REAL_LIB32_B2_DECLARED, text)


if __name__ == "__main__":
    unittest.main()
