#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Point Proton at this tool's pinned FSR4 payload, then hand the process over.

Steam runs a sibling shim, which runs this file; this file execve()s the real
Proton. The indirection exists so the environment can be prepared without
patching Proton's own launcher.

The two packages lay their tool directory out differently -- protonge-latest
keeps GE under `ge/`, while proton-cachyos-native is the Proton tree itself --
so where the real proton and the pinned manifest live comes from the config
written at build time, not from anything assumed here.

Everything this touches is either owned by the package (the pinned manifest, the
OptiScaler proxy name, the preset) or a stale setting from some other Proton
build that would break a pinned launch. The user's own choices are left alone.
"""

import configparser
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

TOOL = Path(__file__).resolve().parent

# protonfixes would fetch these from its remote manifest. Ours pins only the
# FSR4 provider and OptiScaler, and pinned mode refuses to launch rather than
# quietly falling back to the network -- so a stale launch option left over from
# another Proton build would turn into a game that does not start. Drop them and
# let the payload we actually ship decide.
UNSHIPPED = (
    "PROTON_DLSS_UPGRADE",
    "PROTON_XESS_UPGRADE",
    "PROTON_FFX3_UPGRADE",
    "PROTON_FFX4_UPGRADE",
    "PROTON_FSR3_UPGRADE",
    "PROTON_MLFG_UPGRADE",
)

# These address the pinned payload by path and by name. A caller cannot supply a
# meaningful value for any of them, and a wrong one either breaks the launch or
# silently swaps in an unverified DLL. They are cleared and then set here.
#
# PROTON_OPTISCALER_NAME is the one a caller may still ask for: it does not
# choose which DLL is loaded -- the manifest pins that -- only which import the
# game resolves to OptiScaler; protonfixes links that name to the pinned DLL in
# the prefix. See proxy_name().
OWNED = (
    "PROTON_UPSCALER_MANIFEST",
    "PROTON_OPTISCALER_NAME",
    "PROTON_OPTISCALER_CONFIG",
    "WINE_OPTISCALER_NAME",
    "WINE_UPSCALER_REPLACE",
    "FSR4_UPGRADE",
    "MLFG_UPGRADE",
    # Sets DXIL_SPIRV_CONFIG=wmma_rdna3_workaround. The BC-250 is gfx1013, which
    # has no WMMA at all; the FSR4 path here comes from our patched RADV. This
    # would only mis-tune codegen for hardware that is not present.
    "PROTON_FSR4_RDNA3_UPGRADE",
)


def game_launch(arguments, inherited):
    """True only for an actual game launch.

    Steam runs this tool for path conversion, installers and GPU queries too,
    and those calls can inherit a game identity from the session -- so the verb
    has to agree as well. "0" is Steam's own "no game" value for the ids.

    umu, which is how Heroic and Lutris run this tool, is the exception: it
    derives SteamAppId from its own GAMEID and writes SteamGameId to match, so
    a non-Steam title arrives with both set to "0". Heroic's GAMEID for a GOG
    game is literally "umu-0". Judged on the ids alone that reads as a utility
    call and the launch loses FSR4 entirely -- which is what happened. umu
    always names the game in UMU_ID, and Steam never sets it, so its presence
    is the signal the ids cannot give here.

    Getting this wrong applies the whole FSR4 environment to a utility call, or
    withholds it from a real one.
    """
    if not arguments or arguments[0] not in ("run", "waitforexitandrun"):
        return False
    if any(
        inherited.get(name, "") not in ("", "0")
        for name in ("SteamAppId", "SteamGameId")
    ):
        return True
    return bool(inherited.get("UMU_ID", "").strip())


# Names both anti-cheats put in a game's install directory. Matched
# case-insensitively against file and directory names, because games ship them
# with whatever capitalisation they like.
ANTICHEAT_NAMES = (
    "easyanticheat",
    "easyanticheat_eos",
    "start_protected_game.exe",
    "battleye",
    "beservice.exe",
    "beservice_x64.exe",
    "beclient.dll",
    "beclient_x64.dll",
)

# How deep to look. A directory at level N is scanned, so entries are seen at
# level N+1; 4 means a marker as deep as
#
#     <install>/Game/Binaries/Win64/EasyAntiCheat/
#
# is found, which is where Unreal Engine games put it -- the common case, and
# the one a shallower bound silently missed on real hardware. Bounded in both
# directions because this runs on every launch: a miss costs one game its
# upscaler, a slow scan costs every game its start-up time.
ANTICHEAT_SCAN_DEPTH = 4
ANTICHEAT_SCAN_DIRS = 2000


def anticheat_reason(inherited):
    """Say why this game looks anti-cheat protected, or None if it does not.

    Injecting a DLL into a game running EasyAntiCheat or BattlEye is the kind
    of thing accounts get banned for, and this package injects by default. So
    the payload steps aside when it sees one, and says so rather than silently
    doing nothing.

    This is a safety net, not a guarantee. A game whose anti-cheat arrives on
    first launch, or that lays its files out differently, will not be caught --
    so a player who cares still has to set PROTON_FSR4_UPGRADE=0 themselves. It
    can also be wrong the other way: a game that ships EAC files without using
    them loses its upscaler until PROTON_USE_OPTISCALER is set explicitly.
    """
    for name in ("PROTON_EAC_RUNTIME", "PROTON_BATTLEYE_RUNTIME"):
        if inherited.get(name, "").strip():
            return name + " is set"

    # Steam layers the EasyAntiCheat and BattlEye runtimes as compatibility
    # tools of their own, and passes the whole chain down in this variable.
    tools = inherited.get("STEAM_COMPAT_TOOL_PATHS", "").lower()
    for needle in ("easyanticheat", "battleye"):
        if needle in tools:
            return "STEAM_COMPAT_TOOL_PATHS names " + needle

    install = inherited.get("STEAM_COMPAT_INSTALL_PATH", "").strip()
    if not install:
        return None
    pending = [(Path(install), 0)]
    seen = 0
    while pending and seen < ANTICHEAT_SCAN_DIRS:
        directory, depth = pending.pop(0)
        seen += 1
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if entry.name.lower() in ANTICHEAT_NAMES:
                return entry.name + " in the game directory"
            if depth + 1 < ANTICHEAT_SCAN_DEPTH and entry.is_dir(follow_symlinks=False):
                pending.append((Path(entry.path), depth + 1))
    return None


def anticheat_ignored(inherited):
    """Say why the anti-cheat guard is switched off, or None if it is not.

    Players who accept the ban risk asked for a switch that is not a second
    meaning of PROTON_FSR4_UPGRADE=1: BC250_FSR4_IGNORE_ANTICHEAT=1 for one
    game, or the file ~/.config/bc250-fsr4/ignore-anticheat for every game.
    A file because Steam has no global environment setting; it is read inside
    the Steam Linux Runtime too, where $HOME is the same.
    """
    if inherited.get("BC250_FSR4_IGNORE_ANTICHEAT", "").strip() == "1":
        return "BC250_FSR4_IGNORE_ANTICHEAT=1"
    config = inherited.get("XDG_CONFIG_HOME", "").strip()
    if not config and inherited.get("HOME", "").strip():
        config = str(Path(inherited["HOME"]) / ".config")
    if config:
        switch = Path(config) / "bc250-fsr4" / "ignore-anticheat"
        try:
            if switch.exists():
                return str(switch)
        except OSError:
            pass
    return None


def defaulted(env, name, value):
    """Set `name` unless the caller chose something. Empty counts as unset."""
    env[name] = env.get(name, "").strip() or value


def load_native(env, dll):
    """Ask Wine to load `dll` from disk, unless the caller already decided.

    Wine picks native or builtin by base name, and its hardcoded default for a
    DLL it implements itself -- winmm among them -- is builtin first. Proton's
    loader hack redirects the proxy's *path* into system32/umu but does not
    touch that decision, and a Wine that counts anything below system32 as a
    system directory then maps OptiScaler and drops it for its own winmm.
    Nothing fails: protonfixes reports the payload installed, the redirect is
    logged, and the game simply runs without an upscaler. Measured on
    proton-cachyos 11.0-20260703; GE-Proton 11-6 loads the same file native.
    """
    name = dll.rsplit(".", 1)[0].lower()
    entries = [entry for entry in env.get("WINEDLLOVERRIDES", "").split(";") if entry]
    if any(
        part.strip().lower() == name
        for entry in entries
        for part in entry.split("=")[0].split(",")
    ):
        return
    env["WINEDLLOVERRIDES"] = ";".join(entries + [name + "=n,b"])


def proxy_name(requested, default):
    """Which DLL name OptiScaler answers to, as the caller asked for it.

    The package proxies winmm because that is what has been tested here, but the
    name is not free: a game that already uses winmm for something of its own --
    a mod or ASI loader, most often -- gets its loader back instead of
    OptiScaler, and the upscaler silently never appears. Such a game needs a
    different import, usually dxgi, which is also upstream protonfixes' default.

    Unlike everything else in OWNED this swaps no pinned file: the payload is
    the same either way, so the worst a wrong name can do is leave OptiScaler
    unloaded. The payload is baked under one name, but Wine's loader redirects
    the imported name to umu\\<name>, so protonfixes also links the requested
    name to the pinned DLL in the prefix. It is still checked for shape, because
    it reaches Wine's loader as a name to match and a path fragment has no
    business there.
    """
    name = (requested or "").strip() or default
    if not name.lower().endswith(".dll"):
        name += ".dll"
    if not re.fullmatch(r"[A-Za-z0-9_+-]+\.dll", name):
        raise RuntimeError(
            "PROTON_OPTISCALER_NAME must be a bare DLL name such as dxgi.dll: "
            + repr(requested))
    return name


def payload_dir(inherited):
    """Where protonfixes installs the OptiScaler payload, if it can be located.

    It is the fixed path protonfixes uses for every upscaler it manages. Proton
    has not run yet when this is called, so the prefix comes from the
    environment: umu and Heroic export WINEPREFIX, Steam exports the compat
    data path with the prefix below it.
    """
    prefix = inherited.get("WINEPREFIX", "").strip()
    if not prefix:
        data = inherited.get("STEAM_COMPAT_DATA_PATH", "").strip()
        prefix = str(Path(data) / "pfx") if data else ""
    if not prefix:
        return None
    return Path(prefix) / "drive_c/windows/system32/umu"


def prefix_ini(inherited):
    """Where protonfixes keeps this game's OptiScaler.ini, if it can be located."""
    payload = payload_dir(inherited)
    return payload / "OptiScaler.ini" if payload else None


