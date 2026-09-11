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
import configparser
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


def validate_preset(preset_path: Path, ini_path: Path) -> dict:
    """Match the launcher's ConfigParser and key/value syntax before packaging."""
    preset = json.loads(preset_path.read_text())
    preset = preset["preset"] if isinstance(preset, dict) and "preset" in preset else preset
    if not isinstance(preset, dict) or not preset:
        raise RuntimeError("OptiScaler preset must be a non-empty object")
    parser = configparser.ConfigParser()
    # Use the same strict parser and encoding as protonfixes, including option
    # case folding. A candidate selector is not sufficient: the normal build
    # takes the mirrored fallback without running that candidate check.
    with ini_path.open() as stream:
        parser.read_file(stream)
    for key, value in preset.items():
        if (not isinstance(value, str) or key.count('.') != 1
                or any(c in key + value for c in ';=\r\n')):
            raise RuntimeError("Malformed OptiScaler preset entry: " + key)
        section, option = key.split('.')
        if section not in parser or option not in parser[section]:
            raise RuntimeError("Unknown OptiScaler preset option: " + key)
        parser[section][option] = value
    return preset


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


def bridge_from(source: Path, staging: Path, name: str) -> tuple[Path, Path | None]:
    """Return the FidelityFX bridge DLL for a variant, and its notices if any.

    A variant is given either as a bare .dll or as the release archive it was
    published in. Taking the archive is preferable where upstream offers one:
    it is far smaller over the wire (RC8 is 10 MB packed against a 112 MB DLL)
    and it carries the licence notices whose retention that release asks for.
    """
    if source.suffix == ".dll":
        return source, None

    unpacked = staging / ("bridge-" + name)
    unpacked.mkdir(parents=True)
    subprocess.run(
        ["bsdtar", "-xf", str(source), "--no-same-owner",
         "--no-same-permissions", "-C", str(unpacked)],
        check=True,
    )
    if any(p.is_symlink() or not (p.is_dir() or p.is_file())
           for p in unpacked.rglob("*")):
        raise RuntimeError(f"{name} archive contains a link or special file")

    dll = unpacked / "amd_fidelityfx_upscaler_dx12.dll"
    if not dll.is_file():
        raise RuntimeError(
            f"{name} archive has no amd_fidelityfx_upscaler_dx12.dll"
        )
    notices = unpacked / "notices"
    return dll, notices if notices.is_dir() else None


