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


def validate_preset(preset_path: Path, ini_path: Path, extra: dict | None = None) -> dict:
    """Match the launcher's ConfigParser and key/value syntax before packaging.

    `extra` is a variant's own preset entries, checked against the same ini.
    """
    preset = json.loads(preset_path.read_text())
    preset = preset["preset"] if isinstance(preset, dict) and "preset" in preset else preset
    if not isinstance(preset, dict) or not preset:
        raise RuntimeError("OptiScaler preset must be a non-empty object")
    preset = {**preset, **(extra or {})}
    # A variant drops a shared key with None (JSON null): FreeFG's OptiScaler
    # renamed FSR.Fsr4ForceModel and writes its ini without it.
    preset = {key: value for key, value in preset.items() if value is not None}
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

    # seed_once names preset keys the launcher stops enforcing once the prefix
    # has a value of its own. A name that is not in the preset would silently
    # do nothing, so it fails the build instead.
    document = json.loads(preset_path.read_text())
    for key in document.get("seed_once", []) if isinstance(document, dict) else []:
        if key not in preset:
            raise RuntimeError("seed_once names a key the preset does not set: " + key)
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
    it is smaller over the wire (RC10's zip is 51 MB against a 95 MB DLL) and
    it carries the licence notices whose retention that release asks for.
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


# HelixSR Scaler (OptiScaler with HelixSR built in) is "helixsr"; the older
# route, HelixSR 1.x as OptiScaler's FidelityFX library on the stock nightly, is
# "helixsr-ffx".
HELIXSR_NAME = "helixsr"
HELIXSR_FFX_NAME = "helixsr-ffx"
# Since HelixSR Scaler 1.1.0 (HelixSR 2.0) HelixSR is one FidelityFX DLL that
# the Scaler finds in a HelixSR-fsrfg folder next to its own DLL (the proxy,
# here umu/winmm.dll) or the game's .exe: HelixSR-fsrfg/amd_fidelityfx_dx12.dll,
# and HelixSR-fsrfg/helixsr-fg/ for frame generation. With that folder there,
# the Scaler's auto picks HelixSR as the Dx12 upscaler (ffx), the library path
# is spelled out below all the same, because the ffx route needs it to be right.
# FrameGen.Enabled is "false" in the shared preset; "auto" lets the game's own
# DLSS frame generation setting (on/off and multiplier) drive HelixSR's, which
# the Scaler only serves when FGInput is nvngxfg and FGNvngxReplacement HelixSR
# (its README; the older [HelixSR] FrameGeneration key is gone).
SCALER_FOLDER = "HelixSR-fsrfg"
SCALER_PRESET = {
    "Upscalers.Dx12Upscaler": "ffx",
    "Libraries.FfxDx12SRPath":
        "C:\\windows\\system32\\umu\\" + SCALER_FOLDER + "\\amd_fidelityfx_dx12.dll",
    "FrameGen.Enabled": "auto",
    "FrameGen.FGInput": "nvngxfg",
    "FrameGen.FGNvngxReplacement": "HelixSR",
}
# Where OptiScaler finds the HelixSR DLL in the prefix: the payload folder
# (Libraries.OptiDllPath), under both FidelityFX names. HelixSR's README has
# both library paths point at it explicitly, or OptiScaler may pick another
# FidelityFX DLL for one of the two roles.
HELIXSR_PRESET = {
    "Libraries.FfxDx12Path": "C:\\windows\\system32\\umu\\OptiScaler\\amd_fidelityfx_dx12.dll",
    "Libraries.FfxDx12SRPath": "C:\\windows\\system32\\umu\\OptiScaler\\amd_fidelityfx_upscaler_dx12.dll",
    # UpscalerIndex picks from the providers that DLL lists. With the package's
    # FSR4 provider (amdxcffx64.dll) in the prefix, HelixSR lists AMD's FSR 4.1.1
    # first and itself second, so the shared preset's 0 selected FSR4 and
    # HelixSR sat unused in the dropdown (Spider-Man 2: 5.35 ms on 4.1.1, 1.72 ms
    # on HelixSR at 1512x856 -> 1440p). FreeFG relies on 0 because its plain
    # GE-Proton has no provider there.
    "FSR.UpscalerIndex": "1",
}


# FreeFG (daniel-h-0/freefg) speeds up Intel's XeSS frame generation (XeFG) on
# the BC-250. Its OptiScaler build is the proxy; OptiScaler loads XeFG as
# libxess_fg.dll from its library folder (Libraries.OptiDllPath, umu\OptiScaler),
# so FreeFG's wrapper DLL takes that name there, with Intel's unmodified runtime
# beside it as bc250_xefg_original.dll and FreeFG's shaders and Vulkan pacing
# layer in BC250-XeFG/ (the wrapper looks for both beside itself). This is
# FreeFG's own "xefg on the OptiScaler route" layout, with umu\ as the game
# folder.
FREEFG_NAME = "freefg"
# FreeFG with HelixSR as its upscaler, as FreeFG's Setup also offers.
FREEFG_HELIXSR_NAME = "freefg-helixsr"
FREEFG_FOLDER = "OptiScaler/BC250-XeFG"
FREEFG_LAYER = "VK_LAYER_BC250_xefg_wave"
# What FreeFG's installer writes for its OptiScaler route at 2x (install.py
# CHANGES plus the route's own keys); the shared preset already has
# Dx12Upscaler=ffx, UpscalerIndex=0, Fsr4ForceModel=2 and LoadAsiPlugins=true.
# FGInput: FreeFG picks it per game from its recipes and falls back to OptiFG
# (upscaler), which works in any game whose upscaler OptiScaler sees, so that
# fallback is the default here. XeLL then needs Reflex forced on (FreeFG does
# the same for that input). XeFGPath/XeLLPath are left alone: this OptiScaler
# reads XeFGPath into its XeSS library path, and the library folder already
# finds both.
FREEFG_PRESET = {
    "FrameGen.Enabled": "true",
    "FrameGen.FGInput": "upscaler",
    "FrameGen.FGOutput": "xefg",
    "XeFG.InterpolationCount": "1",
    # XeFG does not interpolate in exclusive fullscreen.
    "XeFG.ForceBorderless": "true",
    "fakenvapi.ForceReflex": "2",
    # FreeFG's OptiScaler (master of 19 October) renamed Fsr4ForceModel to
    # Fsr4GpuSupport and writes its ini without the old name, so the shared key
    # would stop the next launch once the player changed anything in the menu.
    "FSR.Fsr4ForceModel": None,
    "FSR.Fsr4GpuSupport": "2",
}


def freefg_from(source: Path, nightly: Path, staging: Path) -> tuple[dict[str, Path], Path]:
    """Unpack a FreeFG release into the files its variant adds, and its notices.

    The wrapper accepts only the Intel runtime FreeFG pins (it checks size and
    hash at load and otherwise leaves XeFG unavailable, which a player would
    only see as "no frame generation"). That runtime is the libxess_fg.dll of
    the pinned OptiScaler nightly, so it is taken from there and checked
    against FreeFG's own pin here: a nightly bump that changes it fails the
    build instead.
    """
    unpacked = staging / "freefg"
    unpacked.mkdir()
    subprocess.run(
        ["bsdtar", "-xf", str(source), "--no-same-owner",
         "--no-same-permissions", "-C", str(unpacked)],
        check=True,
    )
    if any(p.is_symlink() or not (p.is_dir() or p.is_file())
           for p in unpacked.rglob("*")):
        raise RuntimeError("FreeFG archive contains a link or special file")
    manifests = sorted(unpacked.rglob("dependencies.json"))
    if len(manifests) != 1:
        raise RuntimeError("FreeFG archive must contain exactly one dependencies.json")
    root = manifests[0].parent
    for name in ("opti/OptiScaler.dll", "payload/libxess_fg.dll",
                 "payload/BC250-XeFG/layer/layer.json"):
        if not (root / name).is_file():
            raise RuntimeError("FreeFG archive has no " + name)
    layer = json.loads((root / "payload/BC250-XeFG/layer/layer.json").read_text())
    if layer.get("layer", {}).get("name") != FREEFG_LAYER:
        raise RuntimeError("FreeFG's Vulkan layer is not " + FREEFG_LAYER)
    if not (root / "payload/BC250-XeFG/shaders").is_dir():
        raise RuntimeError("FreeFG archive has no shader profile")

    pins = json.loads(manifests[0].read_text())
    wanted = pins["runtime"]["Files"]["OptiScaler/libxess_fg.dll"]
    runtime_dir = staging / "freefg-runtime"
    runtime_dir.mkdir()
    subprocess.run(
        ["bsdtar", "-xf", str(nightly), "--no-same-owner", "--no-same-permissions",
         "-C", str(runtime_dir), "OptiScaler/libxess_fg.dll"],
        check=True,
    )
    runtime = runtime_dir / "OptiScaler/libxess_fg.dll"
    if not runtime.is_file() or digest(runtime) != wanted:
        raise RuntimeError(
            "the OptiScaler nightly's libxess_fg.dll is not the Intel XeFG runtime "
            f"FreeFG pins ({wanted}); FreeFG would refuse it")

    files = {
        "OptiScaler/libxess_fg.dll": root / "payload/libxess_fg.dll",
        "OptiScaler/bc250_xefg_original.dll": runtime,
    }
    # settings.ini is not shipped: the wrapper reads it beside the game's .exe,
    # never from here, and its defaults are what that file holds anyway.
    for path in sorted((root / "payload/BC250-XeFG").rglob("*")):
        relative = path.relative_to(root / "payload/BC250-XeFG").as_posix()
        if path.is_file() and relative != "settings.ini":
            files[f"{FREEFG_FOLDER}/{relative}"] = path

    notices = staging / "freefg-notices"
    notices.mkdir()
    for path in sorted((root / "licenses").rglob("*")):
        if path.is_file():
            target = notices / path.relative_to(root / "licenses").as_posix().replace("/", "-")
            shutil.copy2(path, target)
    for name in ("NOTICE.md", "SOURCE.md"):
        if not (root / name).is_file():
            raise RuntimeError("FreeFG archive has no " + name)
        shutil.copy2(root / name, notices / ("FreeFG-" + name))
    return {"opti": root / "opti/OptiScaler.dll", **files}, notices


HELIXSR_NETWORK_FILES = ("helixsr_weights.bin", "helixsr_kernels.pak")
# Since 1.8.0 the setup builds the network into the DLL itself. The release DLL
# is about 5 MB without it and 13 MB with it (90 shaders), so anything below
# this is an unbuilt release and would run as a plain bilinear upscale.
HELIXSR_BUILT_DLL_MIN = 8 * 1024 * 1024
# 2.0.0's unbuilt DLL is 7.6 MB, just under that, so the setup's own marker
# decides first: a built DLL ends with a 32-byte trailer starting HXSRNET1.
HELIXSR_NETWORK_TRAILER = b"HXSRNET1"


def helixsr_dll_is_built(dll: Path) -> bool:
    size = dll.stat().st_size
    if size < 32:
        return False
    with dll.open("rb") as handle:
        handle.seek(size - 32)
        if handle.read(8) == HELIXSR_NETWORK_TRAILER:
            return True
    return size >= HELIXSR_BUILT_DLL_MIN


def helixsr_from(source: Path, staging: Path) -> tuple[Path, Path, Path, dict[str, Path], dict[str, Path]]:
    """Unpack a HelixSR release: its DLL, its helixsr.ini, its notices.

    The upstream zip carries no network: its setup script builds it from
    NVIDIA's DLSS DLL. Up to 1.7.0 that produced two files,
    helixsr_weights.bin and helixsr_kernels.pak, beside the DLL; since 1.8.0 it
    is written into the DLL. The archive given here is the upstream zip after
    that setup has run, and the network must be there either way: without it
    HelixSR only does a plain upscale, which would ship as a silent downgrade.

    HelixSR is one FSR 3.1 DLL (amd_fidelityfx_dx12.dll) that runs NVIDIA's
    DLSS Model E network. Its release zip has everything under a versioned
    top-level folder. The ini is shipped as released, so every default is the
    author's, helixsr.log beside the DLL included.
    """
    unpacked = staging / "helixsr"
    unpacked.mkdir()
    subprocess.run(
        ["bsdtar", "-xf", str(source), "--no-same-owner",
         "--no-same-permissions", "-C", str(unpacked)],
        check=True,
    )
    if any(p.is_symlink() or not (p.is_dir() or p.is_file())
           for p in unpacked.rglob("*")):
        raise RuntimeError("HelixSR archive contains a link or special file")
    dlls = sorted(unpacked.rglob("amd_fidelityfx_dx12.dll"))
    if len(dlls) != 1:
        raise RuntimeError("HelixSR archive must contain exactly one amd_fidelityfx_dx12.dll")
    root = dlls[0].parent
    network = {}
    for name in HELIXSR_NETWORK_FILES:
        if (root / name).is_file() and (root / name).stat().st_size > 0:
            network[name] = root / name
    if network and len(network) != len(HELIXSR_NETWORK_FILES):
        raise RuntimeError("HelixSR archive has only one of its two network files")
    if not network and not helixsr_dll_is_built(dlls[0]):
        raise RuntimeError(
            "HelixSR archive has no network: run its setup script on the "
            "release and archive the folder it produced")
    # Shipped byte for byte, log included: helixsr.log is what HelixSR's author
    # asks for with a problem report, and players could not give it to him
    # while this package switched it off.
    ini = root / "helixsr.ini"
    if not ini.is_file():
        raise RuntimeError("HelixSR archive has no helixsr.ini beside its DLL")
    # Only the licence texts go to Licenses/, not the release folder itself
    # (which holds the DLL and README too).
    notices = staging / "helixsr-notices"
    notices.mkdir()
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        # 2.0.0 keeps the DLL in a HelixSR-fsrfg folder below the release folder
        # that holds the notices; earlier releases had all of it in one folder.
        found = next((d / name for d in (root, root.parent) if (d / name).is_file()), None)
        if found is None:
            raise RuntimeError("HelixSR archive has no " + name)
        shutil.copy2(found, notices / name)
    # Frame generation (helixsr-fg/, built by the same setup): the Scaler runs
    # the game's DLSS frame generation on it. Absent when the setup ran with
    # --no-fg, which is fine for the FFX route and refused for the Scaler.
    fg = {}
    if (root / "helixsr-fg").is_dir():
        # Sub-folders too: 2.0.0 builds the light mode (the default) into
        # helixsr-fg/310.9.16/ beside the full mode's files. Logs and half-written
        # files are not part of it, as in HelixSR's own installer.
        fg = {f"helixsr-fg/{p.relative_to(root / 'helixsr-fg').as_posix()}": p
              for p in sorted((root / "helixsr-fg").rglob("*"))
              if p.is_file() and not p.name.lower().endswith((".log", ".tmp"))
              and ".log." not in p.name.lower()}
    return dlls[0], ini, notices, network, fg


def scaler_from(source: Path, staging: Path) -> tuple[Path, Path, Path]:
    """Unpack HelixSR Scaler (OptiScaler with HelixSR built in): its DLL, ini, notices.

    Only OptiScaler.dll and OptiScaler.ini differ from the stock nightly of the
    same generation (every other library is byte-identical), so the archive
    given here holds just those two and the licence texts of the release zip.
    """
    unpacked = staging / "scaler"
    unpacked.mkdir()
    subprocess.run(
        ["bsdtar", "-xf", str(source), "--no-same-owner",
         "--no-same-permissions", "-C", str(unpacked)],
        check=True,
    )
    if any(p.is_symlink() or not (p.is_dir() or p.is_file())
           for p in unpacked.rglob("*")):
        raise RuntimeError("HelixSR Scaler archive contains a link or special file")
    dlls = sorted(unpacked.rglob("OptiScaler.dll"))
    if len(dlls) != 1:
        raise RuntimeError("HelixSR Scaler archive must contain exactly one OptiScaler.dll")
    root = dlls[0].parent
    if not (root / "OptiScaler.ini").is_file():
        raise RuntimeError("HelixSR Scaler archive has no OptiScaler.ini")
    notices = staging / "scaler-notices"
    notices.mkdir()
    for path in sorted((root / "Licenses").glob("*")) if (root / "Licenses").is_dir() else []:
        shutil.copy2(path, notices / path.name)
    if not any(notices.iterdir()):
        raise RuntimeError("HelixSR Scaler archive has no Licenses/")
    return dlls[0], root / "OptiScaler.ini", notices


def seed_fakenvapi_settings(extracted: Path) -> Path | None:
    """Stop fakenvapi logging on every launch, unless it brought its own settings.

    fakenvapi writes fakenvapi.log beside its own DLL and its compiled default is
    enable_logs=true (config.h). It reads that setting from a fakenvapi.ini in
    the same directory -- one upstream's archive ships and this package did not
    extract -- so the package logged by default while presenting
    BC250_FSR4_DEBUG as the way to ask for logs.

    Only written when there is none: a future OptiScaler that bundles fakenvapi
    brings settings matched to that build. The file lands in the prefix and stays
    editable there, because .ini files are left out of the per-file checksums, so
    setting enable_logs=1 to diagnose something survives the next launch.
    """
    dll = next(
        (candidate for candidate in (
            extracted / "fakenvapi.dll", extracted / "OptiScaler/fakenvapi.dll",
            extracted / "nvapi64.dll", extracted / "OptiScaler/nvapi64.dll")
         if candidate.is_file()),
        None,
    )
    if dll is None:
        return None
    settings = dll.parent / "fakenvapi.ini"
    if settings.is_file():
        return settings
    settings.write_text(
        "; Written by the BC-250 package. fakenvapi logs to fakenvapi.log beside\n"
        "; this file unless told otherwise, and its own default is to do so.\n"
        "; Set enable_logs=1 (and enable_trace_logs=1 for more) to diagnose a\n"
        "; latency or Reflex problem -- this file is yours to edit and is not\n"
        "; checksummed, so the change survives the next launch.\n"
        "[fakenvapi]\n"
        "enable_logs=0\n"
        "enable_trace_logs=0\n",
        encoding="utf-8",
    )
    return settings


def optiscaler_artifact(
    args, staging: Path, ffx_sdk: Path, version: str, provenance: str = "",
    notices: Path | None = None, extra: dict | None = None,
    variant_preset: dict | None = None
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

    if not (extra and "OptiScaler.ini" in extra):
        # A variant with its own ini is checked against that one, below.
        validate_preset(args.preset, extracted / "OptiScaler.ini", variant_preset)

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

    # Files a variant adds beside the bridge (HelixSR: itself again as
    # amd_fidelityfx_dx12.dll, and its helixsr.ini). The Scaler variant also
    # replaces the proxy and OptiScaler.ini this way.
    for name, content in (extra or {}).items():
        target = extracted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy2(content, target)
        else:
            target.write_text(content, encoding="utf-8")
    if extra and "OptiScaler.ini" in extra:
        # The ini the launcher will actually edit is this one, not the nightly's.
        validate_preset(args.preset, extracted / "OptiScaler.ini", variant_preset)

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
    # If a future OptiScaler build starts bundling it after all, keep theirs:
    # it is the copy matched to that build, and overwriting it silently would
    # make this package quietly diverge from upstream on every nightly bump.
    shipped = [
        candidate
        for candidate in (
            extracted / "fakenvapi.dll",
            extracted / "OptiScaler/fakenvapi.dll",
            extracted / "nvapi64.dll",
            extracted / "OptiScaler/nvapi64.dll",
        )
        if candidate.is_file()
    ]
    if shipped:
        print("==> OptiScaler already bundles "
              + ", ".join(str(c.relative_to(extracted)) for c in shipped)
              + "; not adding ours", file=sys.stderr)
    else:
        subprocess.run(
            ["bsdtar", "-xf", str(args.fakenvapi), "--no-same-owner",
             "--no-same-permissions", "-C", str(extracted / "OptiScaler"),
             "fakenvapi.dll"],
            check=True,
        )
        if not (extracted / "OptiScaler/fakenvapi.dll").is_file():
            raise RuntimeError("fakenvapi archive contains no fakenvapi.dll")

    seed_fakenvapi_settings(extracted)

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
        # The DLL name baked into this payload. protonfixes links
        # PROTON_OPTISCALER_NAME to it when a caller asks for another name.
        "proxy": args.proxy,
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
    ap.add_argument("--ffx-sdk-default", default="",
                    help="name of an --ffx-sdk-alt variant, 'helixsr' when "
                         "--helixsr-scaler is given or 'helixsr-ffx' when "
                         "--helixsr is, to ship as the default; the "
                         "AMD-signed --ffx-sdk bridge then becomes the "
                         "'signed' variant")
    ap.add_argument("--ffx-sdk-alt", action="append", default=[], nargs=3,
                    metavar=("NAME", "PATH", "ORIGIN"),
                    help="an opt-in bridge variant: the short name the wrapper "
                         "accepts, the .dll or release archive to take it from, "
                         "and the URL recorded in the prefix. Repeatable.")
    ap.add_argument("--helixsr", nargs=2, metavar=("ARCHIVE", "ORIGIN"),
                    help="HelixSR release zip (after its setup) and the URL recorded "
                         "in the prefix; adds the 'helixsr-ffx' variant (opt-in "
                         "unless named by --ffx-sdk-default)")
    ap.add_argument("--helixsr-scaler", nargs=2, metavar=("ARCHIVE", "ORIGIN"),
                    help="HelixSR Scaler archive (OptiScaler.dll, OptiScaler.ini, "
                         "Licenses/) and the URL recorded in the prefix; adds the "
                         "'helixsr' variant, which needs --helixsr for the "
                         "HelixSR DLL and its frame generation folder")
    ap.add_argument("--scaler-bridge", default="fsr411f",
                    help="name of the --ffx-sdk-alt bridge the HelixSR Scaler "
                         "variant ships as its FidelityFX library (what OptiScaler "
                         "offers as FSR4 and uses for Direct3D 11 and Vulkan)")
    ap.add_argument("--freefg", nargs=2, metavar=("ARCHIVE", "ORIGIN"),
                    help="FreeFG release zip and the URL recorded in the prefix; adds "
                         "the opt-in 'freefg' variant (Intel XeFG frame generation "
                         "with FreeFG's BC-250 shaders and VRR pacing layer), and "
                         "'freefg-helixsr' with HelixSR as its upscaler when "
                         "--helixsr is given")
    ap.add_argument("--freefg-ini", type=Path,
                    help="OptiScaler.ini of FreeFG's OptiScaler build (its fork's tree at "
                         "the tagged commit); the nightly's is older than that build")
    ap.add_argument("--freefg-bridge", default="fsr411f",
                    help="name of the --ffx-sdk-alt bridge the FreeFG variant ships "
                         "as its FidelityFX upscaler (FreeFG's own is RC11, fsr411f)")
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
    variants = []
    # Preset entries that apply only when that pinned version is selected.
    variant_presets = {}
    # FreeFG's Vulkan layer, by pinned version: the launcher points the loader
    # at it in the prefix when that version is selected.
    freefg_layers = {}

    # SIGNED_NAME is what the AMD-signed bridge is called once something else is
    # the default. It has to be reachable by name either way: a player comparing
    # an unsigned bridge against the signed one is the whole point of having
    # variants, and "what this package used to do" has to stay one launch option
    # away.
    SIGNED_NAME = "signed"
    bridges = {}
    if args.helixsr_scaler and not args.helixsr:
        raise SystemExit("ERROR: --helixsr-scaler needs --helixsr (its DLL and frame generation)")
    if args.ffx_sdk_default and args.ffx_sdk_default not in {
        name for name, _, _ in args.ffx_sdk_alt
    } | ({HELIXSR_FFX_NAME} if args.helixsr else set()) \
      | ({HELIXSR_NAME} if args.helixsr_scaler else set()):
        raise SystemExit(
            f"ERROR: --ffx-sdk-default names no variant: {args.ffx_sdk_default!r}")

    def unsigned_provenance(dll: Path, origin: str, is_default: bool) -> str:
        return (
            "amd_fidelityfx_upscaler_dx12.dll in this directory is NOT the "
            "AMD-signed FidelityFX SDK binary.\n\n"
            f"Origin: {origin or 'unspecified'}\n"
            f"SHA256: {digest(dll)}\n\n"
            + ("It is a third-party modified build, and it is what this package "
               "ships by default. AMD's signed bridge remains available with "
               f"PROTON_USE_OPTISCALER={SIGNED_NAME}.\n"
               if is_default else
               "It is a third-party modified build, selected explicitly by "
               "PROTON_USE_OPTISCALER.\n")
        )

    with tempfile.TemporaryDirectory(prefix=".payload-") as temporary:
        staging = Path(temporary)
        signed_is_default = not args.ffx_sdk_default
        if signed_is_default:
            variants.append((args.ffx_sdk, args.optiscaler_version, "", None, None))
        else:
            # Same treatment the alternates get, so the signed build is a normal
            # variant rather than a special case with its own code path.
            signed_version = args.optiscaler_version + "-" + SIGNED_NAME
            aliases[SIGNED_NAME] = signed_version
            variants.append((args.ffx_sdk, signed_version, "", None, None))

        for name, path, origin in args.ffx_sdk_alt:
            if name in ("", "default", "1", "0", SIGNED_NAME, HELIXSR_NAME,
                        HELIXSR_FFX_NAME, FREEFG_NAME, FREEFG_HELIXSR_NAME, "optiscaler") or name in aliases:
                raise SystemExit(f"ERROR: unusable variant name: {name!r}")
            source = Path(path)
            dll, notices = bridge_from(source, staging, name)
            bridges[name] = (dll, notices, origin)
            is_default = name == args.ffx_sdk_default
            version = (args.optiscaler_version if is_default
                       else args.optiscaler_version + "-" + name)
            # The default's own short name resolves too, so the launch option
            # documented for it keeps working once it becomes the default.
            aliases[name] = version
            variants.append(
                (dll, version, unsigned_provenance(dll, origin, is_default), notices, None)
            )

        helixsr = None
        if args.helixsr:
            helixsr = helixsr_from(Path(args.helixsr[0]), staging)
            dll, ini, notices, network, fg = helixsr
            origin = args.helixsr[1]
            # As the default it takes the plain OptiScaler version, like any
            # other default, and its library paths in variant_presets then apply
            # to every launch that does not name another variant.
            is_default = args.ffx_sdk_default == HELIXSR_FFX_NAME
            version = (args.optiscaler_version if is_default
                       else args.optiscaler_version + "-" + HELIXSR_FFX_NAME)
            aliases[HELIXSR_FFX_NAME] = version
            variant_presets[version] = dict(HELIXSR_PRESET)
            provenance = (
                "amd_fidelityfx_dx12.dll and amd_fidelityfx_upscaler_dx12.dll in "
                "this directory are both HelixSR, NOT AMD FidelityFX binaries.\n\n"
                f"Origin: {origin}\n"
                f"SHA256: {digest(dll)}\n\n"
                "HelixSR answers OptiScaler as FSR 3.1 and runs NVIDIA's DLSS Model E "
                "network (its trained weights and GPU kernels translated to DirectX 12). "
                "Per its author, those components remain the property of NVIDIA "
                "Corporation and are not covered by HelixSR's licence; "
                "the network in the DLL (before 1.8.0: helixsr_weights.bin and "
                "helixsr_kernels.pak beside it) is "
                "built from NVIDIA's DLSS DLL by HelixSR's own setup script; see "
                f"Licenses/{version}/. "
                + ("This package ships it by default; the FidelityFX bridges "
                   "remain available through PROTON_USE_OPTISCALER (signed, "
                   "fsr411f, ...). "
                   if is_default else
                   f"Selected explicitly by PROTON_USE_OPTISCALER={HELIXSR_FFX_NAME}. ")
                + "helixsr.ini is HelixSR's own, unchanged.\n"
            )
            variants.append((
                dll, version, provenance, notices,
                {"OptiScaler/amd_fidelityfx_dx12.dll": dll, "OptiScaler/helixsr.ini": ini,
                 **{f"OptiScaler/{name}": path for name, path in network.items()}},
            ))

        if args.helixsr_scaler:
            scaler_dll, scaler_ini, scaler_notices = scaler_from(
                Path(args.helixsr_scaler[0]), staging)
            dll, ini, helix_notices, network, fg = helixsr
            if network:
                raise SystemExit("ERROR: the Scaler needs HelixSR 1.8.0 or later "
                                 "(network inside the DLL)")
            if not fg:
                raise SystemExit("ERROR: HelixSR archive has no helixsr-fg/: run its "
                                 "setup without --no-fg and archive the folder it produced")
            if args.scaler_bridge not in bridges:
                raise SystemExit(f"ERROR: --scaler-bridge names no --ffx-sdk-alt: "
                                 f"{args.scaler_bridge!r}")
            bridge, bridge_notices, bridge_origin = bridges[args.scaler_bridge]
            is_default = args.ffx_sdk_default == HELIXSR_NAME
            version = (args.optiscaler_version if is_default
                       else args.optiscaler_version + "-" + HELIXSR_NAME)
            aliases[HELIXSR_NAME] = version
            variant_presets[version] = dict(SCALER_PRESET)
            merged = staging / "scaler-all-notices"
            merged.mkdir()
            for path in sorted(scaler_notices.iterdir()):
                shutil.copy2(path, merged / path.name)
            for path in sorted(helix_notices.iterdir()):
                shutil.copy2(path, merged / ("HelixSR-" + path.name))
            for path in sorted(bridge_notices.rglob("*")) if bridge_notices else []:
                if path.is_file():
                    shutil.copy2(path, merged / (args.scaler_bridge + "-" + path.name))
            provenance = (
                f"{args.proxy} in this directory is HelixSR Scaler, OptiScaler with HelixSR "
                "built in (GPL-3.0; source: https://github.com/lonewolf0622/HelixSR-Scaler), "
                "NOT the stock OptiScaler nightly.\n\n"
                f"Origin: {args.helixsr_scaler[1]}\n"
                f"SHA256: {digest(scaler_dll)}\n\n"
                f"{SCALER_FOLDER}/amd_fidelityfx_dx12.dll is HelixSR, which runs NVIDIA's DLSS "
                f"Model E network as DirectX 12 compute.\nOrigin: {args.helixsr[1]}\n"
                f"SHA256: {digest(dll)}\n\n"
                f"{SCALER_FOLDER}/helixsr-fg/ holds the files its frame generation runs on "
                "(NVIDIA's DLSS frame generation network and NGX core, Intel's XeLL), "
                "built or fetched by HelixSR's own setup script. Per its author, "
                "the NVIDIA components remain the property of NVIDIA Corporation and "
                f"are not covered by HelixSR's licence; see Licenses/{version}/.\n\n"
                "OptiScaler/amd_fidelityfx_upscaler_dx12.dll is the "
                f"{args.scaler_bridge} FSR4 bridge (origin: {bridge_origin}); it is what "
                "OptiScaler offers as FSR4 and uses for Direct3D 11 and Vulkan games.\n"
                + ("This package ships the Scaler by default; the stock OptiScaler "
                   "nightly stays available with PROTON_USE_OPTISCALER=optiscaler "
                   "(and the bridge variants).\n"
                   if is_default else
                   f"Selected explicitly by PROTON_USE_OPTISCALER={HELIXSR_NAME}.\n")
            )
            extra = {
                args.proxy: scaler_dll,
                "OptiScaler.ini": scaler_ini,
                f"{SCALER_FOLDER}/amd_fidelityfx_dx12.dll": dll,
                f"{SCALER_FOLDER}/helixsr.ini": ini,
                **{f"{SCALER_FOLDER}/{name}": path for name, path in fg.items()},
            }
            variants.append((bridge, version, provenance, merged, extra))

        if args.freefg:
            # Opt-in only: FreeFG 1.0.x has been qualified in menus and
            # benchmarks, not in play.
            freefg, freefg_notices = freefg_from(
                Path(args.freefg[0]), args.optiscaler, staging)
            if not args.freefg_ini:
                raise SystemExit("ERROR: --freefg needs --freefg-ini (the OptiScaler.ini "
                                 "of FreeFG's OptiScaler build)")
            if args.freefg_bridge not in bridges:
                raise SystemExit(f"ERROR: --freefg-bridge names no --ffx-sdk-alt: "
                                 f"{args.freefg_bridge!r}")
            bridge, bridge_notices, bridge_origin = bridges[args.freefg_bridge]
            # Two upscalers, as FreeFG's own Setup offers: the RC11 bridge it
            # ships (freefg), and HelixSR in its place (freefg-helixsr), laid
            # out like helixsr-ffx. HelixSR's frame generation cannot load there
            # (no helixsr-fg/), so frame generation stays XeFG and its ini can
            # ship as released.
            upscalers = [(FREEFG_NAME, bridge, {}, {}, bridge_notices, args.freefg_bridge,
                          f"the {args.freefg_bridge} FSR4 bridge (origin: {bridge_origin}), "
                          "the same RC11 build FreeFG ships")]
            if helixsr:
                dll, ini, helix_notices, network, fg = helixsr
                upscalers.append((
                    FREEFG_HELIXSR_NAME, dll,
                    {"OptiScaler/amd_fidelityfx_dx12.dll": dll, "OptiScaler/helixsr.ini": ini,
                     **{f"OptiScaler/{name}": path for name, path in network.items()}},
                    HELIXSR_PRESET, helix_notices, "HelixSR",
                    f"HelixSR (origin: {args.helixsr[1]}, SHA256 {digest(dll)}), which runs "
                    "NVIDIA's DLSS Model E network as DirectX 12 compute; it is also "
                    "OptiScaler/amd_fidelityfx_dx12.dll. Per its author, that network remains "
                    "the property of NVIDIA Corporation and is not covered by HelixSR's licence"))
            for name, ffx_sdk, upscaler_files, upscaler_preset, upscaler_notices, \
                    notice_prefix, upscaler_text in upscalers:
                version = args.optiscaler_version + "-" + name
                aliases[name] = version
                variant_presets[version] = {**FREEFG_PRESET, **upscaler_preset}
                freefg_layers[version] = {
                    "layer": FREEFG_LAYER,
                    "layer_dir": f"{FREEFG_FOLDER}/layer",
                    "wave_config": f"{FREEFG_FOLDER}/shaders/waves.txt",
                    # 49 of the wrapper's 57 exports are forwarders to the module
                    # "bc250_xefg_original", which the loader looks up by name on
                    # the DLL search path. FreeFG puts it beside the game's .exe;
                    # here it is in OptiScaler's library folder, so that folder has
                    # to be on the path, or OptiScaler gets NULL for every forwarded
                    # export and calls it (Spider-Man 2, xefgSwapChainSetLoggingCallback).
                    "dll_path": "C:\\windows\\system32\\umu\\OptiScaler",
                }
                merged = staging / (name + "-all-notices")
                merged.mkdir()
                for path in sorted(freefg_notices.iterdir()):
                    shutil.copy2(path, merged / path.name)
                for path in sorted(upscaler_notices.rglob("*")) if upscaler_notices else []:
                    if path.is_file():
                        shutil.copy2(path, merged / (notice_prefix + "-" + path.name))
                provenance = (
                    f"{args.proxy} in this directory is FreeFG's build of OptiScaler (GPL-3.0; "
                    "source: https://github.com/daniel-h-0/OptiScaler/releases/tag/bc250-f971ed1 "
                    "and freefg-1.0.1-source.zip beside FreeFG's release), NOT the stock "
                    "OptiScaler nightly.\n\n"
                    f"Origin: {args.freefg[1]}\n"
                    f"SHA256: {digest(freefg['opti'])}\n\n"
                    "OptiScaler/libxess_fg.dll is FreeFG's wrapper (MIT), which runs part of "
                    "the work of Intel's XeFG runtime with FreeFG's own shaders "
                    f"({FREEFG_FOLDER}/shaders/). OptiScaler/bc250_xefg_original.dll is Intel's "
                    "XeFG runtime, unmodified (the nightly's libxess_fg.dll, renamed).\n"
                    f"SHA256 of the wrapper: {digest(freefg['OptiScaler/libxess_fg.dll'])}\n\n"
                    f"{FREEFG_FOLDER}/layer/ is FreeFG's Linux Vulkan layer that paces "
                    "generated frames for VRR displays.\n\n"
                    f"OptiScaler/amd_fidelityfx_upscaler_dx12.dll is {upscaler_text}.\n"
                    f"Selected explicitly by PROTON_USE_OPTISCALER={name}.\n"
                )
                extra = {args.proxy: freefg["opti"], "OptiScaler.ini": args.freefg_ini,
                         **{n: path for n, path in freefg.items() if n != "opti"},
                         **upscaler_files}
                variants.append((ffx_sdk, version, provenance, merged, extra))

        # The stock OptiScaler nightly, selected with one name whichever variant
        # is the default: the FSR4 fork's bridge, like the packages shipped
        # before HelixSR became the default. Other bridges are their own names.
        if "fsr411f" in aliases:
            aliases["optiscaler"] = aliases["fsr411f"]

        entries = []
        for ffx_sdk, version, provenance, notices, extra in variants:
            archive, entry = optiscaler_artifact(
                args, staging, ffx_sdk, version, provenance, notices, extra,
                variant_presets.get(version)
            )
            shutil.copy2(archive, artifacts / Path(entry["download_url"]).name)
            entries.append(entry)
    provider = provider_artifact(args, artifacts)

    manifest = {"optiscaler": entries, "fsr_40_drv": [provider]}
    (args.output / "upscaler-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    document = json.loads(args.preset.read_text())
    preset = document["preset"] if "preset" in document else document
    seed_once = document.get("seed_once", []) if isinstance(document, dict) else []
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
                # Merged over the preset only when that version is the one
                # asked for (keyed by pinned version, like the manifest).
                "optiscaler_variant_preset": variant_presets,
                # Paths below the payload folder (system32/umu in the prefix).
                "freefg": freefg_layers,
                # Enforced into a fresh prefix and then left to the user, so the
                # OptiScaler overlay can own them from that point on.
                "seed_once": seed_once,
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