def prepend(env, name, value, separator):
    """Put `value` first in a list-valued variable, keeping what was there."""
    parts = [part for part in env.get(name, "").split(separator) if part and part != value]
    env[name] = separator.join([value, *parts])


def freefg_environment(env, layer, inherited):
    """Enable FreeFG's Vulkan pacing layer, which runs in the game process.

    The layer ships in the payload, so the loader is pointed at the prefix;
    pressure-vessel maps the prefix at the same path, so this holds inside the
    Steam Linux Runtime too. The rest is what FreeFG's own installer writes
    into a game's launch options: the wave-size table, and vkd3d-proton's
    no_staggered_submit, which FreeFG's BC250_XEFG_NO_STAGGERED_SUBMIT=0 turns
    off.

    The wrapper forwards most of Intel's exports to bc250_xefg_original.dll by
    module name, and the loader finds that only on the DLL search path.
    FreeFG puts it beside the game's .exe; here it is in OptiScaler's library
    folder, which WINEPATH puts on the Windows PATH, the last place the loader
    looks. Without it OptiScaler gets NULL for each forwarded export and calls
    one while the game creates its swapchain.
    """
    if layer.get("dll_path"):
        prepend(env, "WINEPATH", layer["dll_path"], ";")
    payload = payload_dir(inherited)
    if payload is None:
        sys.stderr.write(
            "bc250-fsr4: no Wine prefix in the environment; FreeFG runs without\n"
            "bc250-fsr4: its frame pacing layer.\n")
        return
    prepend(env, "VK_LAYER_PATH", str(payload / layer["layer_dir"]), ":")
    prepend(env, "VK_INSTANCE_LAYERS", layer["layer"], ":")
    defaulted(env, "XEFG_WAVE_CONFIG", str(payload / layer["wave_config"]))
    if inherited.get("BC250_XEFG_NO_STAGGERED_SUBMIT") != "0":
        parts = [part for part in env.get("VKD3D_CONFIG", "").split(",") if part]
        if "no_staggered_submit" not in parts:
            parts.append("no_staggered_submit")
        env["VKD3D_CONFIG"] = ",".join(parts)


