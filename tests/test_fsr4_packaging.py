"""Exercise the preparation scripts and archive gate without building packages."""

import importlib.util
import io
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "driver_check", ROOT / "scripts/check-fsr4-driver.py"
)
driver_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver_check)

# Minimal upstream packaging contracts for the renderers. The real scripts run
# unchanged; curl is the only external input replaced by a fixture.
STABLE = """pkgver=26.2.2
pkgrel=2
source=('https://archive.mesa3d.org/mesa-26.2.2.tar.xz')
sha256sums=('unused-in-render-test')
b2sums=('unused-in-render-test')
prepare() {
  :
}
build() {
  :
}
"""
GIT = """pkgrel=1
build () {
    if [ -n "$_custom_opt_flags" ]; then
      export CFLAGS="${_custom_opt_flags}"
      export CPPFLAGS="${_custom_opt_flags}"
      export CXXFLAGS="${_custom_opt_flags}"
    fi
}
"""
NATIVE = """pkgname=proton-cachyos-native
_srctag=11.0-test
pkgrel=3
source=('upstream-source')
b2sums=('unused-in-render-test')
provides=('proton-cachyos' 'proton')
replaces=('proton-cachyos')
prepare() {
    cd proton-cachyos
}
build() {
    local march="nocona"
    local mtune="core-avx2"
    sed -r \\
      -e "s|##DISPLAY_NAME##|proton-cachyos-${_srctag} (native)|" \\
      "${srcdir}/compatibilitytool.vdf.template" > compatibilitytool.vdf
}
"""


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fsr4 packaging ")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        (self.work / "stable").write_text(STABLE)
        (self.work / "git").write_text(GIT)
        (self.work / "native").write_text(NATIVE)
        commands = self.work / "bin"
        commands.mkdir()
        curl = commands / "curl"
        curl.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
url = args[-1]
# resolve-fakenvapi.sh reads the release API and hashes the asset, both without
# -o, so this stub has to answer on stdout too -- and answer plausibly, because
# the point is to exercise the real resolver's parsing rather than skip it.
if 'api.github.com' in url and url.endswith('/releases/latest'):
    sys.stdout.write(
        '{"tag_name": "v1.4.1", "assets": '
        '[{"name": "fakenvapi-v1.4.1.7z"}]}\\n'
    )
    sys.exit(0)
if url.endswith('.7z') and 'fakenvapi' in url:
    sys.stdout.write('fixture fakenvapi archive\\n')
    sys.exit(0)
output = Path(args[args.index('-o') + 1])
if url.endswith('/PKGBUILD'):
    kind = 'native' if '/proton-cachyos-native/' in url else ('git' if '/mesa-git/' in url else 'stable')
    text = (Path(os.environ['BC250_TEST_UPSTREAM']) / kind).read_text()
elif url.endswith('/customization.cfg'):
    text = '_lib32=true\\n_user_patches="true"\\n_user_patches_no_confirm="true"\\n'
else:
    text = 'fixture for ' + output.name + '\\n'
