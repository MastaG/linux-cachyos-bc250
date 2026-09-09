#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject production packages that omit the compiled FSR4 v4 driver path.

This checks the actual packaged ELF before repository promotion, not the list
of patch assets uploaded alongside it. It is a build-coverage check; numerical
correctness and performance still require separate GPU qualification.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PACKAGES = {
    "vulkan-radeon": ("usr/lib/libvulkan_radeon.so", 2, 62),
    "lib32-vulkan-radeon": ("usr/lib32/libvulkan_radeon.so", 1, 3),
    "mesa-git": ("usr/lib/libvulkan_radeon.so", 2, 62),
    "lib32-mesa-git": ("usr/lib32/libvulkan_radeon.so", 1, 3),
}
MARKERS = (
    "bc250-fsr4-integrated-v3",
    "BC250_FSR4_DISABLE",
    "BC250_FSR4_IMAGEPREP",
    "BC250_FSR4_TEXTURE",
    "BC250_FSR4_RESOLUTION_VARIANTS",
    "BC250_FSR4_RESOLUTION_GUARD",
)


def verify_driver(data, elf_class, machine):
    if (
        len(data) < 64
        or data[:4] != b"\x7fELF"
        or data[4] != elf_class
        or int.from_bytes(data[16:18], "little") != 3
        or data[5] != 1
        or int.from_bytes(data[18:20], "little") != machine
    ):
        raise RuntimeError("RADV is not an ELF for the expected x86 architecture")
    missing = [marker for marker in MARKERS if marker.encode() + b"\0" not in data]
    if missing:
        raise RuntimeError(
            "Packaged RADV is missing FSR4 v4 code: " + ", ".join(missing)
        )
    return hashlib.sha256(data).hexdigest()


def member(package, name):
    return subprocess.check_output(
        ["bsdtar", "-xOf", str(package), name], stderr=subprocess.PIPE
    )


def verify_packages(paths, expected):
    remaining = set(expected)
    rows = []
    for package in paths:
        metadata = member(package, ".PKGINFO").decode("utf-8")
        names = [
            line.partition(" = ")[2]
            for line in metadata.splitlines()
            if line.startswith("pkgname = ")
        ]
        if len(names) != 1:
            raise RuntimeError("Expected one pkgname in " + str(package))
        name = names[0]
        if name not in expected:
            continue
        if name not in remaining:
            raise RuntimeError("Duplicate production driver package: " + name)
        path, elf_class, machine = PACKAGES[name]
        sha256 = verify_driver(member(package, path), elf_class, machine)
        remaining.remove(name)
        rows.append(
            {
                "package": name,
                "archive": package.name,
                "library": path,
                "sha256": sha256,
            }
        )
    if remaining:
        raise RuntimeError(
            "Missing production driver package: " + ", ".join(sorted(remaining))
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", action="append", choices=PACKAGES, required=True)
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps(verify_packages(args.packages, set(args.expect)), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit("ERROR: " + str(error))