# Written at run time beside files the variants share, so no folder of their
# own takes them along. Removed whenever FreeFG is not the selected variant.
FREEFG_LOGS = ("OptiScaler/BC250-MFG.log", "OptiScaler/BC250-XeFG-fast.log")


# Folders an older package put into prefixes that no variant uses any more, so
# the manifest no longer names them. HelixSR-fsrfg is HelixSR Scaler 1.1.0's
# HelixSR 2.0 folder: Scaler 2.0.0 still looks for it beside its proxy when
# HelixSR/helixsr.dll is missing, and the HelixSR inside it is gone from the
# package.
RETIRED_FOLDERS = ("HelixSR-fsrfg",)
# Files the same way: HelixSR 2.0 as OptiScaler's FidelityFX library (the
# freefg-helixsr default and helixsr-ffx, both gone with it). The prefix's
# OptiScaler.ini still points FfxDx12Path at that DLL and has UpscalerIndex=1,
# so a prefix that has them is treated as a variant switch and starts fresh.
RETIRED_FILES = ("OptiScaler/amd_fidelityfx_dx12.dll", "OptiScaler/helixsr.ini")


def clean_other_variants(config, env, inherited):
    """Remove what another OptiScaler variant left in this prefix.

    Switching PROTON_USE_OPTISCALER makes protonfixes replace the payload, but
    it only removes the files it checksums: .ini files stay (HelixSR Scaler's
    HelixSR/helixsr.ini, for one), as does anything written at run time
    (helixsr.log, FreeFG's logs). A leftover HelixSR folder is not inert
    either: HelixSR Scaler looks for it beside its proxy.

    So every file the manifest lists for some variant but not for the selected
    one is removed, and so is every folder that only other variants use, with
    whatever was written into it, and every folder of RETIRED_FOLDERS and file of
    RETIRED_FILES. Files the selected variant also has are left
    to protonfixes, which replaces them. Nothing outside the payload folder is
    touched, and nothing at all when OptiScaler is off.
    """
    version = env.get("PROTON_USE_OPTISCALER", "0")
    payload = payload_dir(inherited)
    if version == "0" or payload is None or not payload.is_dir():
        return []
    manifest = json.loads((TOOL / config["manifest"]).read_text())
    entries = manifest.get("optiscaler", [])
    selected = next((e for e in entries if e.get("version") == version), None)
    if selected is None:
        # protonfixes refuses the launch and names the version; nothing to do.
        return []

    def folders(names):
        return {str(parent) for name in names
                for parent in Path(name).parents if str(parent) != "."}

    keep = set(selected["md5_hash"])
    stale = set().union(*(set(e["md5_hash"]) for e in entries)) - keep
    if version not in config.get("freefg", {}):
        stale |= set(FREEFG_LOGS)
    stale_folders = (folders(stale) | set(RETIRED_FOLDERS)) - folders(keep)
    # Only the files: their folder is OptiScaler/, which every variant shares.
    stale |= set(RETIRED_FILES) - keep

    root = payload.resolve()

    def inside(path):
        # The names come from our own manifest, but a link planted in a prefix
        # must not send a removal anywhere else.
        parent = path.parent.resolve()
        return parent == root or root in parent.parents

    removed = []
    # Shallowest first: a folder inside one already removed is simply gone.
    for name in sorted(stale_folders, key=lambda n: (n.count("/"), n)):
        path = payload / name
        if path.is_dir() and not path.is_symlink() and inside(path):
            shutil.rmtree(path)
            removed.append(name + "/")
    for name in sorted(stale):
        path = payload / name
        if (path.is_file() or path.is_symlink()) and inside(path):
            path.unlink()
            removed.append(name)
    if removed:
        sys.stderr.write("bc250-fsr4: removed " + str(len(removed))
                         + " leftover file(s) of another OptiScaler variant\n")
    return removed


def seed_once(preset, inherited):
    """Drop the shared preset keys this prefix already has an answer for.

    The shared preset seeds a prefix; it does not govern one. OptiScaler ships
    every key as "auto", so a value that is not "auto" means somebody decided:
    us on the first launch into a fresh prefix, or the player from the OptiScaler
    overlay afterwards. Either way it is left alone from then on, which is what
    lets the overlay's Save Settings survive a restart -- it used to be written
    back over on the next launch. A prefix keeps whatever it has now, and a
    changed default only reaches a fresh install.

    A key that is still "auto", or missing from the prefix's ini, is nobody's
    answer and gets the packaged value. A new packaged OptiScaler re-extracts
    the ini, which resets it to "auto" and re-seeds. Anything unreadable keeps
    the whole preset: being wrong in that direction is a launch that behaves
    like the package says it does.

    What the caller merges after this -- a variant's own entries, the debug keys
    and BC250_OPTISCALER_EXTRA -- is enforced on every launch. A variant switch
    reuses the prefix's ini, which protonfixes does not re-copy, so that wiring
    has to be re-applied here; and a launch option is how a player overrules a
    seed on purpose.
    """
    # A copy in every case: the caller merges the variant layer, the debug keys
    # and BC250_OPTISCALER_EXTRA over the result, and that must not reach back
    # into the loaded config.
    kept = dict(preset)
    ini = prefix_ini(inherited)
    if not ini or not ini.is_file():
        return kept
    parser = configparser.ConfigParser()
    try:
        with ini.open() as stream:
            parser.read_file(stream)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return kept
    for key in list(kept):
        section, _, option = key.partition(".")
        value = parser.get(section, option, fallback="auto").strip().lower()
        if value and value != "auto":
            kept.pop(key)
    return kept




