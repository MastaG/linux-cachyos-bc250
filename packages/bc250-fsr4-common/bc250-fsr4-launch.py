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

import json
import os
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
# silently swaps in an unverified DLL.
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
    defaulted(env, "PROTON_FSR4_UPGRADE", config["provider_version"])
    # The documented opt-out disables the package's default proxy as well.
    # Otherwise OptiScaler can still discover a provider retained in a prefix.
    defaulted(env, "PROTON_USE_OPTISCALER",
              "0" if env["PROTON_FSR4_UPGRADE"] == "0" else config["optiscaler_version"])

    # Not shipped, and explicitly off rather than merely absent: leaving it to
    # the default would let a future Proton decide.
    env["PROTON_MLFG_UPGRADE"] = "0"
    # Xalia inherits the global proxy below and can keep a closed game alive.
    env["PROTON_USE_XALIA"] = "0"

    env["PROTON_OPTISCALER_NAME"] = config["proxy"]
    if env["PROTON_USE_OPTISCALER"] != "0":
        load_native(env, config["proxy"])

    preset = dict(config["preset"])
    if inherited.get("BC250_FSR4_DEBUG") == "1":
        preset.update({"Log.LogToFile": "true", "FSR.Fsr4EnableWatermark": "true"})
        env["PROTON_LOG"] = "1"
    env["PROTON_OPTISCALER_CONFIG"] = ";".join(k + "=" + v for k, v in preset.items())

    # OptiScaler advertises these to unlock a game's DLSS input path. The BC-250
    # cannot use them in vkd3d's separate D3D12 device, whose creation otherwise
    # fails once Vulkan extension spoofing is on independently of vendor
    # spoofing. Keep any exclusions the caller already asked for.
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
