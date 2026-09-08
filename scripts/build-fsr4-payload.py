#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble the pinned FSR4 payload and the manifest that describes it.

Both FSR4 Proton packages ship the same thing: a local `upscaler-manifest.json`
plus the artifacts it names, so protonfixes installs a verified payload from
disk instead of downloading one at game launch. The manifest cannot be a static
file in the repository -- `patches/0001-pinned-upscaler-manifest.patch` requires
a per-file SHA256 for every non-.ini entry in an OptiScaler build, so it has to
be computed from the archive that was actually selected.

Run with the already-downloaded, already-checksummed inputs; makepkg's source=()
verification is what proves they are the pinned ones, so nothing is fetched here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tar_tree(root: Path, output: Path) -> None:
    """Write a deterministic .tar.xz of `root`.

    Determinism is not cosmetic here: the archive's own SHA256 goes into the
    manifest and into its filename, and the CI rebuild fingerprints compare
    package inputs across machines. Timestamps or uids leaking in would make an
    identical payload hash differently on every build.
    """

    def metadata(member: tarfile.TarInfo) -> tarfile.TarInfo:
        member.uid = member.gid = member.mtime = 0
        member.uname = member.gname = ""
        member.pax_headers = {}
        member.mode = 0o755 if member.isdir() else 0o644
        return member

    with output.open("wb") as raw:
        # 9|EXTREME over the default: measured on this payload it is 77 MB
        # against 91 MB for eleven more seconds of CPU, and the package rebuilds
        # only when its fingerprint changes while every user downloads the result.
        with lzma.LZMAFile(raw, "w", preset=9 | lzma.PRESET_EXTREME) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(root.rglob("*")):
                    archive.add(
                        path,
                        arcname=str(path.relative_to(root)),
                        recursive=False,
                        filter=metadata,
                    )