def optiscaler_version(config, requested):
    """Resolve what the caller asked for to a version the manifest pins.

    The manifest carries more than one OptiScaler entry when the package ships
    an opt-in variant, and protonfixes maps a bare "1" to "default", which then
    matches none of them by name and refuses the launch. So "1" is resolved here
    to the version this package actually defaults to, and a variant's short name
    to its pinned version. Anything else is passed through untouched: an exact
    version the manifest does not have must still fail loudly rather than be
    quietly replaced with one that happens to be present.
    """
    if requested in ("0", ""):
        return requested
    if requested in ("1", "default"):
        return config["optiscaler_version"]
    return config.get("optiscaler_aliases", {}).get(requested, requested)


def extra_preset(value):
    """Parse BC250_OPTISCALER_EXTRA into preset entries.

    The preset is rewritten into OptiScaler.ini on every launch, so editing that
    file in a prefix does nothing and answering "is it setting X?" otherwise
    costs a package rebuild. This makes one game's settings a launch option:

        BC250_OPTISCALER_EXTRA="Spoofing.Dxgi=auto;FrameGen.Enabled=true" %command%

    Deliberately not validated here against the shipped OptiScaler.ini, because
    protonfixes already refuses to launch on a key that build does not define --
    a typo stops the game with the offending name rather than being ignored.
    """
    extra = {}
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        key, separator, setting = part.partition("=")
        key = key.strip()
        if not separator or "." not in key:
            raise RuntimeError(
                "BC250_OPTISCALER_EXTRA entries look like Section.Option=value: "
                + repr(part))
        extra[key] = setting.strip()
    return extra


def environment(config, inherited, *, game, menu=None, known=None):
    env = dict(inherited)
    # /usr is read-only, so Proton's own imports cannot drop __pycache__ beside
    # them. Python tolerates that silently, but saying so avoids the attempts.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in UNSHIPPED + OWNED:
        env.pop(name, None)

    # Keep every invocation in local mode. In particular, CachyOS's stock
    # provider setup also runs for utilities; dropping the manifest there would
    # make a path query fetch its remote upscaler manifest.
    env["PROTON_UPSCALER_MANIFEST"] = str(TOOL / config["manifest"])
    if not game:
        # Inherited game settings must not inject payloads into utility calls.
        env["PROTON_USE_OPTISCALER"] = "0"
        env["PROTON_FSR4_UPGRADE"] = "0"
        return env

    # FSR4 and OptiScaler are what this tool is for, so they default to on --
    # but they stay the user's call. get_version() maps both "0" and "1" to
    # 'default', and the pinned manifest holds exactly one entry per upscaler,
    # so an explicit "0" cleanly turns a feature off and an explicit "1" still
    # resolves to what we ship. A specific version we do not have fails the
    # launch with a message naming it, rather than running something unpinned.
    # An anti-cheat game gets the documented opt-out as its default instead:
    # both payload steps off, still overridable by anyone who insists.
    guard = anticheat_reason(inherited)
    ignored = anticheat_ignored(inherited) if guard else None
    if ignored:
        sys.stderr.write(
            "bc250-fsr4: anti-cheat detected (" + guard + "), but the guard is\n"
            "bc250-fsr4: switched off by " + ignored + ": FSR4 and OptiScaler\n"
            "bc250-fsr4: stay on. This risks a ban, and anti-cheat may refuse to start.\n")
        guard = None
    defaulted(env, "PROTON_FSR4_UPGRADE",
              "0" if guard else config["provider_version"])
    if guard and env["PROTON_FSR4_UPGRADE"] == "0":
        sys.stderr.write(
            "bc250-fsr4: anti-cheat detected (" + guard + "); FSR4 and OptiScaler\n"
            "bc250-fsr4: are off for this game. Injecting into a protected game\n"
            "bc250-fsr4: risks a ban. To accept that: BC250_FSR4_IGNORE_ANTICHEAT=1\n"
            "bc250-fsr4: for this game, or touch ~/.config/bc250-fsr4/ignore-anticheat\n"
            "bc250-fsr4: for every game.\n")
    # The documented opt-out disables the package's default proxy as well.
    # Otherwise OptiScaler can still discover a provider retained in a prefix.
    defaulted(env, "PROTON_USE_OPTISCALER",
              "0" if env["PROTON_FSR4_UPGRADE"] == "0" else config["optiscaler_version"])
    env["PROTON_USE_OPTISCALER"] = optiscaler_version(config, env["PROTON_USE_OPTISCALER"])

    # Not shipped, and explicitly off rather than merely absent: leaving it to
    # the default would let a future Proton decide.
    env["PROTON_MLFG_UPGRADE"] = "0"
    # Xalia inherits the global proxy below and can keep a closed game alive.
    env["PROTON_USE_XALIA"] = "0"

    proxy = proxy_name(inherited.get("PROTON_OPTISCALER_NAME"), config["proxy"])
    env["PROTON_OPTISCALER_NAME"] = proxy
    if env["PROTON_USE_OPTISCALER"] != "0":
        load_native(env, proxy)

    preset = seed_once(config["preset"], inherited)
    # A variant's own entries (HelixSR's library paths), only when that pinned
    # version is the one being launched -- and enforced every launch, not seeded
    # (see seed_once: a variant switch reuses the prefix's ini). Debug and
    # BC250_OPTISCALER_EXTRA go on top.
    # A variant's own entries, only when that pinned version is the one being
    # launched. The wiring (library paths, the upscaler pick) is enforced every
    # launch -- a variant switch reuses the prefix's ini (see seed_once). Its
    # frame-gen keys are seeded on that variant's first launch only: re-forcing
    # them is what undid an overlay "FG off" + Save at the next start.
    preset.update(config.get("optiscaler_variant_preset", {}).get(env["PROTON_USE_OPTISCALER"], {}))
    preset.update(seed_once(config.get("optiscaler_variant_seed", {}).get(env["PROTON_USE_OPTISCALER"], {}),
                            inherited))
    if known:
        # The game's known working settings (apply_game_preset): on a fresh ini
        # or when the player forces them, over the seeds, under the menu.
        preset.update(known)
    if menu:
        # The player chose in the menu. A decision for this game, like a launch
        # option, so it goes on top of the seed filter.
        preset.update(menu)
    # null drops a shared key the variant's OptiScaler does not have: protonfixes
    # refuses a launch on a key missing from the ini, and FreeFG's OptiScaler
    # writes its ini without the old FSR.Fsr4ForceModel.
    preset = {key: value for key, value in preset.items() if value is not None}
    layer = config.get("freefg", {}).get(env["PROTON_USE_OPTISCALER"])
    if layer:
        freefg_environment(env, layer, inherited)
    # Merged after the seed filter on purpose: a launch option is an
    # explicit decision for this game, so it wins over whatever the prefix holds.
    if inherited.get("BC250_FSR4_DEBUG") == "1":
        preset.update({"Log.LogToFile": "true", "FSR.Fsr4EnableWatermark": "true"})
        env["PROTON_LOG"] = "1"
    preset.update(extra_preset(inherited.get("BC250_OPTISCALER_EXTRA", "")))
    env["PROTON_OPTISCALER_CONFIG"] = ";".join(k + "=" + v for k, v in preset.items())

    # Belt and braces since the preset turned Spoofing.VulkanExtensionSpoofing
    # off: OptiScaler used to advertise these to unlock a game's DLSS input
    # path, and vkd3d's separate D3D12 device then failed to create -- the
    # "DX12 not supported" report. Nothing should advertise them now, but the
    # BC-250 cannot use them either way, so the exclusion stays. Keep any
    # exclusions the caller already asked for.
    disabled = env.get("VKD3D_DISABLE_EXTENSIONS", "")
    env["VKD3D_DISABLE_EXTENSIONS"] = ";".join(
        part
        for part in (disabled, "VK_NVX_binary_import", "VK_NVX_image_view_handle")
        if part
    )
    return env


