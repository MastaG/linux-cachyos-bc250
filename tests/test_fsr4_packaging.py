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
    git submodule update --init --filter=tree:0 --recursive ${_submodules[@]}
    for rustlib in gst-plugins-rs; do
    pushd $rustlib
        cargo fetch --locked --target x86_64-unknown-linux-gnu
    popd
    done
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


class KernelPatchSetTests(unittest.TestCase):
    """The two kernel patch sets must not drift apart silently.

    They are anchored to different kernel series, so they are separate
    directories -- but everything except the series-specific carries is meant to
    be in both. When 7.2.5 backported the drm/gud change, the stable kernel
    stopped building because its set was missing a patch the RC set had had for
    weeks, and nothing said so until CI went red.
    """

    STABLE = ROOT / "patches/linux-cachyos"
    RC = ROOT / "patches/linux-cachyos-rc"

    # Patches that legitimately exist in one set only, with the reason.
    RC_ONLY = {"0010-hdmi21-vtem-on-tmds.patch": "backport that applies only to 7.3"}

    def test_the_sets_differ_only_by_documented_carries(self):
        stable = {p.name for p in self.STABLE.glob("*.patch")}
        rc = {p.name for p in self.RC.glob("*.patch")}
        self.assertEqual(sorted(rc - stable), sorted(self.RC_ONLY),
                         "a patch is in the RC set but not in the stable one")
        self.assertEqual(sorted(stable - rc), [],
                         "a patch is in the stable set but not in the RC one")

    @staticmethod
    def substance(path):
        """What a patch does, without where it happens to land.

        The two sets are regenerated against different kernels on purpose, so
        blob hashes in `index` lines and hunk offsets differ by design. What
        must not differ is the files touched and the lines changed.
        """
        touched, changed = [], []
        for line in path.read_text().splitlines():
            if line.startswith("diff --git"):
                touched.append(line)
            elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                changed.append(line)
        return touched, changed

    def test_shared_patches_do_the_same_thing_in_both_sets(self):
        for name in sorted({p.name for p in self.STABLE.glob("*.patch")}):
            with self.subTest(patch=name):
                self.assertEqual(self.substance(self.STABLE / name),
                                 self.substance(self.RC / name))

    def test_docs_list_the_patches_that_actually_ship(self):
        """docs/PATCHES.md names the shared set in a fenced block; keep it true.

        It is the only place a reader can see what the kernels carry, and it has
        gone stale before -- it still said "nine patches" after two were added.
        """
        text = (ROOT / "docs/PATCHES.md").read_text()
        marker = "Both sets share these"
        block = text.split(marker, 1)[1].split("```text", 1)[1].split("```", 1)[0]
        documented = [line.strip() for line in block.splitlines() if line.strip()]
        shipped = sorted(p.name for p in self.STABLE.glob("*.patch"))
        self.assertEqual(documented, shipped)
        self.assertIn(self.number_word(len(shipped)) + " patches", text)
        self.assertIn(self.number_word(len(shipped)) + " BC-250 patches", text)

    @staticmethod
    def number_word(n):
        words = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
                 13: "thirteen", 14: "fourteen", 15: "fifteen"}
        return words[n]


class MetapackageDocsTests(unittest.TestCase):
    """The README's metapackage list must match what the metapackage installs.

    The list is the only place a user can see what `-meta` pulls in before
    installing it, so a stale one is a user-facing lie. It went stale once
    already: `proton-cachyos-slr-bc250` was added to `depends=` and the README
    kept describing "the two Proton packages", sizes and Steam entries included.
    """

    PKGBUILD = ROOT / "packages/linux-cachyos-bc250-meta/PKGBUILD"
    README = ROOT / "README.md"

    def depends(self):
        text = self.PKGBUILD.read_text()
        body = text.split("depends=(", 1)[1].split(")", 1)[0]
        names = []
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip().strip("'\"")
            if line:
                names.append(line)
        return names

    def documented(self):
        lines = self.README.read_text().splitlines()
        start = lines.index("## linux-cachyos-bc250-meta")
        names, seen_list = [], False
        for line in lines[start:]:
            if line.startswith("- `"):
                seen_list = True
                names.append(line.split("`")[1])
            elif seen_list and not line.strip():
                break
        return names

    def test_readme_lists_exactly_what_the_metapackage_depends_on(self):
        self.assertEqual(sorted(self.documented()), sorted(self.depends()))

    def test_readme_does_not_miscount_the_proton_packages(self):
        protons = [d for d in self.depends() if "proton" in d]
        text = self.README.read_text()
        wrong = [phrase for phrase in ("The two Proton packages",
                                       "both FSR4 Proton packages",
                                       "two entries in Steam")
                 if phrase in text]
        self.assertEqual(wrong, [],
                         "README still describes a different number of Proton "
                         "packages than the %d the metapackage installs" % len(protons))