output.write_text(text)
""")
        curl.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=str(commands) + ":" + os.environ["PATH"],
            BC250_TEST_UPSTREAM=str(self.work),
            CACHYOS_MESA_COMMIT="a" * 40,
            MESA_GIT_COMMIT="b" * 40,
            BC250_SKIP_MESA_PREFETCH="1",
        )

    def test_every_production_patch_reaches_each_generated_package(self):
        for family, script, variable in (
            ("mesa", "prepare-mesa-pkgbuild.sh", "MESA_BUILD_DIR"),
            ("mesa", "prepare-lib32-mesa-pkgbuild.sh", "LIB32_MESA_BUILD_DIR"),
            ("mesa-git", "prepare-mesa-git-pkgbuild.sh", "MESA_GIT_BUILD_DIR"),
        ):
            with self.subTest(script=script):
                output = self.work / script
                env = dict(self.env, **{variable: str(output)})
                subprocess.run(
                    ["bash", str(ROOT / "scripts" / script)],
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                expected = sorted((ROOT / "patches" / family).glob("*.patch"))
                self.assertGreaterEqual(len(expected), 9)
                if family == "mesa-git":
                    actual = sorted((output / "mesa-userpatches").glob("*.mymesapatch"))
                    self.assertEqual(
                        [p.stem for p in actual], [p.stem for p in expected]
                    )
                else:
                    result = subprocess.check_output(
                        [
                            "bash",
                            "-c",
                            'source "$1"; printf "%s\\n" "${source[@]}"',
                            "_",
                            str(output / "PKGBUILD"),
                        ],
                        text=True,
                    )
                    self.assertEqual(
                        [
                            line
                            for line in result.splitlines()
                            if line.endswith(".patch")
                        ],
                        [p.name for p in expected],
                    )
                    actual = [output / p.name for p in expected]
                for staged, source in zip(actual, expected):
                    self.assertEqual(staged.read_bytes(), source.read_bytes())

    def test_native_payload_failure_stops_build_even_when_errexit_is_suppressed(self):
        output = self.work / "native-build"
        env = dict(self.env, PROTON_CACHYOS_NATIVE_BUILD_DIR=str(output))
        subprocess.run(
            ["bash", str(ROOT / "scripts/prepare-proton-cachyos-native-pkgbuild.sh")],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        (output / "toolmanifest.vdf").write_text('"commandline" "/proton %verb%"\n')
        result = subprocess.run(
            [
                "bash",
                "-c",
                """