def variant_files(config):
    """Each pinned OptiScaler version and the payload files protonfixes installs for it."""
    entries = json.loads((TOOL / config["manifest"]).read_text()).get("optiscaler", [])
    return {e.get("version"): set(e.get("md5_hash", {})) for e in entries}


def installed_variant(config, inherited):
    """The pinned version this prefix was last launched with, or None.

    protonfixes records it per installed file in <compatdata>/upscaler_files. A
    version this package does not pin (an older package's) is None: that prefix
    is switched, and so starts fresh, on its next launch whatever is picked.
    """
    data = inherited.get("STEAM_COMPAT_DATA_PATH", "").strip()
    if not data:
        return None
    try:
        tracked = json.loads((Path(data) / "upscaler_files").read_text())["opti_files"]
        versions = [item.get("version") for item in tracked.values()]
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None
    if not versions:
        return None
    version = max(set(versions), key=versions.count)
    return version if version in variant_files(config) else None


# The variants the menu offers, by the short names PROTON_USE_OPTISCALER takes.
MENU_VARIANTS = ("freefg-hlxfsr4", "freefg", "helixsr", "fsr412f", "hlxfsr4")


def menu_names(config):
    """Pinned version -> its menu name, for the variants the menu offers."""
    aliases = config.get("optiscaler_aliases", {})
    return {aliases[name]: name for name in MENU_VARIANTS if name in aliases}


# Where Steam Linux Runtime's pressure-vessel keeps its client inside the
# container, and beside the runtime outside it.
LAUNCH_CLIENT = "steam-runtime-launch-client"


def launch_client(inherited):
    found = shutil.which(LAUNCH_CLIENT)
    if found:
        return found
    candidates = [Path("/run/pressure-vessel/pv-from-host/bin") / LAUNCH_CLIENT]
    for tool in inherited.get("STEAM_COMPAT_TOOL_PATHS", "").split(":"):
        if tool:
            candidates.append(Path(tool) / "pressure-vessel/bin" / LAUNCH_CLIENT)
    return next((str(c) for c in candidates if c.is_file()), None)


# What the menu needs from the launch when it runs outside the container.
MENU_ENV = ("STEAM_COMPAT_DATA_PATH", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
            "XDG_RUNTIME_DIR", "SteamAppId", "SteamGameId", "PROTON_OPTISCALER_MENU",
            "PROTON_USE_OPTISCALER", "BC250_MENU_INSTALLED", "BC250_MENU_DEFAULT",
            "BC250_MENU_GAME_PRESET")


