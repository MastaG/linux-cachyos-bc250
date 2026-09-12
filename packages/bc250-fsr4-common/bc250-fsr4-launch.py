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
import sys
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
# game resolves to OptiScaler. See proxy_name().
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

    Unlike everything else in OWNED this changes no pinned file: the payload is
    the same either way, so the worst a wrong name can do is leave OptiScaler
    unloaded. It is still checked for shape, because it reaches Wine's loader as
    a name to match and a path fragment has no business there.
    """
    name = (requested or "").strip() or default
    if not name.lower().endswith(".dll"):
        name += ".dll"
    if not re.fullmatch(r"[A-Za-z0-9_+-]+\.dll", name):
        raise RuntimeError(
            "PROTON_OPTISCALER_NAME must be a bare DLL name such as dxgi.dll: "
            + repr(requested))
    return name


def prefix_ini(inherited):
    """Where protonfixes keeps this game's OptiScaler.ini, if it can be located.

    protonfixes writes it beside the payload it installs, at the fixed path it
    uses for every upscaler it manages. Proton has not run yet when this is
    called, so the prefix comes from the environment: umu and Heroic export
    WINEPREFIX, Steam exports the compat data path with the prefix below it.
    """
    prefix = inherited.get("WINEPREFIX", "").strip()
    if not prefix:
        data = inherited.get("STEAM_COMPAT_DATA_PATH", "").strip()
        prefix = str(Path(data) / "pfx") if data else ""
    if not prefix:
        return None
    return Path(prefix) / "drive_c/windows/system32/umu/OptiScaler.ini"


def seed_once(preset, config, inherited):
    """Drop the seeded keys once this prefix has an answer of its own.

    Most of the preset is enforced on every launch on purpose: it is what makes
    a launch reproducible from its launch options, with no invisible state in a
    prefix deciding what you get. The spoofing keys are the exception, because
    they are the ones a player legitimately wants to toggle for one game -- and
    toggling them in the OptiScaler overlay used to do nothing, since the next
    launch wrote the preset back over the top.

    OptiScaler ships every one of them as "auto", so a value that is not "auto"
    means somebody decided: us on the first launch into a fresh prefix, or the
    player afterwards. Either way it is left alone from then on. A new packaged
    OptiScaler re-extracts the ini, which resets it to "auto" and re-seeds.

    Anything unreadable keeps the enforced value. Being wrong in that direction
    is a launch that behaves like the package says it does.
    """
    # A copy in every case: the caller merges debug and BC250_OPTISCALER_EXTRA
    # over the result, and that must not reach back into the loaded config.
    kept = dict(preset)
    keys = config.get("seed_once", [])
    ini = prefix_ini(inherited) if keys else None
    if not ini or not ini.is_file():
        return kept
    parser = configparser.ConfigParser()
    try:
        with ini.open() as stream:
            parser.read_file(stream)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return kept
    for key in keys:
        section, _, option = key.partition(".")
        value = parser.get(section, option, fallback="auto").strip().lower()
        if value and value != "auto":
            kept.pop(key, None)
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


def environment(config, inherited, *, game):
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
    defaulted(env, "PROTON_FSR4_UPGRADE",
              "0" if guard else config["provider_version"])
    if guard and env["PROTON_FSR4_UPGRADE"] == "0":
        sys.stderr.write(
            "bc250-fsr4: anti-cheat detected (" + guard + "); FSR4 and OptiScaler\n"
            "bc250-fsr4: are off for this game. Injecting into a protected game\n"
            "bc250-fsr4: risks a ban. PROTON_FSR4_UPGRADE=1 overrides this.\n")
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

    preset = seed_once(config["preset"], config, inherited)
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


def main():
    config = json.loads((TOOL / "bc250-fsr4-config.json").read_text())
    game = game_launch(sys.argv[1:], os.environ)
    env = environment(config, os.environ, game=game)
    # Replace this process so Steam keeps the pid it started and every inherited
    # descriptor, exactly as if it had run Proton directly.
    proton = str(TOOL / config["proton"])
    os.execve(proton, [proton, *sys.argv[1:]], env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit("BC250 FSR4: " + str(error))