source "$1/PKGBUILD"
srcdir="$1"
python3() { return 42; }
install() { printf 'unexpected install\\n' >> "$srcdir/installed-after-failure"; }
# makepkg/pkgfunc callers can suppress errexit this way. The builder failure
# must still be returned before any later install/sed command masks it.
if build; then exit 99; else exit 0; fi
""",
                "_",
                str(output),
            ],
            cwd=output,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((output / "installed-after-failure").exists())


class IntegrityArrayTests(unittest.TestCase):
    """Every source needs an entry in every integrity array makepkg sees.

    makepkg only reports this as "Integrity checks (shaN) differ in size from
    the source array" once it has already downloaded everything, so a one-line
    omission costs a full fetch before it fails -- and it failed exactly that
    way in CI when a source was added without extending sha512sums.
    """

    def test_protonge_template_arrays_all_match_the_source_count(self):
        template = ROOT / "packages/protonge-latest-bc250/PKGBUILD.in"
        with tempfile.TemporaryDirectory() as temporary:
            # The template's @PLACEHOLDERS@ are all inside quotes, so a dummy
            # substitution leaves a file bash can source verbatim.
            text = re.sub(r"@[A-Z0-9_]+@", "dummy", template.read_text())
            pkgbuild = Path(temporary, "PKGBUILD")
            pkgbuild.write_text(text)
            counts = subprocess.check_output(
                [
                    "bash",
                    "-c",
                    'source "$1" >/dev/null 2>&1; '
                    'printf "%s %s %s" "${#source[@]}" "${#sha256sums[@]}" '
                    '"${#sha512sums[@]}"',
                    "_",
                    str(pkgbuild),
                ],
                text=True,
            ).split()
        sources, sha256, sha512 = (int(value) for value in counts)
        self.assertGreater(sources, 0)
        self.assertEqual(sha256, sources, "sha256sums does not cover every source")
        self.assertEqual(sha512, sources, "sha512sums does not cover every source")


class LutrisLayoutTests(unittest.TestCase):
    """Every launcher has to reach the shim, not just Steam.

    Steam and Heroic read toolmanifest.vdf, and so does umu, so the shim is
    honoured by all three. Lutris first decides whether a Proton is usable at
    all by probing for a wine executable in two fixed places, and refuses the
    tool when it finds neither -- which is what protonge-latest-bc250 did,
    because GE's own tree lives under ge/ there.
    """

    #: verbatim from lutris/util/wine/proton.py, Lutris v0.5.22
    @staticmethod
    def lutris_wine_path(tool):
        for candidate in ("dist/bin/wine", "files/bin/wine"):
            path = os.path.join(tool, candidate)
            if os.path.exists(path):
                return path
        raise AssertionError(f"Lutris would refuse {tool}: no wine executable")

    @staticmethod
    def lutris_protonpath(wine_path):
        directory_path = os.path.dirname(wine_path)
        return os.path.dirname(os.path.dirname(directory_path))

    def test_lutris_finds_wine_and_still_lands_on_the_shim(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary, "protonge-latest-bc250")
            (tool / "ge/files/bin").mkdir(parents=True)
            (tool / "ge/files/bin/wine").write_text("#!/bin/sh\n")
            (tool / "proton").write_text("#!/bin/sh\n")
            (tool / "toolmanifest.vdf").write_text(
                '"manifest"\n{\n  "commandline" "/proton %verb%"\n}\n'
            )
            # what package() lays down
            (tool / "files").symlink_to("ge/files")

            wine = self.lutris_wine_path(str(tool))
            protonpath = self.lutris_protonpath(wine)
            # Lexical, so it must land on the tool root and not inside ge/ --
            # otherwise umu would read GE's own manifest and skip the shim.
            self.assertEqual(Path(protonpath), tool)
            # umu resolves PROTONPATH before reading the manifest beside it.
            self.assertEqual(Path(protonpath).resolve(strict=True), tool.resolve())
            manifest = (tool / "toolmanifest.vdf").read_text()
            command = manifest.split('"commandline"')[1].split('"')[1]
            self.assertEqual(Path(protonpath + command.split()[0]).name, "proton")

    def test_the_package_creates_the_symlink_and_refuses_to_dangle(self):
        pkgbuild = (
            ROOT / "packages/protonge-latest-bc250/PKGBUILD.in"
        ).read_text()
        self.assertIn('ln -s ge/files "$_tool/files"', pkgbuild)
        self.assertIn('[[ ! -x "$_tool/ge/files/bin/wine" ]]', pkgbuild)


class PackageGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def package(self, filename, name, *, bits=64, v4=True, include_driver=True):
        path = self.work / filename
        files = {".PKGINFO": ("pkgname = " + name + "\n").encode()}
        if include_driver:
            header = bytearray(64)
            header[:7] = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1, 1])
            header[16:20] = (3).to_bytes(2, "little") + (
                62 if bits == 64 else 3
            ).to_bytes(2, "little")
            markers = (
                b"\0".join(marker.encode() for marker in driver_check.MARKERS) + b"\0"
            )
            files["usr/lib" + ("32" if bits == 32 else "") + "/libvulkan_radeon.so"] = (
                bytes(header) + (markers if v4 else b"V3 only")
            )
        with tarfile.open(path, "w:gz") as archive:
            for member, data in files.items():
                entry = tarfile.TarInfo(member)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        return path

    def test_old_driver_is_rejected_even_when_named_as_a_new_package(self):
        package = self.package("new-version.pkg.tar.gz", "vulkan-radeon", v4=False)
        with self.assertRaisesRegex(RuntimeError, "missing FSR4 v4 code"):
            driver_check.verify_packages([package], {"vulkan-radeon"})

    def test_both_mesa_git_architectures_are_required_and_verified(self):
        native = self.package("native.pkg.tar.gz", "mesa-git")
        compat = self.package("compat.pkg.tar.gz", "lib32-mesa-git", bits=32)
        expected = {"mesa-git", "lib32-mesa-git"}
        self.assertEqual(
            len(driver_check.verify_packages([native, compat], expected)), 2
        )
        with self.assertRaisesRegex(RuntimeError, "Missing production driver"):
            driver_check.verify_packages([native], expected)
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            driver_check.verify_packages([native, native, compat], expected)

    def test_metadata_cannot_substitute_for_the_driver_member(self):
        package = self.package(
            "missing.pkg.tar.gz", "vulkan-radeon", include_driver=False
        )
        with self.assertRaises(subprocess.CalledProcessError):
            driver_check.verify_packages([package], {"vulkan-radeon"})


if __name__ == "__main__":
    unittest.main()