def menu_choice(config, inherited):
    """Ask the first-launch menu which variant to run and what to change.

    Returns (variant, change, switched, force). force is "matching" or
    "everything" when the player ticked "Force apply known settings", else None.
    variant is a short name, or None when
    the launch already says (PROTON_USE_OPTISCALER, an anti-cheat game) or the
    prefix has no answer of its own yet. It never blocks a launch: no display, no
    gi/GTK4/SDL3, any error, and the game starts on the prefix's current variant.
    """
    import subprocess
    menu = TOOL / "bc250-fsr4-menu.py"
    prefix = inherited.get("STEAM_COMPAT_DATA_PATH", "").strip()
    if not prefix or not menu.is_file():
        return None, {}, False, None
    if inherited.get("PROTON_USE_OPTISCALER", "").strip() or inherited.get("PROTON_FSR4_UPGRADE") == "0":
        return None, {}, False, None
    if anticheat_reason(inherited) and not anticheat_ignored(inherited):
        return None, {}, False, None
    names = menu_names(config)
    env = dict(inherited)
    env["BC250_MENU_INSTALLED"] = names.get(installed_variant(config, inherited), "")
    env["BC250_MENU_DEFAULT"] = names.get(config["optiscaler_version"], "")
    # The SLR and GE packages run this inside Steam Linux Runtime 4
    # ("require_tool_appid" 4183110), which has no python-gobject and no GTK4.
    # Steam's own launcher service runs the menu beside the Steam client instead,
    # where the host's python, GTK4 and SDL3 are. The native package runs on the
    # host and needs no hop.
    command = [sys.executable, str(menu)]
    if Path("/run/pressure-vessel").is_dir():
        client = launch_client(inherited)
        if not client:
            return None, {}, False, None
        command = [client, "--alongside-steam",
                   *("--pass-env=" + name for name in MENU_ENV), "--", "python3", str(menu)]

    def ask(args):
        try:
            done = subprocess.run([*command, *args], env=env, capture_output=True, text=True)
        except (OSError, ValueError):
            return {}
        sys.stderr.write(done.stderr)
        if done.returncode != 0:
            return {}
        return dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)

    decided = ask(["--decide"])
    current = decided.get("current") or None
    if decided.get("show") != "1":
        return current, {}, False, None
    choice = ask([])
    if not choice.get("preset"):
        return current, {}, False, None
    change = dict(part.split("=", 1) for part in choice.get("changed", "").split(";") if "=" in part)
    force = choice.get("apply_preset") if choice.get("apply_preset") in PRESET_MODES else None
    return choice["preset"], change, choice.get("switched") == "1", force


def variant_switched(config, inherited):
    """True when this prefix still carries files only some other variant has.

    That is a switch, and a switch means starting fresh: the prefix's shared
    OptiScaler.ini goes, protonfixes re-copies a missing one, and the new variant
    seeds from scratch. This is the disk test that replaced the 1122e656 key reset,
    and it holds for every switch, made in the menu or by launch option.
    """
    requested = inherited.get("PROTON_USE_OPTISCALER", "").strip() or config["optiscaler_version"]
    version = optiscaler_version(config, requested)
    payload = payload_dir(inherited)
    if version == "0" or not payload or not payload.is_dir():
        return False
    files = variant_files(config)
    if version not in files:
        return False
    if any((payload / name).exists() for name in RETIRED_FILES if name not in files[version]):
        return True
    for name, theirs in files.items():
        if name == version or not theirs:
            continue
        if any((payload / other).exists() for other in theirs - files[version]):
            return True
    return False


def start_fresh_on_switch(config, inherited, switched=False):
    """Remove the prefix's OptiScaler.ini when this launch switches variant.

    protonfixes re-copies a missing ini, so the new variant seeds from scratch.
    Runs before environment() reads the ini, or the leaving variant's answers
    (FreeFG's FrameGen.Enabled=true) would count as the player's.
    """
    if not (switched or variant_switched(config, inherited)):
        return False
    ini = prefix_ini(inherited)
    if ini and ini.is_file():
        ini.unlink()
    return True


# ------------------------------------------------------------ per-game presets
#
# Known working OptiScaler settings per game: FreeFG's BC-250 recipes on top of
# the OptiScaler wiki, built every night into one file by
# scripts/build-game-presets.py and published on its own release, so a new
# setting never waits for (or triggers) a Proton build. Data only: it can set
# keys this build's OptiScaler.ini defines, a proxy name and launch options,
# never a file or a library. Nothing here may stop a game from starting.

PRESETS_URL = ("https://github.com/MastaG/linux-cachyos-bc250/releases/download/"
               "bc250-game-presets/game-presets.json.gz")
# A day between checks: the file changes at most nightly, and a launch should
# not wait on the network more often than that.
PRESETS_MAX_AGE = 24 * 3600
PRESETS_TIMEOUT = 3
PRESET_MODES = ("matching", "everything")
# The per-prefix record of what was applied, beside the menu's own file.
PRESET_RECORD = "bc250-game-preset.json"
# Package wiring a preset never changes, whatever its source: the libraries and
# plugins the payload points at, which upscaler and output a variant uses, the
# player's frame-generation switch, logging, and the overlay that changes it all.
PRESET_LOCKED = ("libraries.", "plugins.", "upscalers.", "log.", "menu.",
                 "framegen.fgoutput", "framegen.enabled", "fsr.upscalerindex")
# FreeFG's BC-250 recipes were tested with their own library paths (Cyberpunk's
# own libxess.dll), so for them only those are allowed.
PRESET_TESTED_LIBRARIES = ("libraries.xesspath",)


def presets_cache(inherited):
    base = inherited.get("XDG_CACHE_HOME", "").strip()
    if not base and inherited.get("HOME", "").strip():
        base = str(Path(inherited["HOME"]) / ".cache")
    return Path(base) / "bc250-fsr4" / "game-presets.json.gz" if base else None


def parse_presets(body):
    import gzip
    data = json.loads(gzip.decompress(body))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("games"), list):
        raise ValueError("not a game preset database")
    return data


def read_presets(path):
    return parse_presets(path.read_bytes())


def load_presets(inherited, now=None):
    """The preset database: the cached copy, refreshed at most once a day.

    A failed download keeps the cached copy, and no copy at all means no
    presets; either way the launch goes on. BC250_GAME_PRESETS_FILE reads a
    local file instead (testing a database before it is published)."""
    import time
    local = inherited.get("BC250_GAME_PRESETS_FILE", "").strip()
    if local:
        return read_presets(Path(local))
    cache = presets_cache(inherited)
    if cache is None:
        return None
    now = time.time() if now is None else now
    try:
        fresh = now - cache.stat().st_mtime < PRESETS_MAX_AGE
    except OSError:
        fresh = False
    if not fresh:
        try:
            import urllib.request
            with urllib.request.urlopen(PRESETS_URL, timeout=PRESETS_TIMEOUT) as response:
                body = response.read(16 << 20)
            parse_presets(body)  # never replace a good copy with a broken one
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(".part")
            temporary.write_bytes(body)
            temporary.replace(cache)
        except Exception as error:  # the network, a proxy, a broken file: all the same here
            sys.stderr.write("bc250-fsr4: game presets not refreshed (" + str(error) + ")\n")
            try:
                os.utime(cache)  # the next try is tomorrow, not the next launch
            except OSError:
                pass
    try:
        return read_presets(cache)
    except (OSError, ValueError, EOFError):
        return None


