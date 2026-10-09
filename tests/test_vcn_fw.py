import hashlib
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "bc250-vcn-fw"
RC = ROOT / "patches" / "linux-cachyos-rc"
STABLE = ROOT / "patches" / "linux-cachyos"

FW_SHA = "bbd15ab65e76178c2918e8224b6ab4ab1711f1b59d935ee131ab188a9712e596"
FW_NAME = "ps5_vcn.bin"


def pkgbuild_sums():
    text = (PKG / "PKGBUILD").read_text()
    sources = re.search(r"source=\((.*?)\)", text, re.S).group(1)
    sums = re.search(r"sha256sums=\((.*?)\)", text, re.S).group(1)
    names = re.findall(r"'([^']+)'", sources)
    digests = re.findall(r"'([^']+)'", sums)
    return dict(zip(names, digests))


class FirmwareFileTests(unittest.TestCase):
    def test_firmware_is_the_pinned_file(self):
        data = (PKG / FW_NAME).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), FW_SHA)

    def test_firmware_has_a_valid_amdgpu_header(self):
        data = (PKG / FW_NAME).read_bytes()
        size_bytes, header_size, major, minor = struct.unpack("<IIHH", data[:12])
        self.assertEqual(size_bytes, len(data))
        self.assertEqual((major, minor), (1, 0))
        self.assertLess(header_size, len(data))

    def test_pkgbuild_pins_every_file_it_ships(self):
        sums = pkgbuild_sums()
        for name in (FW_NAME, "LICENSE.amdgpu"):
            self.assertEqual(sums[name], hashlib.sha256((PKG / name).read_bytes()).hexdigest(), name)

    def test_sha256sums_matches_the_files(self):
        for line in (PKG / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split(None, 1)
            self.assertEqual(hashlib.sha256((PKG / name.strip()).read_bytes()).hexdigest(), digest)

    def test_licence_travels_with_the_firmware(self):
        text = (PKG / "LICENSE.amdgpu").read_text()
        self.assertIn("Advanced Micro Devices", text)
        self.assertIn("Redistributions must reproduce", text)
        self.assertIn("LICENSE.amdgpu", (PKG / "PKGBUILD").read_text())

    def test_package_is_not_in_the_meta_package(self):
        meta = (ROOT / "packages" / "linux-cachyos-bc250-meta" / "PKGBUILD").read_text()
        self.assertNotIn("bc250-vcn-fw", meta)


class KernelPatchTests(unittest.TestCase):
    # The kernel patch is parked in disabled/: on the BC-250 the first register
    # read of the VCN block freezes the machine, so no kernel ships it.
    patch = RC / "disabled" / "bc250-vcn.patch"

    def test_patch_is_parked_and_not_applied(self):
        self.assertTrue(self.patch.is_file())
        self.assertEqual(list(RC.glob("*-bc250-vcn.patch")), [])
        self.assertEqual(list(STABLE.glob("*-bc250-vcn.patch")), [])
        self.assertEqual(list(STABLE.glob("disabled/*bc250-vcn.patch")), [])

    def test_patch_asks_for_the_file_the_package_ships(self):
        self.assertIn(f"amdgpu/{FW_NAME}", self.patch.read_text())
        self.assertTrue((PKG / FW_NAME).is_file())

    def test_bring_up_is_opt_in(self):
        """Should the patch ever be re-enabled, the block must stay off unless
        amdgpu.bc250_vcn=1 is given."""
        text = self.patch.read_text()
        self.assertIn("module_param_named(bc250_vcn, amdgpu_bc250_vcn, int, 0444)", text)
        self.assertIn("adev->pdev->device == 0x13fe && amdgpu_bc250_vcn", text)
        self.assertIn("+int amdgpu_bc250_vcn;", text)  # zero-initialised: default off

    def test_every_change_is_keyed_on_the_bc250_device_id(self):
        added = [l[1:] for l in self.patch.read_text().splitlines()
                 if l.startswith("+") and not l.startswith("+++")]
        body = "\n".join(added)
        self.assertIn("0x13fe", body)
        self.assertNotIn("0x13fb", body)
        self.assertNotIn("X86_PS5", body)


if __name__ == "__main__":
    unittest.main()
