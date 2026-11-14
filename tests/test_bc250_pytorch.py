import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "bc250-pytorch"
ROCM = ROOT / "rocm"
WORKFLOWS = ROOT / ".github" / "workflows"


class WheelWorkflowTests(unittest.TestCase):
    """The ROCm/PyTorch build takes most of a night; it must only run when
    someone starts it, never on a schedule or a push."""

    text = (WORKFLOWS / "rocm-pytorch.yml").read_text()

    def test_started_by_hand_only(self):
        on = re.search(r"^on:\n((?:[ \t].*\n|\n)*)", self.text, re.M).group(1)
        self.assertIn("workflow_dispatch:", on)
        for trigger in ("schedule", "push", "pull_request", "workflow_run"):
            self.assertNotIn(trigger, on)

    def test_runs_capped_on_the_self_hosted_runner(self):
        self.assertIn("- self-hosted", self.text)
        self.assertIn("BC250_BUILD_MEMORY", self.text)
        self.assertIn("rocm/build-rocm.sh all", self.text)

    def test_nightly_workflow_ignores_rocm_sources(self):
        nightly = (WORKFLOWS / "build-release.yml").read_text()
        paths = re.search(r"push:\n(?:.*\n)*?\s+paths:\n((?:\s+- .*\n)+)", nightly).group(1)
        self.assertNotIn("rocm", paths)


class FingerprintTests(unittest.TestCase):
    def fingerprint(self, root):
        return subprocess.run(
            [str(root / "scripts" / "source-fingerprint.sh"), "bc250-pytorch"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_rocm_sources_do_not_rebuild_the_package(self):
        """Only a PKGBUILD pointing at new wheels rebuilds it, not pin or patch edits."""
        with tempfile.TemporaryDirectory() as tmp:
            # Only what the fingerprint reads; the full tree (rebase/) is many GB.
            copy = Path(tmp) / "repo"
            for part in ("scripts", "rocm", "packages/bc250-pytorch"):
                shutil.copytree(ROOT / part, copy / part,
                                ignore=shutil.ignore_patterns("__pycache__"))
            before = self.fingerprint(copy)
            (copy / "rocm" / "pins.env").write_text("PYTORCH_VERSION=9.9.9\n")
            self.assertEqual(self.fingerprint(copy), before)
            pkgbuild = copy / "packages" / "bc250-pytorch" / "PKGBUILD"
            pkgbuild.write_text(pkgbuild.read_text() + "\n# changed\n")
            self.assertNotEqual(self.fingerprint(copy), before)


class PackageTests(unittest.TestCase):
    pkgbuild = (PKG / "PKGBUILD").read_text()

    def test_everything_lives_in_opt(self):
        self.assertIn("dest=\"$pkgdir/opt/bc250-pytorch\"", self.pkgbuild)
        self.assertNotIn("/usr/lib/python", self.pkgbuild)
        self.assertNotRegex(self.pkgbuild, r"depends=\([^)]*python")

    def test_python_download_is_pinned(self):
        sums = re.search(r"sha256sums=\('([0-9a-f]{64})'", self.pkgbuild)
        self.assertIsNotNone(sums)

    def test_bc250_settings_load_with_python(self):
        pth = (PKG / "bc250-rocm-env.pth").read_text()
        self.assertTrue(pth.startswith("import os;"))
        for var in ("HSA_ENABLE_SDMA", "GPU_PINNED_MIN_XFER_SIZE", "TORCH_BLAS_PREFER_HIPBLASLT"):
            self.assertIn(f'"{var}"', pth)
        self.assertIn("setdefault", pth)  # a user's own value wins

    def test_not_in_the_meta_package(self):
        meta = (ROOT / "packages" / "linux-cachyos-bc250-meta" / "PKGBUILD").read_text()
        self.assertNotIn("bc250-pytorch", meta)

    def test_wired_into_the_nightly_build(self):
        self.assertIn("bc250-pytorch)", (ROOT / "scripts" / "ci-build.sh").read_text())
        nightly = (WORKFLOWS / "build-release.yml").read_text()
        self.assertIn('"bc250-pytorch:$BUILD_BC250_PYTORCH"', nightly)
        self.assertIn("bc250-pytorch-info.env", (ROOT / "scripts" / "finalize-repository.sh").read_text())


class UpdatePkgbuildTests(unittest.TestCase):
    def test_writes_wheels_and_versions(self):
        wheels = [
            "rocm-10.3.0.dev0-py3-none-any.whl",
            "rocm_sdk_core-10.3.0.dev0-py3-none-linux_x86_64.whl",
            "torch-2.13.0+devrocm10.3.0.dev0-cp312-cp312-linux_x86_64.whl",
            "numpy-2.5.4-cp312-cp312-manylinux_2_28_x86_64.whl",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "scripts").mkdir()
            shutil.copytree(ROCM, tmp / "rocm")
            shutil.copytree(PKG, tmp / "packages" / "bc250-pytorch")
            wh = tmp / "wheelhouse"
            wh.mkdir()
            sums = {w: hashlib.sha256(w.encode()).hexdigest() for w in wheels}
            (wh / "SHA256SUMS").write_text("".join(f"{d}  {w}\n" for w, d in sums.items()))
            (wh / "BUILD_ID").write_text("0123456789ab\n")
            subprocess.run([str(tmp / "rocm" / "update-pkgbuild.sh"), str(wh)], check=True,
                           capture_output=True, env={**os.environ, "PATH": os.environ["PATH"]})
            text = (tmp / "packages" / "bc250-pytorch" / "PKGBUILD").read_text()
            self.assertIn("_build_id=0123456789ab", text)
            self.assertIn("_torch=2.13.0\n", text)
            self.assertIn("_rocm=10.3.0.dev0\n", text)
            for w, d in sums.items():
                self.assertIn(f"'{w}'", text)
                self.assertIn(f"'{d}'", text)
            # makepkg sees one checksum per source.
            out = subprocess.run(
                ["bash", "-c", "source PKGBUILD; echo ${#source[@]} ${#sha256sums[@]}"],
                cwd=tmp / "packages" / "bc250-pytorch", check=True, capture_output=True, text=True,
            ).stdout.split()
            self.assertEqual(out[0], out[1])
            self.assertEqual(int(out[0]), 5 + len(wheels))


if __name__ == "__main__":
    unittest.main()