def optiscaler_artifact(
    args, staging: Path, ffx_sdk: Path, version: str, provenance: str = "",
    notices: Path | None = None
) -> tuple[Path, dict]:
    """Lay out the OptiScaler tree as it must land in the prefix, and describe it.

    `ffx_sdk` is the FidelityFX bridge to lay over OptiScaler's own, and
    `version` the name protonfixes must ask for. Everything else is identical
    between variants, which is why the whole tree is rebuilt per variant rather
    than patched: protonfixes installs an OptiScaler entry all-or-nothing and
    verifies every file in it, so a variant has to be a complete, self-consistent
    set with its own hashes.
    """
    extracted = staging / ("optiscaler-" + version)
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

    validate_preset(args.preset, extracted / "OptiScaler.ini")

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
    # lets the pinned 4.1.1 provider win. A variant that deliberately ships a
    # newer bridge is opting into the opposite arrangement.
    shutil.copy2(ffx_sdk, extracted / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll")
    shutil.copy2(
        args.licenses / "FidelityFX-SDK-4.0.2.txt",
        extracted / "Licenses/FidelityFX-SDK-4.0.2.txt",
    )
    if notices is not None:
        # Shipped into the prefix because the release that carries this bridge
        # asks for its notices to be retained with it.
        for notice in sorted(notices.rglob("*")):
            if notice.is_file():
                target = extracted / "Licenses" / version / notice.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(notice, target)

    if provenance:
        # Say in the prefix itself where a non-AMD binary came from. Anyone
        # looking at an unsigned DLL in their prefix deserves to find this
        # next to it rather than in a build script.
        (extracted / "Licenses/THIRD-PARTY-UPSCALER.txt").write_text(
            provenance, encoding="utf-8"
        )

    # fakenvapi stands in for nvapi64.dll so OptiScaler can reach AntiLag 2,
    # Vulkan AntiLag+, XeLL or LatencyFlex where a game would otherwise need
    # NVIDIA Reflex. It goes beside the other bundled libraries rather than
    # getting its own config key: OptiDllPath is "the main folder for OptiScaler
    # to check dll files below", and the per-DLL Libraries.* keys only override
    # that, so `NvapiPath=auto` finds it exactly the way libxell.dll is found
    # today. OptiScaler's own [fakenvapi] UseFakenvapi defaults to on.
    #
    # The upstream README says fakenvapi ships inside OptiScaler 0.9+, but the
    # nightly this package pins contains no nvapi DLL at all -- checked, not
    # assumed -- so it is bundled here.
    subprocess.run(
        ["bsdtar", "-xf", str(args.fakenvapi), "--no-same-owner",
         "--no-same-permissions", "-C", str(extracted / "OptiScaler"),
         "fakenvapi.dll"],
        check=True,
    )
    fakenvapi = extracted / "OptiScaler/fakenvapi.dll"
    if not fakenvapi.is_file():
        raise RuntimeError("fakenvapi archive contains no fakenvapi.dll")

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
        "version": version,
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
    ap.add_argument("--fakenvapi", type=Path, required=True,
                    help="fakenvapi release .7z, tracked live by resolve-fakenvapi.sh")
    ap.add_argument("--provider", type=Path, required=True, help="amdxcffx64 .xz")
    ap.add_argument("--provider-version", default="4.1.1")
    ap.add_argument("--ffx-sdk", type=Path, required=True,
                    help="FidelityFX SDK amd_fidelityfx_upscaler_dx12.dll")
    # An optional second, opt-in variant of the same tree. It exists so a bridge
    # can be A/B'd against the shipped one on real hardware without a separate
    # package and without anyone hand-editing a prefix -- which pinning makes
    # impossible anyway, since every file is verified before launch.
    ap.add_argument("--ffx-sdk-alt", action="append", default=[], nargs=3,
                    metavar=("NAME", "PATH", "ORIGIN"),
                    help="an opt-in bridge variant: the short name the wrapper "
                         "accepts, the .dll or release archive to take it from, "
                         "and the URL recorded in the prefix. Repeatable.")
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

    aliases = {}
    variants = [(args.ffx_sdk, args.optiscaler_version, "", None)]

    with tempfile.TemporaryDirectory(prefix=".payload-") as temporary:
        staging = Path(temporary)
        for name, path, origin in args.ffx_sdk_alt:
            if name in ("", "default", "1", "0") or name in aliases:
                raise SystemExit(f"ERROR: unusable variant name: {name!r}")
            source = Path(path)
            dll, notices = bridge_from(source, staging, name)
            alt_version = args.optiscaler_version + "-" + name
            aliases[name] = alt_version
            variants.append(
                (
                    dll,
                    alt_version,
                    "amd_fidelityfx_upscaler_dx12.dll in this directory is NOT "
                    "the AMD-signed FidelityFX SDK binary.\n\n"
                    f"Origin: {origin or 'unspecified'}\n"
                    f"SHA256: {digest(dll)}\n\n"
                    "It is a third-party modified build, selected explicitly by "
                    "PROTON_USE_OPTISCALER. The default payload ships AMD's "
                    "signed bridge instead.\n",
                    notices,
                )
            )

        entries = []
        for ffx_sdk, version, provenance, notices in variants:
            archive, entry = optiscaler_artifact(
                args, staging, ffx_sdk, version, provenance, notices
            )
            shutil.copy2(archive, artifacts / Path(entry["download_url"]).name)
            entries.append(entry)
    provider = provider_artifact(args, artifacts)

    manifest = {"optiscaler": entries, "fsr_40_drv": [provider]}
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
                # Short names the wrapper resolves to a pinned version, so a
                # tester types PROTON_USE_OPTISCALER=fsr411b rather than a
                # version string nobody can remember.
                "optiscaler_aliases": aliases,
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
          + " (" + str(len(entries[0]["sha256_hash"])) + " verified files)")
    for name, version in aliases.items():
        print(f"==> pinned opt-in OptiScaler variant {name!r} as {version}")
    print("==> pinned FSR4 provider " + args.provider_version)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, configparser.Error,
            subprocess.SubprocessError) as error:
        raise SystemExit("ERROR: " + str(error))
