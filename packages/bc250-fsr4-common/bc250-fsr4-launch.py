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

    Getting this wrong applies the whole FSR4 environment to a utility call.
    """
    return bool(
        arguments
        and arguments[0] in ("run", "waitforexitandrun")
        and any(
            inherited.get(name, "") not in ("", "0")
            for name in ("SteamAppId", "SteamGameId")
        )
    )


def defaulted(env, name, value):
    """Set `name` unless the caller chose something. Empty counts as unset."""
    env[name] = env.get(name, "").strip() or value


def environment(config, inherited, *, game):
    env = dict(inherited)
    # /usr is read-only, so Proton's own imports cannot drop __pycache__ beside
    # them. Python tolerates that silently, but saying so avoids the attempts.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if not game:
        # Path conversion, installers and GPU queries want ordinary Proton, even
        # when a game identity happens to be inherited from the session.
        return env

    for name in UNSHIPPED + OWNED:
        env.pop(name, None)

    # FSR4 and OptiScaler are what this tool is for, so they default to on --
    # but they stay the user's call. get_version() maps both "0" and "1" to
    # 'default', and the pinned manifest holds exactly one entry per upscaler,
    # so an explicit "0" cleanly turns a feature off and an explicit "1" still
    # resolves to what we ship. A specific version we do not have fails the
    # launch with a message naming it, rather than running something unpinned.
    defaulted(env, "PROTON_USE_OPTISCALER", config["optiscaler_version"])
    defaulted(env, "PROTON_FSR4_UPGRADE", config["provider_version"])

    # Not shipped, and explicitly off rather than merely absent: leaving it to
    # the default would let a future Proton decide.
    env["PROTON_MLFG_UPGRADE"] = "0"
    # Xalia inherits the global proxy below and can keep a closed game alive.
    env["PROTON_USE_XALIA"] = "0"

    env["PROTON_UPSCALER_MANIFEST"] = str(TOOL / config["manifest"])
    env["PROTON_OPTISCALER_NAME"] = config["proxy"]

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