def optiscaler_artifact(args, staging: Path) -> tuple[Path, dict]:
    """Lay out the OptiScaler tree as it must land in the prefix, and describe it."""
    extracted = staging / "optiscaler"
    extracted.mkdir()
    # bsdtar reads 7z and ships with libarchive, which makepkg already needs, so
    # this costs no extra makedepends.
    subprocess.run(
        ["bsdtar", "-xf", str(args.optiscaler), "--no-same-owner",
         "--no-same-permissions", "-C", str(extracted)],
        check=True,
    )
    if any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in extracted.rglob("*")):
        raise RuntimeError("OptiScaler archive contains a link or special file")

    dll = extracted / "OptiScaler.dll"
    # WINMM is imported by Vulkan games that never touch DXGI, so it is the one
    # proxy that gets loaded either way. Proton redirects it from its own prefix;
    # no file is ever written into a game's directory.
    dll.rename(extracted / args.proxy)

    # Older NGX inputs look for an NVIDIA-signed library beside the proxy before
    # they will call the API OptiScaler intercepts. This is the pinned, unmodified
    # 310.7.0 DLL used purely as that surrogate -- never a DLL taken from a game.
    shutil.copy2(args.dlss, extracted / "nvngx_dlss.dll")
    shutil.copy2(args.licenses / "NVIDIA-DLSS.txt", extracted / "Licenses/NVIDIA-DLSS.txt")

    # OptiScaler bundles a 4.1.1 FidelityFX SDK, which would shadow the equally
    # versioned provider that our RADV actually drives. The older 4.0.2 bridge
    # lets the pinned 4.1.1 provider win.
    shutil.copy2(args.ffx_sdk, extracted / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll")
    shutil.copy2(
        args.licenses / "FidelityFX-SDK-4.0.2.txt",
        extracted / "Licenses/FidelityFX-SDK-4.0.2.txt",
    )

    plugins = extracted / "OptiScaler/plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.optipatcher, plugins / "OptiPatcher.asi")

    # Upstream's interactive Windows/Linux deployment helpers. Nothing in the
    # launch path runs them, and shipping them into a prefix invites someone to.
    for path in extracted.rglob("*"):
        if path.suffix in (".bat", ".sh"):
            path.unlink()

    files = {str(p.relative_to(extracted)): p for p in sorted(extracted.rglob("*")) if p.is_file()}
    for path in files.values():
        path.chmod(0o644)

    output = staging / "optiscaler.tar.xz"
    tar_tree(extracted, output)
    archive_sha256 = digest(output)
    return output, {
        "version": args.optiscaler_version,
        "is_dev_file": False,
        "download_url": "artifacts/optiscaler-" + archive_sha256 + ".tar.xz",
        "zip_sha256_hash": archive_sha256,
        # .ini files are excluded: protonfixes rewrites OptiScaler.ini in the
        # prefix from PROTON_OPTISCALER_CONFIG, so its content cannot be pinned.
        "sha256_hash": {
            name: digest(path) for name, path in files.items() if not name.endswith(".ini")
        },
        "md5_hash": {
            name: "" if name.endswith(".ini") else hashlib.md5(path.read_bytes()).hexdigest()
            for name, path in files.items()
        },
    }


def provider_artifact(args, destination: Path) -> dict:
    """Copy the compressed FSR4 provider in and describe both of its forms."""
    payload = lzma.decompress(args.provider.read_bytes())
    archive_sha256 = digest(args.provider)
    name = "provider-" + archive_sha256 + ".dll.xz"
    shutil.copy2(args.provider, destination / name)
    return {
        "version": args.provider_version,
        "is_dev_file": False,
        "download_url": "artifacts/" + name,
        "zip_sha256_hash": archive_sha256,
        "sha256_hash": hashlib.sha256(payload).hexdigest(),
        "md5_hash": hashlib.md5(payload).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--optiscaler", type=Path, required=True, help="OptiScaler .7z")
    ap.add_argument("--optiscaler-version", required=True,
                    help="version string protonfixes must ask for by name")
    ap.add_argument("--optipatcher", type=Path, required=True, help="OptiPatcher .asi")
    ap.add_argument("--provider", type=Path, required=True, help="amdxcffx64 .xz")
    ap.add_argument("--provider-version", default="4.1.1")
    ap.add_argument("--ffx-sdk", type=Path, required=True,
                    help="FidelityFX SDK amd_fidelityfx_upscaler_dx12.dll")
    ap.add_argument("--dlss", type=Path, required=True, help="NVIDIA nvngx_dlss.dll surrogate")
    ap.add_argument("--licenses", type=Path, required=True, help="directory of license notices")
    ap.add_argument("--preset", type=Path, required=True, help="optiscaler-preset.json")
    ap.add_argument("--proxy", default="winmm.dll")
    # Where the wrapper will find things, relative to the Steam tool directory.
    # protonge-latest nests GE under ge/; proton-cachyos-native is the tree itself.
    ap.add_argument("--manifest-rel", required=True,
                    help="path from the tool root to upscaler-manifest.json")
    ap.add_argument("--proton-rel", required=True,
                    help="path from the tool root to the real proton launcher")
    ap.add_argument("--output", type=Path, required=True,
                    help="GE tree the manifest and artifacts are written into")
    ap.add_argument("--config", type=Path, required=True,
                    help="where to write the launch wrapper's config")
    args = ap.parse_args()

    artifacts = args.output / "artifacts"
    artifacts.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix=".payload-") as temporary:
        staging = Path(temporary)
        archive, optiscaler = optiscaler_artifact(args, staging)
        shutil.copy2(archive, artifacts / Path(optiscaler["download_url"]).name)
    provider = provider_artifact(args, artifacts)

    manifest = {"optiscaler": [optiscaler], "fsr_40_drv": [provider]}
    (args.output / "upscaler-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    preset = json.loads(args.preset.read_text())
    preset = preset["preset"] if "preset" in preset else preset
    # The wrapper asks protonfixes for these versions by name, and the manifest
    # answers with exactly one entry each. Writing both from here is what keeps
    # them from drifting apart.
    args.config.write_text(
        json.dumps(
            {
                "schema": 1,
                "optiscaler_version": args.optiscaler_version,
                "provider_version": args.provider_version,
                "proxy": args.proxy,
                "manifest": args.manifest_rel,
                "proton": args.proton_rel,
                "preset": preset,
            },
            indent=2,
        )
        + "\n"
    )

    # Only the files this script created: --output is the GE tree, and a blanket
    # chmod over it would strip the executable bit from proton and wine.
    for path in [args.output / "upscaler-manifest.json", args.config, *artifacts.iterdir()]:
        path.chmod(0o644)
    print("==> pinned OptiScaler " + args.optiscaler_version
          + " (" + str(len(optiscaler["sha256_hash"])) + " verified files)")
    print("==> pinned FSR4 provider " + args.provider_version)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit("ERROR: " + str(error))