class SlrPackageTests(unittest.TestCase):
    """The Steam Linux Runtime package's promises, checked at the source.

    This one exists for a single reason -- it runs inside the Steam Linux
    Runtime, which is what a game with EasyAntiCheat or BattlEye needs and what
    proton-cachyos-native-bc250 cannot do. Everything else about it duplicates
    the native package, so the checks here are about not losing that.
    """

    TEMPLATE = ROOT / "packages/proton-cachyos-slr-bc250/PKGBUILD.in"

    def test_the_build_refuses_a_tree_without_the_runtime_manifest(self):
        text = self.TEMPLATE.read_text()
        self.assertIn('grep -q \'"require_tool_appid"\' toolmanifest.vdf', text)
        # ...and says why, rather than failing with a bare grep exit code.
        self.assertIn("not a Steam Linux Runtime build", text)

    def test_it_uses_the_cachyos_rooted_protonfixes_patch(self):
        # CachyOS patch upscalers.py several times before this package sees it,
        # so the GE-rooted copy does not apply. Picking the wrong one would
        # leave the launch fetching its upscaler manifest from the network.
        script = (ROOT / "scripts/build-proton-cachyos-slr-bc250-package.sh").read_text()
        self.assertIn("stage_fsr4_payload_sources \"$ROOT_DIR\" \"$BUILD_DIR\" proton-cachyos",
                      script)

    def test_the_package_wraps_a_tree_it_did_not_build_itself(self):
        # The compile needs Valve's SDK image, which makepkg cannot start. The
        # script must therefore fail with instructions rather than silently
        # packaging nothing.
        script = (ROOT / "scripts/build-proton-cachyos-slr-bc250-package.sh").read_text()
        self.assertIn("build-proton-runtime-dist.sh", script)
        self.assertIn("has not been built yet", script)

    def test_every_proton_package_ships_the_same_payload_inputs(self):
        # Three packages, one payload. A variant that reached only two of them
        # would be a silent difference in what users get.
        templates = {
            "slr": self.TEMPLATE.read_text(),
            "ge": (ROOT / "packages/protonge-latest-bc250/PKGBUILD.in").read_text(),
            "native": (ROOT / "scripts/prepare-proton-cachyos-native-pkgbuild.sh").read_text(),
        }
        for name, text in templates.items():
            with self.subTest(package=name):
                self.assertIn("--ffx-sdk-default fsr411f", text)
                self.assertIn("--ffx-sdk-alt fsr411b", text)
                self.assertIn("--ffx-sdk-alt fsr411f", text)
                self.assertIn("bc250-fsr4-dll-4.0.0-rc9.tar.xz", text)

    def test_the_metapackage_pulls_in_all_three(self):
        pkgbuild = (ROOT / "packages/linux-cachyos-bc250-meta/PKGBUILD").read_text()
        for package in ("protonge-latest-bc250", "proton-cachyos-native-bc250",
                        "proton-cachyos-slr-bc250"):
            self.assertIn(f"'{package}'", pkgbuild)

    def test_the_component_is_wired_into_ci(self):
        # A package nothing builds is a package nobody gets.
        for path, needle in (
            ("scripts/ci-build.sh", "build-proton-cachyos-slr-bc250-package.sh"),
            ("scripts/source-fingerprint.sh", "proton-cachyos-slr-bc250)"),
            ("scripts/finalize-repository.sh", "proton-cachyos-slr-bc250-info.env"),
            (".github/workflows/build-release.yml", "BUILD_PROTON_CACHYOS_SLR_BC250"),
            (".github/workflows/build-release.yml", "build-proton-runtime-dist.sh"),
        ):
            with self.subTest(path=path):
                self.assertIn(needle, (ROOT / path).read_text())


