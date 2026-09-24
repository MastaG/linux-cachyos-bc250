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

    The two sets can legitimately have different *lengths* now: each carries
    its own series-specific patches (the gud FORTIFY workaround, needed on 7.3-rc
    but reverted upstream on 7.2), so the same logical patch does not always sit
    at the same number prefix in both directories. Comparison is therefore by content name (the part after the
    `NNNN-`), not by full filename or position.
    """

    STABLE = ROOT / "patches/linux-cachyos"
    RC = ROOT / "patches/linux-cachyos-rc"

    # Patches that legitimately exist in one set only, with the reason.
    STABLE_ONLY = {}
    RC_ONLY = {
        "gud-bound-tv-mode-count.patch": (
            "FORTIFY workaround for a bug upstream reverted on the 7.2 branch "
            "but that is still present on 7.3-rc"
        ),
        "ch7218-vrr-allowlist.patch": (
            "CachyOS 7.2/hdmi already lists the CH7218 in the FreeSync PCON "
            "allowlist; its 7.3 HDMI branch does not, so the RC set adds it"
        ),
        "pcon-vrr-hf-vsdb.patch": (
            "7.3 reads a PCON's VRR range only from the AMD VSDB via DMUB/DMCU "
            "firmware DCN201 lacks; 7.2/hdmi already falls back to the HF-VSDB"
        ),
    }

    @staticmethod
    def content_name(patch_name):
        """Strip the leading `NNNN-` ordering prefix, e.g. '0003-foo.patch' -> 'foo.patch'."""
        return re.sub(r"^\d+-", "", patch_name)

    @classmethod
    def stable_by_content(cls):
        return {cls.content_name(p.name): p for p in cls.STABLE.glob("*.patch")}

    @classmethod
    def rc_by_content(cls):
        return {cls.content_name(p.name): p for p in cls.RC.glob("*.patch")}

    def test_the_sets_differ_only_by_documented_carries(self):
        stable = self.stable_by_content()
        rc = self.rc_by_content()
        self.assertEqual(sorted(set(rc) - set(stable)), sorted(self.RC_ONLY),
                         "a patch is in the RC set but not in the stable one")
        self.assertEqual(sorted(set(stable) - set(rc)), sorted(self.STABLE_ONLY),
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
        stable = self.stable_by_content()
        rc = self.rc_by_content()
        for content_name in sorted(set(stable) & set(rc)):
            with self.subTest(patch=content_name):
                self.assertEqual(self.substance(stable[content_name]),
                                 self.substance(rc[content_name]))

    def test_docs_list_the_patches_that_actually_ship(self):
        """docs/PATCHES.md names the stable set in a fenced block; keep it true.

        It is the only place a reader can see what the kernels carry, and it has
        gone stale before -- it still said "nine patches" after two were added.
        """
        text = (ROOT / "docs/PATCHES.md").read_text()
        marker = "The stable and BORE kernels carry these"
        block = text.split(marker, 1)[1].split("```text", 1)[1].split("```", 1)[0]
        documented = [line.strip() for line in block.splitlines() if line.strip()]
        shipped = sorted(p.name for p in self.STABLE.glob("*.patch"))
        self.assertEqual(documented, shipped)
        self.assertIn(self.number_word(len(shipped)) + " patches", text)
        self.assertIn(self.number_word(len(shipped)) + " BC-250 patches", text)

    def test_hdmi21_patches_stay_switchable_and_default_on(self):
        """The two DCN201 display patches must stay behind amdgpu.bc250_hdmi21,
        and that switch must default to ON.

        The gist they come from has no switch at all, so a careless re-import
        would drop it: the removed line `.num_dsc = 0,` and an unguarded
        `dp_hdmi21_pcon_support = true` are the two signatures of that.

        The default is pinned because it decides what every user gets. It was
        briefly flipped off while a display blackout was suspected to be a DSC
        problem; it was then reproduced on hardware with bc250_hdmi21=0 on an
        uncompressed link, so DSC was exonerated and the default went back on.
        Changing it is a deliberate act that should fail this test first.

        Looked up by content name, not number prefix: the two sets number this
        pair differently (stable and RC have diverged in length elsewhere).
        """
        for patch_set, by_content in (
            (self.STABLE, self.stable_by_content()),
            (self.RC, self.rc_by_content()),
        ):
            for content_name in ("dcn201-hdmi21-pcon.patch", "dcn201-enable-dsc.patch"):
                text = by_content[content_name].read_text()
                with self.subTest(patch=f"{patch_set.name}/{content_name}"):
                    self.assertIn("dc->config.bc250_hdmi21", text)
                    self.assertNotIn("-\t\t.num_dsc = 0,", text)
            pcon = by_content["dcn201-hdmi21-pcon.patch"].read_text()
            self.assertIn("+\tif (dc->config.bc250_hdmi21)\n"
                          "+\t\tdc->caps.dp_hdmi21_pcon_support = true;", pcon)
            self.assertIn('module_param_named(bc250_hdmi21, amdgpu_bc250_hdmi21, int, 0444);', pcon)
            self.assertIn("+int amdgpu_bc250_hdmi21 = 1;\n", pcon,
                          "the switch must default to on")
            self.assertIn("(0 = disabled, 1 = enabled (default))", pcon,
                          "the parm description must say which way it defaults")

    def test_relink_defaults_are_pinned(self):
        """The relink patch's four defaults decide what every user gets.

        cs_relink_at_boot is the one to watch: it fires a forced re-detect on
        the first bring-up of every boot, on every board with a converter, and
        it is ON. It exists because a machine can boot with the converter
        already dropped and the rest of the mechanism cannot see a blank that
        predates the driver. Whether a second detect clears that state is not
        established -- DC already runs a full link_detect about three seconds
        earlier -- so if boot regressions appear, this is the first thing to
        turn off.

        Changing any of these should be a deliberate act that fails here first.
        """
        for patch_set, by_content in (
            (self.STABLE, self.stable_by_content()),
            (self.RC, self.rc_by_content()),
        ):
            text = by_content["cs-relink-after-long-blank.patch"].read_text()
            added = "\n".join(l[1:] for l in text.splitlines()
                               if l.startswith("+") and not l.startswith("+++"))
            with self.subTest(patch=patch_set.name):
                # 3000 sits below every observed failure (>= 4.44 s) and above
                # every observed healthy handover (<= 2.1 s measured in the
                # field). 1000 fired on healthy 1.8 s and 2.1 s switches, and a
                # re-detect costs a real modeset, so firing needlessly is worse
                # than not firing.
                self.assertIn("static uint cs_relink_ms = 3000;", added)
                self.assertNotIn("static uint cs_relink_ms = 1000;", added)
                self.assertIn("static uint cs_relink_delay_ms = 250;", added)
                self.assertIn("static uint cs_relink_cooldown_ms = 10000;", added)
                self.assertIn("static bool cs_relink_at_boot;", added,
                              "the boot re-detect must default to OFF")
                self.assertNotIn("static bool cs_relink_at_boot = true;", added)
                # one shot: it must clear its own pending flag
                self.assertIn("cs_relink_boot_pending = false;", added)
                # and it must never fire while the mechanism itself is off
                self.assertIn("if (!cs_relink_ms || cs_relink_running)", added)
                # the cooldown is the loop breaker and must stay stamped on
                # every exit path, including the failures
                self.assertIn("cs_relink_last_run = jiffies ? jiffies : 1;", added)
                # ...but the speculative boot shot must NOT start that clock,
                # or the first genuine long blank of the boot is refused --
                # and on a normal startup that blank lands inside the cooldown
                self.assertIn("if (!cs_relink_is_boot_run)\n\t\tcs_relink_last_run", added,
                              "the boot shot must not burn the cooldown")
                # the boot shot must expire, or a board powered up before its
                # TV spends it hours later on an unrelated hotplug
                self.assertIn("CS_RELINK_BOOT_WINDOW_MS", added)
                self.assertIn("time_after(jiffies, (unsigned long)INITIAL_JIFFIES +", added)

    def test_ch7218_quirk_is_opt_in_and_every_change_is_behind_the_switch(self):
        """The CH7218 adapter quirk must default OFF and be fully gated.

        Working CH7218 adapters are indistinguishable from broken ones in the
        DPCD, so a quirk that applied itself would override correct information
        reported by a healthy adapter. The requirement is stronger than "has a
        switch": with amdgpu.bc250_ch7218_quirk unset, *nothing* the patch adds
        may take effect.

        The version this was adapted from failed exactly that. It gated only
        its capability helper on dp_hdmi21_pcon_support -- which defaults on --
        and left the dongle_type reclassification, the DSC_SUPPORT bit and a
        FreeSync allowlist entry with no gate at all.

        So this pins three things: the default is off, every function that
        mutates link state begins by consulting the switch, and no static
        table is edited (a table entry cannot be gated at all).

        The DSC_SUPPORT restore is deliberately NOT here any more -- it lives
        in ch7218-dsc-restore.patch and is unconditional, for the reasons that
        patch's own test records.
        """
        for patch_set, by_content in (
            (self.STABLE, self.stable_by_content()),
            (self.RC, self.rc_by_content()),
        ):
            text = by_content["ch7218-pcon-quirk.patch"].read_text()
            added = [line[1:] for line in text.splitlines()
                     if line.startswith("+") and not line.startswith("+++")]
            body = "\n".join(added)
            with self.subTest(patch=patch_set.name):
                self.assertIn("int amdgpu_bc250_ch7218_quirk;", body,
                              "the switch must default to off, i.e. no ' = 1'")
                self.assertNotIn("int amdgpu_bc250_ch7218_quirk = 1;", body)
                self.assertIn("module_param_named(bc250_ch7218_quirk, "
                              "amdgpu_bc250_ch7218_quirk, int, 0444);", body)
                self.assertIn("(0 = disabled (default), 1 = enabled)", body,
                              "the parm description must say which way it defaults")

                # every mutating helper consults the switch before touching
                # anything; bc250_ch7218_quirk_wanted() is that single gate
                # the switch is consulted in the gate the mutating helper calls
                self.assertIn("static bool bc250_ch7218_quirk_wanted(const struct dc_link *link)",
                              body)
                self.assertIn("return bc250_ch7218_detected(link) &&\n\t       link->dc->config.bc250_ch7218_quirk;", body)
                helper = "bc250_ch7218_force_converter_identity"
                defn = body.split(f"static void {helper}(struct dc_link *link)\n{{", 1)
                self.assertEqual(len(defn), 2, f"{helper} must be defined")
                self.assertIn("if (!bc250_ch7218_quirk_wanted(link))\n\t\treturn;",
                              defn[1][:400],
                              f"{helper} must return before mutating anything")
                # the DSC restore moved to its own, unconditional patch: this
                # one must not carry it back in, gated or otherwise
                self.assertNotIn("bc250_ch7218_restore_dsc_support", body)
                self.assertNotIn("DSC_SUPPORT = true", body)

                # a static table entry cannot be switched off at runtime, so
                # the quirk must not add one
                self.assertNotIn("dm_freesync_pcon_whitelist", body)
                self.assertNotIn("dm_helpers_is_vrr_pcon_allowlist", body)
                self.assertNotIn("DP_BRANCH_DEVICE_ID_2B02F0", body,
                                 "7.2 already defines this and 7.3-rc does not; "
                                 "use the file-local constant instead")

    def test_ch7218_dsc_restore_is_unconditional_but_cannot_lie(self):
        """The DSC restore runs without a parameter, so its gate is the proof.

        It is split out of the opt-in quirk precisely because it cannot
        override a correct report: it must return when DSC_SUPPORT is already
        set, and return when the capability block is empty. What is left is the
        one state that cannot describe real hardware -- a decoder that reports
        its revision, slices and bits-per-pixel while claiming not to exist.
        If a future edit gates it on the module parameter, the split has been
        undone; if an edit drops either early return, it starts inventing a
        decoder on adapters that never had one.
        """
        for patch_set, by_content in (
            (self.STABLE, self.stable_by_content()),
            (self.RC, self.rc_by_content()),
        ):
            with self.subTest(patch_set=patch_set.name):
                text = by_content["ch7218-dsc-restore.patch"].read_text()
                added = [line[1:] for line in text.splitlines()
                         if line.startswith("+") and not line.startswith("+++")]
                body = "\n".join(added)
                defn = body.split(
                    "static void bc250_ch7218_restore_dsc_support(struct dc_link *link)\n{", 1)
                self.assertEqual(len(defn), 2, "the helper must be defined here")
                helper = defn[1]
                # identity only -- never the module parameter
                self.assertIn("if (!bc250_ch7218_detected(link))\n\t\treturn;", helper[:400])
                self.assertNotIn("bc250_ch7218_quirk_wanted", body)
                self.assertNotIn("config.bc250_ch7218_quirk", body)
                # and it still refuses the two cases where it would be lying
                self.assertIn(
                    "if (dsc_caps->dsc_basic_caps.fields.dsc_support.DSC_SUPPORT)\n\t\treturn;",
                    helper)
                self.assertIn("DP_DSC_REV - DP_DSC_SUPPORT", helper)
                self.assertIn("DP_DSC_SLICE_CAP_1 - DP_DSC_SUPPORT", helper)
                self.assertIn("DP_DSC_MAX_BITS_PER_PIXEL_LOW - DP_DSC_SUPPORT", helper)
                # no static tables, and it adds no module parameter of its own
                self.assertNotIn("module_param_named", body)
                self.assertNotIn("dm_freesync_pcon_whitelist", body)
                # it is in both sets, so it is not an RC-only carry
                self.assertIn("ch7218-dsc-restore.patch", self.stable_by_content())
                self.assertIn("ch7218-dsc-restore.patch", self.rc_by_content())

    def test_pcon_force_dsc_is_opt_in_and_only_fills_an_empty_block(self):
        """The force-DSC experiment must default OFF and touch only silence.

        It invents a DSC decoder for an adapter that reports none. That is a
        probe of the adapter's firmware, so it must never reach an adapter
        that said anything about DSC (a CH7218 with a cleared bit belongs to
        the quirk, not to this), must not edit any static table, and must
        return before mutating anything unless the parameter is set.
        """
        for patch_set, by_content in (
            (self.STABLE, self.stable_by_content()),
            (self.RC, self.rc_by_content()),
        ):
            with self.subTest(patch_set=patch_set.name):
                text = by_content["pcon-force-dsc.patch"].read_text()
                added = [line[1:] for line in text.splitlines()
                         if line.startswith("+") and not line.startswith("+++")]
                body = "\n".join(added)
                # default off: a bare int definition, no initialiser
                self.assertIn("int amdgpu_bc250_pcon_force_dsc;", body)
                self.assertIn("module_param_named(bc250_pcon_force_dsc, amdgpu_bc250_pcon_force_dsc, int, 0444);", body)
                self.assertIn("init_data.flags.bc250_pcon_force_dsc = (amdgpu_bc250_pcon_force_dsc != 0);", body)
                # the helper consults the switch before it touches anything
                defn = body.split("static void bc250_pcon_force_dsc(struct dc_link *link)\n{", 1)
                self.assertEqual(len(defn), 2)
                head = defn[1][:400]
                self.assertIn("if (!link->dc->config.bc250_pcon_force_dsc ||", head)
                self.assertLess(head.index("config.bc250_pcon_force_dsc"), head.index("memcpy") if "memcpy" in head else 10**6)
                # only an all-zero block is filled in
                self.assertIn("if (dsc_caps->dsc_basic_caps.raw[i])\n\t\t\treturn;", defn[1])
                self.assertIn("dongle_type != DISPLAY_DONGLE_DP_HDMI_CONVERTER", defn[1])
                # template: DSC_SUPPORT set, passthrough clear, DSC 1.2
                self.assertIn("0x01, 0x21, 0x00, 0x07, 0x3b, 0x04, 0x01, 0xc0,", body)
                # it is called right after the quirk's restore, inside the DC_OK branch
                self.assertIn("bc250_pcon_force_dsc(link);", body)
                # no static tables
                self.assertNotIn("dm_freesync_pcon_whitelist", body)
                self.assertNotIn("DP_BRANCH_DEVICE_ID_", body)

    def test_rc_pcon_vrr_fallback_keeps_the_dpcd_gates(self):
        """The HF-VSDB fallback fills a range; it must not loosen the gates.

        It exists because the firmware EDID parser cannot run on DCN201. It
        has to stay inside the allowlisted-PCON block (so the Adaptive-Sync
        SDP, Ignore-MSA and allowlist checks still decide), fire only when the
        AMD VSDB path produced nothing, and touch one file.
        """
        touched, changed = self.substance(self.rc_by_content()["pcon-vrr-hf-vsdb.patch"])
        self.assertEqual([t.split(" b/")[1] for t in touched],
                         ["drivers/gpu/drm/amd/display/amdgpu_dm/amdgpu_dm_connector.c"])
        body = "\n".join(l[1:] for l in changed if l.startswith("+"))
        self.assertIn("if (!freesync_capable && connector->display_info.hdmi.vrr_cap.supported) {", body)
        self.assertIn("amdgpu_dm_connector->pack_sdp_v1_3 = true;", body)
        self.assertIn("amdgpu_dm_connector->as_type = as_type;", body)
        self.assertNotIn("dm_get_adaptive_sync_support_type", body)
        self.assertNotIn("dm_freesync_pcon_whitelist", body)
        self.assertFalse([l for l in changed if l.startswith("-")], "must only add")
        # one hunk, inside amdgpu_dm_update_freesync_caps, and it reuses the
        # as_type the gate function computed rather than inventing one
        text = self.rc_by_content()["pcon-vrr-hf-vsdb.patch"].read_text()
        hunks = [l for l in text.splitlines() if l.startswith("@@")]
        self.assertEqual(len(hunks), 1)
        self.assertIn("amdgpu_dm_update_freesync_caps", hunks[0])
        self.assertNotIn("as_type = FREESYNC_TYPE", body)

    def test_rc_vrr_allowlist_patch_adds_exactly_one_entry(self):
        """The RC-only allowlist patch is one table entry and its define.

        It exists because CachyOS's 7.3 HDMI branch dropped the CH7218 from
        dm_freesync_pcon_whitelist that its 7.2 branch carries. It must stay
        that small: anything else belongs in the gated quirk, and when the RC
        source gains the ID itself the duplicate define must make the build
        fail rather than be papered over.
        """
        text = self.rc_by_content()["ch7218-vrr-allowlist.patch"].read_text()
        touched, changed = self.substance(self.rc_by_content()["ch7218-vrr-allowlist.patch"])
        self.assertEqual(
            [t.split(" b/")[1] for t in touched],
            ["drivers/gpu/drm/amd/display/amdgpu_dm/amdgpu_dm_helpers.c",
             "drivers/gpu/drm/amd/display/include/ddc_service_types.h"])
        self.assertEqual(changed, [
            "+\tDP_BRANCH_DEVICE_ID_2B02F0,",
            "+#define DP_BRANCH_DEVICE_ID_2B02F0 0x2B02F0 /* Chrontel CH7218 */",
        ])
        # and the gated quirk must not have quietly absorbed it
        quirk = self.rc_by_content()["ch7218-pcon-quirk.patch"].read_text()
        self.assertNotIn("dm_freesync_pcon_whitelist", quirk)

    @staticmethod
    def number_word(n):
        words = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
                 13: "thirteen", 14: "fourteen", 15: "fifteen",
                 16: "sixteen", 17: "seventeen", 18: "eighteen",
                 19: "nineteen", 20: "twenty"}
        return words[n]


class ReadmePackageTableTests(unittest.TestCase):
    """The README's "What you get" table must only name packages this repo builds.

    It listed `nct6687d-dkms` -- a package that has never existed here; the
    driver is compiled into the kernel packages -- and a reader tried to
    install it. Every backticked name in that table has to map to a build
    script or a kernel family.
    """

    def test_every_package_in_the_table_is_built_here(self):
        text = (ROOT / "README.md").read_text()
        start = text.index("## What you get")
        end = text.index("\n## ", start + 1)
        rows = [l for l in text[start:end].splitlines() if l.startswith("| `")]
        self.assertGreater(len(rows), 5)
        built = {p.name[len("build-"):-len("-package.sh")]
                 for p in (ROOT / "scripts").glob("build-*-package.sh")}
        # scripts/build-package.sh builds the three kernel families; mesa and
        # mesa-git each produce a lib32 split alongside.
        built |= {"linux-cachyos-bc250", "lib32-mesa-git"}
        for row in rows:
            for name in re.findall(r"`([^`]+)`", row.split("|")[1]):
                with self.subTest(package=name):
                    self.assertIn(name, built)


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
                # Older bridges are kept selectable so their performance can be
                # measured against the default. Every package must offer the
                # same set, and the default must stay the newest.
                self.assertIn("--ffx-sdk-alt fsr411rc9", text)
                self.assertIn("--ffx-sdk-alt fsr411rc10", text)
                for archive in ("bc250-fsr4-dll-4.0.0-rc9.tar.xz",
                                "bc250-fsr4-dll-4.0.0-rc10.zip",
                                "bc250-fsr4-dll-4.0.0-rc11.zip"):
                    self.assertIn(archive, text)
                # The default alias resolves to RC11, not to one of the older
                # ones -- fsr411f is what --ffx-sdk-default names.
                self.assertIn('fsr411f', text.split("--ffx-sdk-default", 1)[1][:16])

    def test_the_metapackage_pulls_in_all_three(self):
        pkgbuild = (ROOT / "packages/linux-cachyos-bc250-meta/PKGBUILD").read_text()
        for package in ("protonge-latest-bc250", "proton-cachyos-native-bc250",
                        "proton-cachyos-slr-bc250"):
            self.assertIn(f"'{package}'", pkgbuild)

    def test_dependency_installer_never_lets_awk_close_the_pipe_on_bsdtar(self):
        """install-proton-build-deps.sh reads package metadata through
        `bsdtar -xOf ... | awk`. An awk that `exit`s on its first match closes
        the pipe while bsdtar may still be writing; bsdtar then exits nonzero
        on EPIPE, and under the script's `set -Eeuo pipefail` the assignment
        it feeds fails silently. It depends on how bsdtar chunks a given desc
        in a given database build, so it worked for weeks and then took
        proton-cachyos-native-bc250 down with no error line. awk has to read
        to end of stream.
        """
        text = (ROOT / "scripts/install-proton-build-deps.sh").read_text()
        for line in text.splitlines():
            if "awk" in line and "bsdtar" in text:
                self.assertNotIn("exit }", line, line)
        self.assertIn("!done", text)

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


class RetiredPackageTests(unittest.TestCase):
    """A package this repository stops shipping must also leave the published database.

    out/repo is seeded from the previous release on every run and the database
    is rebuilt from whatever *.pkg.tar.zst is there, so deleting a PKGBUILD on
    its own leaves the last build published forever. aic8800d80-dkms was
    published at pkgrel 7, above the AUR package's 6, so left in place it would
    shadow the AUR package -- correct since upstream merged our fix -- for
    everyone with this repository enabled. RETIRED_PACKAGES in
    scripts/retired-packages.sh is what removes it, and it has to run in both
    database builders, before either enumerates the package set.

    Every assertion here is anchored to a live, uncommented line: a
    commented-out call, a commented-out list entry or a dropped `source` line
    with its shellcheck directive left behind all used to pass a looser
    version of these tests.
    """

    RETIRED = ROOT / "scripts/retired-packages.sh"
    BUILDERS = ("scripts/update-repo-db.sh", "scripts/finalize-repository.sh")

    def test_aic8800d80_dkms_is_retired_and_gone_from_the_source_tree(self):
        text = self.RETIRED.read_text()
        array = text[text.index("RETIRED_PACKAGES=("):]
        array = array[:array.index(")")]
        self.assertRegex(array, r"(?m)^\s*aic8800d80-dkms\s*$",
                         "the entry must be a live line inside the array, not a comment")
        self.assertIn("retire_packages() {", text)
        self.assertFalse((ROOT / "packages/aic8800d80-dkms").exists())
        self.assertFalse((ROOT / "scripts/build-aic8800d80-dkms-package.sh").exists())
        for path in ("scripts/ci-build.sh", "scripts/source-fingerprint.sh",
                     ".github/workflows/build-release.yml"):
            with self.subTest(path=path):
                self.assertNotIn("aic8800", (ROOT / path).read_text().lower())
        # finalize and update-repo-db legitimately mention the package in prose
        # (the release notes), so scan them for the env/metadata token instead:
        # one surviving `: "${AIC8800D80_DKMS_FINGERPRINT:?...}"` would fail
        # every publish while a lowercase scan of the other files stays green.
        for path in self.BUILDERS:
            with self.subTest(path=path):
                self.assertNotIn("AIC8800D80_DKMS", (ROOT / path).read_text())
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("| `aic8800d80-dkms` |", readme)
        self.assertIn("makepkg -si", readme)
        # never tell people to remove the driver before its replacement exists
        self.assertNotIn("pacman -Rns aic8800d80-dkms", readme)
        self.assertNotIn("pacman -Rns aic8800d80-dkms", (ROOT / "scripts/finalize-repository.sh").read_text())

    def test_retirement_runs_in_both_database_builders_before_enumeration(self):
        for path in self.BUILDERS:
            text = (ROOT / path).read_text()
            with self.subTest(path=path):
                src = re.search(r'(?m)^source "\$\{ROOT_DIR\}/scripts/retired-packages\.sh"$', text)
                self.assertIsNotNone(src, "a live source line, not just the shellcheck directive")
                call = re.search(r'(?m)^retire_packages "\$OUT_DIR"$', text)
                self.assertIsNotNone(call, "a live, uncommented call")
                self.assertLess(src.start(), call.start())
                self.assertLess(call.start(), text.index("packages=(./*.pkg.tar.zst)"),
                                "retire before the package set is enumerated")

    def test_retirement_removes_the_sidecar_assets_too(self):
        # The delta publisher deletes whatever left out/repo, so the info.env,
        # PKGBUILD and SRCINFO copies have to go with the package or they stay
        # on the release forever -- and the rm has to be the real one.
        text = self.RETIRED.read_text()
        fn = text[text.index("retire_packages() {"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertRegex(fn, r'(?m)^\s*remove_pkgbase_from_repo "\$out_dir" "\$pkgbase"$')
        self.assertRegex(fn, r'(?m)^\s*rm -f -- "\$out_dir/\$sidecar"$')
        for sidecar in ('"$pkgbase-info.env"', '"$pkgbase-PKGBUILD"', '"$pkgbase.SRCINFO"'):
            self.assertIn(sidecar, fn)

    def test_the_retired_list_is_fingerprinted_by_the_metapackage_only(self):
        # It has to be hashed somewhere, or a retirement never triggers a run;
        # it must not be hashed into a kernel/Mesa/Proton fingerprint, or a
        # one-package retirement rebuilds everything. The metapackage is the
        # cheapest package there is.
        text = (ROOT / "scripts/source-fingerprint.sh").read_text()
        self.assertEqual(text.count('hash_files "$ROOT_DIR/scripts/retired-packages.sh"'), 1)
        meta = text[text.index("    linux-cachyos-bc250-meta)\n"):]
        meta = meta[:meta.index(";;")]
        self.assertIn("scripts/retired-packages.sh", meta)
        # and repo-package-helpers.sh, which every component hashes, is untouched
        helpers = (ROOT / "scripts/repo-package-helpers.sh").read_text()
        self.assertNotIn("RETIRED_PACKAGES", helpers)
        self.assertNotIn("retire_packages", helpers)


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