def steam_title(inherited):
    """The game's name from Steam's appmanifest, beside the install folder."""
    install = inherited.get("STEAM_COMPAT_INSTALL_PATH", "").strip()
    appid = inherited.get("SteamAppId", "").strip()
    if not install or not appid.isdigit():
        return None
    manifest = Path(install).parent.parent / ("appmanifest_" + appid + ".acf")
    try:
        found = re.search(r'^\s*"name"\s*"(.*)"\s*$', manifest.read_text(errors="replace"), re.M)
    except OSError:
        return None
    return found.group(1) if found else None


def norm_title(title):
    """As scripts/build-game-presets.py norm(): the two must agree."""
    title = re.sub(r"[™®©'’`]", "", title.lower()).replace("&", " and ")
    # Ragnarök and Ragnarok are one game: fold accents to their letter.
    title = "".join(c for c in unicodedata.normalize("NFKD", title)
                    if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", title).split())


def find_game(presets, arguments, inherited):
    """This launch's entry: by Steam app id, then the .exe, then the title."""
    games = presets.get("games", [])
    appid = inherited.get("SteamAppId", "").strip()
    if appid not in ("", "0"):
        for game in games:
            if appid in game.get("match", {}).get("steam", []):
                return game
    exe = next((Path(a.replace("\\", "/")).name.lower() for a in arguments[1:]
                if a.lower().endswith(".exe")), None)
    if exe:
        for game in games:
            if exe in game.get("match", {}).get("exe", []):
                return game
    title = steam_title(inherited)
    if title:
        key = norm_title(title)
        for game in games:
            if key in game.get("match", {}).get("title", []):
                return game
    return None


def variant_context(config, version, settings):
    """What this launch is, in the vocabulary of the wiki's conditions."""
    seeded = {**config.get("optiscaler_variant_preset", {}).get(version, {}),
              **config.get("optiscaler_variant_seed", {}).get(version, {})}
    names = {k.lower(): v for k, v in seeded.items() if v is not None}
    return {
        "gpu": "amd", "os": "linux", "upscaler": "fsr4",
        "fg_output": str(names.get("framegen.fgoutput", "fsrfg")).lower(),
        "fg_input": str(settings.get("framegen.fginput", names.get("framegen.fginput", "upscaler"))).lower(),
        "variant": menu_names(config).get(version, version),
    }


def condition_met(when, context):
    """True when every condition holds for this launch. A condition this does not
    know (a game patch, a mod, "if it crashes") is not met: "everything" is how a
    player applies those."""
    for key, value in (when or {}).items():
        value = str(value).lower()
        if key == "gpu":
            if not re.search(r"\bamd\b", value) or "without" in value:
                return False
        elif key in ("os", "upscaler", "fg_output", "fg_input"):
            if context[key] not in re.split(r"[\s,/]+", value):
                return False
        else:
            return False
    return True


def game_preset(config, version, game, mode):
    """(settings, launch options, proxy) a preset gives this variant.

    "matching": FreeFG's BC-250 settings, and the wiki's that are unconditional or
    whose condition holds here (AMD, Linux, FSR4, this variant's frame-gen input
    and output), leaving out what OptiScaler already applies itself.
    "everything": every setting the game has, conditions ignored, but where
    several values are given for one key the one that matches here wins.
    Either way only keys this build's OptiScaler.ini defines -- protonfixes
    refuses a launch on any other -- and never the package's wiring."""
    defined = {key.lower(): key for key in config.get("optiscaler_ini_keys", {}).get(version, [])}
    avoid = {key.lower() for key in game.get("avoid", [])}
    variant = menu_names(config).get(version, version)
    candidates = {}
    for item in game.get("settings", []):
        key, value = item.get("key", ""), str(item.get("value", ""))
        lower = key.lower()
        tested = item.get("source") == "bc250"
        if lower not in defined or lower in avoid or ";" in value or "\n" in value:
            continue
        if lower.startswith(PRESET_LOCKED) and not (tested and lower in PRESET_TESTED_LIBRARIES):
            continue
        if item.get("variants") and variant not in item["variants"]:
            continue
        candidates.setdefault(lower, []).append(item)
    chosen = {}
    # FreeFG's frame-gen input decides the context the wiki's conditions see.
    context = variant_context(config, version, {
        k: v[0]["value"] for k, v in candidates.items()
        if k == "framegen.fginput" and v[0].get("source") == "bc250"})

    def rank(item):
        if item.get("source") == "bc250":
            return 0
        if item.get("auto"):
            return 3  # OptiScaler sets it itself
        return 1 if condition_met(item.get("when"), context) else 2

    for lower, items in candidates.items():
        best = min(items, key=rank)
        if mode == "everything" or rank(best) < 2:
            chosen[defined[lower]] = str(best["value"])
    arguments = [a["arg"] for a in game.get("launch_args", [])
                 if a.get("source") == "bc250" or mode == "everything"
                 or condition_met(a.get("when"), context)]
    # The wiki's Filename row names what its tester confirmed working. The
    # package's winmm.dll is only the name the first BC-250 build happened to
    # use, so when the page does not list it, the first name it does list wins
    # -- unless this build reserves that name (reserved_proxy()).
    proxies = game.get("proxy", [])
    proxy = None
    if proxies and config.get("proxy", "").lower() not in proxies:
        proxy = next((name for name in proxies if reserved_proxy(config, name) is None), None)
    return chosen, arguments, proxy


def reserved_proxy(config, name):
    """None when a preset may load OptiScaler as `name` in this build, else name.

    A local build can keep DLL names for the player's own loaders
    (build-proton-tarball.sh --optiscaler-reserve version.dll,winmm.dll): a
    preset that asks for one of them gets the build's own proxy instead. Only
    presets are held to this; PROTON_OPTISCALER_NAME is the player's own word."""
    reserved = {n.lower() for n in config.get("reserved_proxies", [])}
    return name if name and name.lower() in reserved else None


def preset_record_path(inherited):
    data = inherited.get("STEAM_COMPAT_DATA_PATH", "").strip()
    return Path(data) / PRESET_RECORD if data else None


def read_preset_record(inherited):
    path = preset_record_path(inherited)
    try:
        record = json.loads(path.read_text()) if path else None
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def describe_game(game):
    tested = "tested on a BC-250" if game.get("bc250") else "from the OptiScaler wiki"
    return game.get("title", "this game") + " (" + tested + ")"


def apply_game_preset(config, version, presets, arguments, inherited, force=None):
    """This launch's preset layer, its launch options and proxy name.

    Applied in full on a fresh OptiScaler.ini -- a new prefix, or a variant
    switch, which starts fresh -- in the mode the prefix last used ("matching"
    unless the player forced "everything"), and whenever the player forces it.
    Otherwise the INI keeps what it has, player edits included, and only the
    launch options and proxy name, which live nowhere else, are applied again.
    Returns ({}, [], None) whenever anything is missing or wrong."""
    nothing = ({}, [], None)
    choice = (inherited.get("BC250_GAME_PRESET", "") or "").strip().lower()
    if choice == "0" or version in ("0", "") or presets is None:
        return nothing
    force = force or (choice if choice in PRESET_MODES else None)
    game = find_game(presets, arguments, inherited)
    if game is None:
        return nothing
    record = read_preset_record(inherited)
    if record and record.get("title") != game.get("title"):
        record = None
    ini = prefix_ini(inherited)
    fresh = ini is not None and not ini.is_file()
    if force or fresh:
        mode = force or (record or {}).get("mode", "matching")
        if mode not in PRESET_MODES:
            mode = "matching"
        settings, launch, proxy = game_preset(config, version, game, mode)
        record = {"title": game.get("title"), "mode": mode, "variant": version,
                  "database": presets.get("content_sha256"), "settings": settings,
                  "launch_args": launch, "proxy": proxy}
        path = preset_record_path(inherited)
        if path:
            path.write_text(json.dumps(record, indent=1) + "\n")
        sys.stderr.write("bc250-fsr4: applied the " + mode + " preset for " + describe_game(game)
                         + ": " + (", ".join(k + "=" + v for k, v in settings.items()) or "no INI keys")
                         + (" " + " ".join(launch) if launch else "") + "\n")
        return settings, launch, proxy
    if not record:
        return nothing
    # A key the variant enforces every launch would undo the preset's value at
    # the next start; those few go in again. Everything else stays as the ini has it.
    enforced = {k.lower() for k in config.get("optiscaler_variant_preset", {}).get(version, {})}
    defined = {k.lower() for k in config.get("optiscaler_ini_keys", {}).get(version, [])}
    again = {k: v for k, v in record.get("settings", {}).items() if k.lower() in enforced & defined}
    return again, list(record.get("launch_args", [])), record.get("proxy")


def with_launch_options(arguments, extra):
    """Proton's arguments with the preset's game options appended once."""
    if not extra or not arguments or arguments[0] not in ("run", "waitforexitandrun"):
        return arguments
    have = {a.lower() for a in arguments[2:]}
    return arguments + [a for a in extra if a.lower() not in have]


def main():
    config = json.loads((TOOL / "bc250-fsr4-config.json").read_text())
    game = game_launch(sys.argv[1:], os.environ)
    presets, found = None, None
    if game:
        try:
            presets = load_presets(os.environ)
            found = find_game(presets, sys.argv[1:], os.environ) if presets else None
        except Exception as error:
            sys.stderr.write("bc250-fsr4: game presets unavailable (" + str(error) + ")\n")
    os.environ.pop("BC250_MENU_GAME_PRESET", None)
    if found is not None:
        os.environ["BC250_MENU_GAME_PRESET"] = describe_game(found)
    variant, change, menu_switched, force = menu_choice(config, os.environ) if game else (None, {}, False, None)
    if variant == "off":
        # The menu's "No upscaling" is the documented opt-out: no FSR4 provider,
        # and so no OptiScaler either (see environment()).
        os.environ["PROTON_FSR4_UPGRADE"] = "0"
        os.environ["PROTON_USE_OPTISCALER"] = "0"
    elif variant:
        os.environ["PROTON_USE_OPTISCALER"] = variant
    if game:
        start_fresh_on_switch(config, os.environ, menu_switched)
    env = environment(config, os.environ, game=game, menu=change)
    arguments = sys.argv[1:]
    if found is not None:
        # After the switch check, which decides whether the ini starts fresh,
        # and after environment(), which decides the variant that runs.
        try:
            layer, launch, proxy = apply_game_preset(
                config, env.get("PROTON_USE_OPTISCALER", "0"), presets, arguments, os.environ, force)
        except Exception as error:
            sys.stderr.write("bc250-fsr4: game preset not applied (" + str(error) + ")\n")
            layer, launch, proxy = {}, [], None
        if reserved_proxy(config, proxy):
            # A record written before the name was reserved.
            proxy = None
        if proxy and not os.environ.get("PROTON_OPTISCALER_NAME", "").strip():
            os.environ["PROTON_OPTISCALER_NAME"] = proxy
        if layer or proxy:
            if any(k.lower() == "framegen.fginput" for k in layer):
                # The menu's FG wiring is a default, not the player's pick.
                change = {k: v for k, v in change.items() if k.lower() != "framegen.fginput"}
            env = environment(config, os.environ, game=game, menu=change, known=layer)
        arguments = with_launch_options(arguments, launch)
    if game:
        # Before Proton runs protonfixes, which then installs the selected
        # variant over a folder with no other variant's files in it.
        clean_other_variants(config, env, os.environ)
    # Replace this process so Steam keeps the pid it started and every inherited
    # descriptor, exactly as if it had run Proton directly.
    proton = str(TOOL / config["proton"])
    os.execve(proton, [proton, *arguments], env)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit("BC250 FSR4: " + str(error))