class LocalPatchGateTests(unittest.TestCase):
    """local-patches/ must reach a local build and nothing else.

    The hook exists so a private build can carry a patch that has no business
    in a published package. That is only true while the gate holds, so the gate
    is tested rather than trusted: the same block of shell that ships inside
    each PKGBUILD is executed here, with and without the variable set.
    """

    MARKER = "# Local private builds only"

    def hook(self, text):
        """The shipped hook, lifted verbatim out of a PKGBUILD."""
        start = text.index(self.MARKER)
        end = text.index("\n    fi\n", start) + len("\n    fi\n")
        block = text[start:end]
        self.assertIn("BC250_LOCAL_PATCHES", block)
        return block

    def sources(self):
        generated = tempfile.TemporaryDirectory(prefix="fsr4 local patches ")
        self.addCleanup(generated.cleanup)
        subprocess.run(
            ["bash", str(ROOT / "scripts/prepare-proton-cachyos-native-pkgbuild.sh")],
            env=dict(
                os.environ,
                PROTON_CACHYOS_NATIVE_BUILD_DIR=str(Path(generated.name) / "native"),
                BC250_SKIP_MESA_PREFETCH="1",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        # Only the native package: the Steam Linux Runtime builds are not built
        # locally, so they carry no hook to test.
        return {
            "proton-cachyos-native": (Path(generated.name) / "native/PKGBUILD").read_text(),
        }

    def run_hook(self, block, tree, patches, **environment):
        # `return 1` is what the hook uses to abort a pkgfunc, so it has to run
        # inside one here as well.
        return subprocess.run(
            ["bash", "-c", "_hook() {\n" + block + "\n}\n_hook"],
            cwd=tree,
            env=dict(os.environ, BC250_LOCAL_PATCHES_DIR=str(patches), **environment),
            capture_output=True,
            text=True,
        )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fsr4 local patches run ")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def patch_set(self, name, body):
        directory = self.work / "patches" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "0001-test.patch").write_text(body)
        return self.work / "patches"

    def tree(self, name):
        tree = self.work / "tree" / name
        tree.mkdir(parents=True, exist_ok=True)
        (tree / "target.txt").write_text("original\n")
        return tree

    GOOD = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-original
+patched
"""
    BAD = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-something that is not there
+patched
"""

    def test_local_patches_run_only_once_the_submodules_are_there(self):
        """Ordering is the whole bug: wine is a submodule.

        Run before `git submodule update`, a patch against an existing file in
        wine, dxvk or vkd3d-proton finds nothing to patch and is skipped, while
        its new-file hunks apply anyway -- a half-patched tree that still builds.
        Reported from a local build, where every wine/ hunk was ignored.
        """
        text = self.sources()["proton-cachyos-native"]
        self.assertLess(
            text.index("git submodule update --init"),
            text.index(self.MARKER),
            "local patches must be applied after the submodules are checked out",
        )
        # ...and still inside prepare(), not stranded in build().
        self.assertLess(text.index(self.MARKER), text.index("\nbuild() {"))

    def test_an_unset_variable_leaves_the_tree_alone(self):
        for name, text in self.sources().items():
            with self.subTest(package=name):
                tree = self.tree(name)
                patches = self.patch_set(name, self.GOOD)
                result = self.run_hook(self.hook(text), tree, patches)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((tree / "target.txt").read_text(), "original\n")

    def test_a_local_build_applies_them_in_order(self):
        for name, text in self.sources().items():
            with self.subTest(package=name):
                tree = self.tree(name)
                patches = self.patch_set(name, self.GOOD)
                result = self.run_hook(
                    self.hook(text), tree, patches, BC250_LOCAL_PATCHES="1"
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((tree / "target.txt").read_text(), "patched\n")

    def test_a_patch_that_does_not_apply_stops_the_build(self):
        for name, text in self.sources().items():
            with self.subTest(package=name):
                tree = self.tree(name)
                patches = self.patch_set(name, self.BAD)
                result = self.run_hook(
                    self.hook(text), tree, patches, BC250_LOCAL_PATCHES="1"
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_nothing_in_ci_turns_the_gate_on(self):
        # The gate is only worth anything while CI never sets it. Everything
        # that runs a build in this repository is searched, rather than the one
        # workflow that happens to build Proton today.
        setters = []
        for path in list((ROOT / ".github").rglob("*.y*ml")) + sorted(
            (ROOT / "scripts").glob("*.sh")
        ):
            if path.name in ("build-proton-tarball.sh", "local-build-inside.sh"):
                continue
            # An assignment, not a mention: the preparation script quotes the
            # variable into the PKGBUILD it generates, which is the hook itself
            # rather than something turning the hook on. `:-` is a default, so
            # ${BC250_LOCAL_PATCHES:-0} does not count either.
            if re.search(r"BC250_LOCAL_PATCHES(?:_DIR)?\s*(?:=|:(?!-))", path.read_text()):
                setters.append(str(path.relative_to(ROOT)))
        self.assertEqual(setters, [])
