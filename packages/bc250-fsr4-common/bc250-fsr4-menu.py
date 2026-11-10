#!/usr/bin/env python3
"""BC-250 OptiScaler first-launch menu.

GTK4 draws the window (mouse and keyboard); the gamepad is read directly through
SDL3's HIDAPI, because Steam hides controllers from SDL in a game's launch
(SDL_GAMECONTROLLER_IGNORE_DEVICES) and Proton gets its pad over Steam IPC, not
from a device a second process could share. This process lifts the filter for
itself only, so the game's own layout is untouched. Verified on cachyosusb-x8664
in Gaming Mode and on KDE Plasma: Steam Controller and PS5 pad both work, no
double inputs, mouse and keyboard work.

Prints the choice as key=value lines on stdout. Exit 0 = a choice was made; any
other exit = no choice, and the caller keeps the current one and starts the game.
Exit 3 = the menu cannot appear (no display, or gi/GTK4/SDL3 missing).

The state rules (owner's decisions, 2026-10-26, upscalers 2026-11-08): single
choice among the upscalers, the one the prefix's OptiScaler.ini has pre-selected
(OptiScaler's overlay writes it on Save Settings, so a pick there shows here);
picking one changes only that key; the frame-generation row shows the
prefix's real current state and is written only when the player changes it;
switching variant means starting fresh (the launcher removes the prefix's
OptiScaler.ini, protonfixes re-copies it); "Save selection" skips the menu from
then on; PROTON_OPTISCALER_MENU=1 shows it again and clears the save, and
PROTON_OPTISCALER_MENU=0 skips it for that launch and keeps the prefix's
choice. A new prefix starts on No upscaling (owner, 2026-11-10), unless the
player's settings file says otherwise (the launcher reads it and passes
BC250_MENU_DEFAULT, BC250_MENU_PREVIOUS and BC250_MENU_AUTO). No timeout: the
menu waits for a choice. Never block a launch.
"""
import configparser
import ctypes
import json
import os
import sys

# Since 2026-11-08 (owner) one payload carries every upscaler, and the menu
# picks the upscaler: [Upscalers] Dx12Upscaler of the prefix's OptiScaler.ini,
# the key OptiScaler's own overlay writes on Save Settings, so a pick made there
# shows here on the next launch. value (as the ini has it), label, sub-label, in
# window order. The two HLX DLSS networks share a row with a choice of model
# (owner); the overlay lists them apart, as hlx-dlss and HLX DLSS Preset K.
VARIANT = "freefg-all"
HLX_DLSS_E, HLX_DLSS_K = "hlx-dlss", "HLX DLSS Preset K"
UPSCALERS = [
    ("ffx", "FreeFG + HLX FSR 4", "HelixSR 3.3.0's HLX FSR 4: AMD's FSR 4 network on HelixSR's pipeline"),
    (HLX_DLSS_E, "FreeFG + HLX DLSS Model E", "HelixSR 3.3.0's HLX DLSS with NVIDIA's DLSS Model E network"),
    (HLX_DLSS_K, "FreeFG + HLX DLSS Preset K", "HelixSR 3.3.0's HLX DLSS with NVIDIA's DLSS 4 Preset K network: sharper, slower, can sparkle on foliage"),
    ("HLX FSR 4 Full", "FreeFG + HLX FSR 4 Full", "HelixSR 3.3.0's HLX FSR 4 Full: the full FSR 4.1.2 network, sharper, slower"),
    ("FSR 4 RC12", "FreeFG + FSR 4 RC12", "The BC-250 FSR 4 fork's RC12 build, the one FreeFG ships"),
]
LABELS = {value: label for value, label, _ in UPSCALERS}
HLX_DLSS_ROW = ("FreeFG + HLX DLSS", "HelixSR 3.3.0's HLX DLSS: NVIDIA's DLSS networks as DirectX 12 compute shaders",
                [(HLX_DLSS_E, "DLSS Model E"), (HLX_DLSS_K, "DLSS Preset K: sharper, slower, can sparkle on foliage")])
OFF = "off"
OFF_ROW = (OFF, "No upscaling", "The game as it ships: no OptiScaler, no FSR 4")
OFF_DEFAULT_SUB = "The game as it ships: no OptiScaler, no FSR 4 (where a new game starts)"
# Shown only when the ini has an upscaler the menu does not list (XeSS, or
# another FidelityFX provider picked in the overlay): starting keeps it.
KEEP = "keep"
KEEP_LABEL = "Keep the overlay's choice (%s)"
# Every older menu choice was a variant with one upscaler; each now means the
# one payload (the launcher seeds its upscaler, see previous_upscaler there).
RETIRED = {name: VARIANT for name in (
    "freefg-hlxfsr4", "freefg-hlxdlss", "freefg", "freefg-hlxdlssk", "freefg-hlxfsr4full",
    "freefg-helixsr", "helixsr-ffx", "helixsr", "hlxdlssk", "hlxfsr4", "fsr412f")}
FG_LABEL = "Enable frame generation"
# OptiScaler's [FrameGen] FGInput=dlssg: the game's own DLSS Frame Generation
# feeds FreeFG's XeFG (its motion vectors and HUD-less image) instead of OptiFG.
# A game only offers DLSS FG when it sees an NVIDIA card, so ticking it also sets
# GPU spoofing to On and frame generation on (owner, 2026-11-07).
DLSSG_LABEL = "Use the game's DLSS frame generation (turn it on in the game; sets spoofing On)"
DLSSG_ON, DLSSG_OFF = "dlssg", "upscaler"
SPOOF_LABEL = "GPU spoofing (DXGI)"
# OptiScaler's [Spoofing] Dxgi: "true or false - Default (auto) is true for
# AMD/Intel", and with no nvngx_dlss.dll in the game auto turns it off. Some
# games crash with it, others only offer DLSS with it, so the player can force it.
SPOOF = [("auto", "Auto"), ("true", "On"), ("false", "Off")]
SAVE_LABEL = "Save selection for next time (make sure to test it first)"
# Shown only when the launcher found this game in the preset database
# (BC250_MENU_GAME_PRESET names it). A fresh prefix gets the matching settings
# by itself; this applies them again over what the prefix has now.
FORCE_LABEL = "Force apply known settings for %s"
APPLY = [("matching", "Apply matching only"), ("everything", "Apply everything")]
HINT = "Launch your game with PROTON_OPTISCALER_MENU=1 %command% to show this menu again."

# Which keys mean "frame generation on", verified from the build's own
# OptiScaler.ini comments: [FrameGen] Enabled, with FGOutput=xefg as the wiring
# the variant's preset brings.
FG_ON = {VARIANT: {"FrameGen.Enabled": "true"}}
FG_OFF = {VARIANT: {"FrameGen.Enabled": "false"}}
# Enabled alone does nothing in a build whose FGInput and FGOutput default (auto)
# to nofg. The variant gets its wiring from its preset, so it needs none of this;
# the table stays for a variant without wiring of its own.
FG_WIRING = {}
UNWIRED = ("auto", "nofg")
# What the variant does with frame generation on a fresh prefix (its seed): it
# starts with it off and writes FrameGen.Enabled=false into the fresh ini
# (owner's decision, 2026-10-30), so the box shows the prefix's own answer from
# then on, the overlay's FG mode included.
FRESH_ON = {VARIANT: False, OFF: False}
# Keys a build's own OptiScaler.ini does not define: protonfixes refuses the
# launch, so the menu must not offer them (the fork ini has no [HelixSR] keys).
DEFINABLE = {VARIANT: {"framegen.enabled", "framegen.fginput", "framegen.fgoutput", "spoofing.dxgi",
                       "upscalers.dx12upscaler", "fsr.upscalerindex"}}


def upscaler_keys(upscaler):
    """The ini keys that pick an upscaler (the launcher's function of that name)."""
    keys = {"Upscalers.Dx12Upscaler": upscaler}
    if upscaler.lower() == "ffx":
        keys["FSR.UpscalerIndex"] = "0"
    return keys


def ini_raw(ini_sections, key):
    """A "Section.Option" value from the prefix's ini as written; missing is auto."""
    section, _, option = key.partition(".")
    value = (ini_sections.get(section.lower(), {}) or {}).get(option.lower())
    return str(value).strip() if value is not None else "auto"


def upscaler_state(ini_sections, fresh, previous=""):
    """The upscaler the launch runs with if nothing is picked, as a value of
    UPSCALERS, or (KEEP, what the ini has) for one the menu does not list.

    A fresh ini (fresh: the launch starts the prefix over) is seeded with the
    previous variant's upscaler, else with the shared preset's ffx; an ini still
    at auto gets that seed too. ffx is HLX FSR 4 only with UpscalerIndex 0, its
    first provider; another index is AMD's own FSR beside it."""
    if fresh:
        return previous if previous in LABELS else "ffx"
    raw = ini_raw(ini_sections, "Upscalers.Dx12Upscaler")
    if raw.lower() == "auto" or not raw:
        return previous if previous in LABELS else "ffx"
    if raw.lower() == "ffx":
        index = ini_raw(ini_sections, "FSR.UpscalerIndex").lower()
        return "ffx" if index in ("auto", "0") else (KEEP, "ffx, provider " + index)
    for value in LABELS:
        if value.lower() == raw.lower():
            return value
    return (KEEP, raw)


def store_path(prefix_path):
    """The per-prefix choice file. Under the prefix, not in the payload folder
    that protonfixes manages."""
    if not prefix_path:
        return None
    return os.path.join(prefix_path, "bc250-fsr4-menu.json")


def read_store(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path) as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def current_variant(store, default):
    return store.get("variant") or default


def fg_state(variant, ini_sections):
    """Is frame generation on for this variant, read from the prefix's ini?

    No ini yet, or every key still auto: nobody has answered, so the launch seeds
    the variant's fresh default and that is the state the game will run with.
    """
    want = FG_ON.get(variant, {})
    if not want:
        return False
    got = {key: ini_value(ini_sections, key) for key in want}
    if all(value == "auto" for value in got.values()):
        return FRESH_ON.get(variant, False)
    return all(got[key] == str(value).lower() for key, value in want.items())


def ini_value(ini_sections, key):
    """A "Section.Option" value from the prefix's ini, lower case; missing is auto."""
    section, _, option = key.partition(".")
    value = (ini_sections.get(section.lower(), {}) or {}).get(option.lower())
    return str(value).strip().lower() if value is not None else "auto"


def dlssg_state(ini_sections):
    """Does the prefix's ini take the game's DLSS frame generation as input?"""
    return ini_value(ini_sections, "FrameGen.FGInput") == DLSSG_ON


def spoof_state(ini_sections):
    """The prefix's [Spoofing] Dxgi as the menu offers it; anything else is auto."""
    value = str((ini_sections.get("spoofing", {}) or {}).get("dxgi", "auto")).strip().lower()
    return value if value in ("true", "false") else "auto"


def read_ini_sections(path):
    parser = configparser.ConfigParser()
    try:
        with open(path) as stream:
            parser.read_file(stream)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return {}
    return {s.lower(): {k.lower(): v for k, v in parser.items(s)} for s in parser.sections()}


def change(variant, was_on, is_on, can_write, ini_sections=None):
    """The keys the menu hands back: only what the player changed, and only keys
    this build can take.

    Frame generation on also hands back the variant's FG_WIRING keys the ini
    (ini_sections, the prefix's own; empty for a fresh start) still has unwired.
    That is not only on a change: a prefix whose Enabled=true went in without
    them (the 2026-10-27 Scaler) is repaired by pressing Start.
    """
    if variant not in FG_ON:
        return {}
    wanted = {}
    if was_on != is_on:
        wanted.update((FG_ON if is_on else FG_OFF)[variant])
    if is_on:
        wanted.update({key: value for key, value in FG_WIRING.get(variant, {}).items()
                       if ini_value(ini_sections or {}, key) in UNWIRED})
    return {k: v for k, v in wanted.items() if k.lower() in can_write}


def menu_option(env):
    """PROTON_OPTISCALER_MENU: "1" shows the menu (and clears a save), "0" skips
    it for this launch, anything else leaves it to the save and the settings."""
    value = env.get("PROTON_OPTISCALER_MENU", "").strip()
    return value if value in ("0", "1") else ""


def should_show(env, store, menu_enabled_default=True):
    """The menu is on by default: it shows unless it was saved away or the
    player's settings turn it off (menu_enabled_default, BC250_MENU_AUTO=0). A
    launch option shows it again and clears the save (=1), or skips it (=0)."""
    if env.get("PROTON_USE_OPTISCALER", "").strip() not in ("", "0"):
        return False
    option = menu_option(env)
    if option:
        return option == "1"
    return bool(store.get("remember", 0)) is False and menu_enabled_default


# --------------------------------------------------------------------------- GUI
for name in ("SDL_GAMECONTROLLER_IGNORE_DEVICES", "SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT"):
    os.environ.pop(name, None)
for name in ("SDL_JOYSTICK_HIDAPI", "SDL_JOYSTICK_HIDAPI_STEAM", "SDL_JOYSTICK_HIDAPI_PS4",
             "SDL_JOYSTICK_HIDAPI_PS5"):
    os.environ[name] = "1"
os.environ["SDL_NO_SIGNAL_HANDLERS"] = "1"  # SDL would swallow SIGTERM (Steam's "Exit game")

CSS = """
window { font-size: %(text)dpx; }
.title { font-size: %(title)dpx; font-weight: bold; }
.sub { font-size: %(small)dpx; opacity: 0.7; }
.hint { font-size: %(small)dpx; opacity: 0.8; }
checkbutton, button { padding: %(pad)dpx; }
checkbutton:focus-visible, button:focus-visible { outline: 4px solid #ff8c1a; outline-offset: 2px; border-radius: 8px; }
checkbutton:focus-visible { background-color: alpha(#ff8c1a, 0.15); }
"""
MARGIN = 28
MIN_SCALE = 0.55  # below this the text gets hard to read on a TV; the menu scrolls instead


def css(scale):
    return (CSS % {"text": round(20 * scale), "title": round(28 * scale), "small": max(9, round(15 * scale)),
                   "pad": round(6 * scale)}).encode()


def fit_scale(natural_height, room):
    """How far to shrink the text so a menu natural_height tall fits in room."""
    if natural_height <= room:
        return 1.0
    return max(MIN_SCALE, room / natural_height)

EVENTS = {0x650: "AXIS", 0x652: "BUTTONDOWN", 0x653: "DEVICEADDED", 0x100: "QUIT"}


def steam_game_id(env=os.environ):
    """The app id to tag the window with, or 0 when the launch carries none.

    Steam's ids come first; they are what Steam set for this launch. A umu
    launcher (Heroic, Lutris, a non-Steam shortcut) overwrites both with its
    GAMEID, which is usually not a number ("umu-default", "umu-0"), and Steam
    sets SteamAppId=0 for a non-Steam shortcut, so a 0 is skipped too and a
    launcher that knows its shortcut id can pass it in STEAM_GAME instead.
    """
    for name in ("SteamAppId", "SteamGameId", "STEAM_GAME"):
        value = (env.get(name) or "").strip()
        if value.isdigit() and int(value):
            return int(value)
    return 0


def tag_steam_game(surface, env=os.environ):
    """Mark the menu's X11 window as the game's, as Steam's overlay does for the game.

    Gamescope only shows windows whose STEAM_GAME property is the running app id.
    The game's own processes get it from Steam's LD_PRELOAD overlay; the SLR and GE
    packages start this menu beside the Steam client (steam-runtime-launch-client
    --alongside-steam), without that preload, so in Gaming Mode the window stayed
    hidden behind the launch spinner. Harmless on a desktop.
    """
    appid = steam_game_id(env)
    if not appid:
        return
    try:
        import gi
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
        if not isinstance(surface, GdkX11.X11Surface):
            return
        xid = surface.get_xid()
        x11 = ctypes.CDLL("libX11.so.6")
    except (ImportError, ValueError, OSError):
        return
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return
    value = (ctypes.c_ulong * 1)(appid)
    x11.XChangeProperty(display, xid, x11.XInternAtom(display, b"STEAM_GAME", 0),
                        x11.XInternAtom(display, b"CARDINAL", 0), 32, 0, value, 1)
    x11.XCloseDisplay(display)  # flushes


def gui(window_rows, preselected, fg_states, spoof_states, saved_on, known="", dlssg_states=None):
    """The window. window_rows as rows() makes them; preselected and the state
    dicts are by row name, a choice's name for a row with choices. Returns the
    picked name as result["preset"], or None when there is no window."""
    dlssg_states = dlssg_states or {}
    try:
        sdl = ctypes.CDLL("libSDL3.so.0")
    except OSError:
        sdl = None
    if sdl and not sdl.SDL_Init(0x2000):  # SDL_INIT_GAMEPAD; SDL3 returns bool
        sdl = None
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, GLib, Gdk
    except (ImportError, ValueError):
        return None
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        return None
    if sdl:
        sdl.SDL_OpenGamepad.restype = ctypes.c_void_p
        sdl.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]
    provider = Gtk.CssProvider()
    provider.load_from_data(css(1.0))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    ev = (ctypes.c_ubyte * 128)()
    result = {}
    loop = GLib.MainLoop()
    win = Gtk.Window(title="BC-250 upscaler")
    win.connect("realize", lambda w: tag_steam_game(w.get_surface()))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    for margin in ("margin_top", "margin_bottom", "margin_start", "margin_end"):
        box.set_property(margin, MARGIN)
    # Scrolls only when even the smallest text does not fit (see fit() below).
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                propagate_natural_width=True, propagate_natural_height=True)
    scroll.set_child(box)
    win.set_child(scroll)
    t = Gtk.Label(label="Choose the upscaler for this game", xalign=0)
    t.add_css_class("title")
    box.append(t)
    radios, group = [], None
    # Per row with choices (HLX DLSS): its own radio group, sensitive while the
    # row is picked, and which choice is on says which name the row stands for.
    choices = {}
    for name, label, sub, options in window_rows:
        r = Gtk.CheckButton()
        lab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        l1 = Gtk.Label(label=label, xalign=0)
        l2 = Gtk.Label(label=sub, xalign=0)
        l2.add_css_class("sub")
        lab.append(l1)
        lab.append(l2)
        r.set_child(lab)
        if group:
            r.set_group(group)
        else:
            group = r
        names = [c for c, _ in options] if options else [name]
        r.set_active(preselected in names)
        radios.append((name, r))
        box.append(r)
        if options:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            row.set_margin_start(32)
            buttons, first = [], None
            for value, text in options:
                c = Gtk.CheckButton(label=text)
                if first:
                    c.set_group(first)
                else:
                    first = c
                c.set_active(value == preselected or (preselected not in names and value == names[0]))
                buttons.append((value, c))
                row.append(c)
            box.append(row)
            choices[name] = buttons

    def chosen(name):
        """The name a picked row stands for: its active choice, or itself."""
        return next((v for v, c in choices.get(name, []) if c.get_active()), name)
    box.append(Gtk.Separator())
    spoof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    spoof_row.append(Gtk.Label(label=SPOOF_LABEL + ":", xalign=0))
    spoofs, spoof_group = [], None
    for value, label in SPOOF:
        s = Gtk.CheckButton(label=label)
        if spoof_group:
            s.set_group(spoof_group)
        else:
            spoof_group = s
        spoofs.append((value, s))
        spoof_row.append(s)
    box.append(spoof_row)
    fg = Gtk.CheckButton(label=FG_LABEL)
    dlssg = Gtk.CheckButton(label=DLSSG_LABEL)
    loading = [False]  # True while picked() shows a prefix's own values

    def dlssg_toggled(button):
        # The game's DLSS FG is only offered on an "NVIDIA" card, and it is
        # OptiScaler's frame generation that runs: both follow a tick by the
        # player, not the box showing what the prefix already has.
        if button.get_active() and not loading[0]:
            fg.set_active(True)
            for value, s in spoofs:
                s.set_active(value == "true")

    dlssg.connect("toggled", dlssg_toggled)

    def picked(button, name):
        # Ticked when frame generation is on. The payload shows its real state
        # (its ini, the overlay's FG mode and Save Settings included), the same
        # for every upscaler; No upscaling has nothing to switch.
        for row_name, buttons in choices.items():
            for _, c in buttons:
                c.set_sensitive(dict(radios)[row_name].get_active())
        if button.get_active():
            name = chosen(name)
            on = name != OFF
            for value, s in spoofs:
                s.set_active(value == spoof_states.get(name, "auto"))
                s.set_sensitive(on)
            loading[0] = True
            dlssg.set_active(dlssg_states.get(name, False))
            loading[0] = False
            dlssg.set_sensitive(on)
            fg.set_active(fg_states.get(name, False))
            fg.set_sensitive(on)

    for name, r in radios:
        r.connect("toggled", picked, name)
    for name, r in radios:
        if r.get_active():
            picked(r, name)
    box.append(fg)
    box.append(dlssg)
    force, applies = None, []
    if known:
        force = Gtk.CheckButton(label=FORCE_LABEL % known)
        box.append(force)
        apply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        apply_row.set_margin_start(32)
        apply_group = None
        for value, label in APPLY:
            a = Gtk.CheckButton(label=label)
            if apply_group:
                a.set_group(apply_group)
            else:
                apply_group = a
            a.set_active(value == "matching")
            applies.append((value, a))
            apply_row.append(a)
        apply_row.set_visible(False)
        force.connect("toggled", lambda b: apply_row.set_visible(b.get_active()))
        box.append(apply_row)
    keep = Gtk.CheckButton(label=SAVE_LABEL)
    keep.set_active(bool(saved_on))
    box.append(keep)
    h = Gtk.Label(label=HINT, xalign=0, wrap=True)
    h.add_css_class("hint")
    box.append(h)
    start = Gtk.Button(label="Start game")
    start.add_css_class("suggested-action")
    box.append(start)
    pad_hint = Gtk.Label(label="", xalign=0)
    pad_hint.add_css_class("hint")
    box.append(pad_hint)

    def finish(*_):
        for name, r in radios:
            if r.get_active():
                result["preset"] = chosen(name)
        result["enable_framegen"] = int(fg.get_active())
        result["dlssg"] = int(dlssg.get_active())
        result["spoof"] = next((value for value, s in spoofs if s.get_active()), "auto")
        result["remember"] = int(keep.get_active())
        result["apply_preset"] = (next((v for v, a in applies if a.get_active()), "matching")
                                  if force is not None and force.get_active() else "")
        loop.quit()

    start.connect("clicked", finish)
    win.connect("close-request", lambda *_: (loop.quit(), False)[1])

    # Own focus order for the pad: GTK's directional focus keeps a radio group's
    # focus inside the group, so the pad could not leave the upscaler rows.
    def move(d):
        extra = [force] if force is not None else []
        if force is not None and force.get_active():
            extra += [a for _, a in applies]
        order = []
        for name, r in radios:
            order.append(r)
            order += [c for _, c in choices.get(name, [])]
        order += [s for _, s in spoofs] + [fg, dlssg, *extra, keep, start]
        cur = win.get_focus()
        while cur is not None and cur not in order:
            cur = cur.get_parent()
        i = order.index(cur) if cur in order else 0
        # Step over what cannot take focus right now: the HLX DLSS choices while
        # another row is picked, the frame-generation rows under No upscaling.
        # grab_focus() on a greyed-out widget does nothing, so stepping onto one
        # left the focus where it was and the pad could not get past it.
        step = 1 if d == Gtk.DirectionType.DOWN else -1
        j = i + step
        while 0 <= j < len(order) and not (order[j].is_sensitive() and order[j].is_visible()):
            j += step
        if 0 <= j < len(order):
            order[j].grab_focus()
        win.set_focus_visible(True)

    def poll_pad():
        if not sdl:
            return False
        while sdl.SDL_PollEvent(ctypes.byref(ev)):
            typ = int.from_bytes(bytes(ev[0:4]), "little")
            if typ == 0x653:
                sdl.SDL_OpenGamepad(int.from_bytes(bytes(ev[16:20]), "little"))
                pad_hint.set_label("Controller: D-pad/stick to move, A to select, Start to start the game")
            elif typ == 0x652:
                b = ev[20]
                if b in (11, 13):  # d-pad up, left
                    move(Gtk.DirectionType.UP)
                elif b in (12, 14):  # d-pad down, right
                    move(Gtk.DirectionType.DOWN)
                elif b == 0:
                    w = win.get_focus()
                    if w is not None:
                        w.activate()
                elif b == 6:
                    finish()
            elif typ == 0x650:
                axis, val = ev[20], int.from_bytes(bytes(ev[24:26]), "little", signed=True)
                if axis == 1:
                    st = 1 if val > 20000 else -1 if val < -20000 else 0
                    if st and st != poll_pad.last:
                        move(Gtk.DirectionType.DOWN if st > 0 else Gtk.DirectionType.UP)
                    poll_pad.last = st
        return True

    def fit():
        # Gaming Mode runs games (and this menu) on a screen of the game's
        # resolution, often 1280x800 or 720p scaled up to the TV, and a HiDPI
        # desktop (4K at 200%) halves the room again: shrink the text until the
        # whole menu fits, so nothing is cut off at the top or bottom.
        win.realize()
        display = win.get_display()
        monitor = display.get_monitor_at_surface(win.get_surface()) or display.get_monitors().get_item(0)
        if monitor is None:
            return
        geometry = monitor.get_geometry()  # logical pixels, as measure() below
        width = min(900, geometry.width - 32)
        room = geometry.height - 48  # leave a little for a title bar
        # Measured once at full size: the CSS takes effect only on the next
        # frame, and text, margins and spacing all shrink about in proportion.
        natural = box.measure(Gtk.Orientation.VERTICAL, width)[1]  # margins included
        scale = fit_scale(natural / 0.97, room)
        if scale < 1.0:
            provider.load_from_data(css(scale))
            box.set_spacing(round(8 * scale))
            for margin in ("margin_top", "margin_bottom", "margin_start", "margin_end"):
                box.set_property(margin, round(MARGIN * scale))
        win.set_default_size(width, -1)
        scroll.set_max_content_height(room)

    poll_pad.last = 0
    GLib.timeout_add(16, poll_pad)
    fit()
    win.present()
    for name, r in radios:
        if r.get_active():
            r.grab_focus()
    win.set_focus_visible(True)
    loop.run()
    return result or None


def state(prefix, env=os.environ):
    """The prefix's current variant and its real frame-generation state."""
    path = store_path(prefix)
    store = read_store(path)
    known = {VARIANT, OFF}
    saved = RETIRED.get(store.get("variant"), store.get("variant"))
    saved = saved if saved in known else None
    installed = env.get("BC250_MENU_INSTALLED", "")
    # What a new prefix starts on: No upscaling, or the settings file's default.
    default = env.get("BC250_MENU_DEFAULT", "").strip() or OFF
    default = default if default in known else OFF
    # A saved choice is the player's word; otherwise what the prefix holds now
    # (the launcher reads it off the payload on disk), then the last pick, then
    # the package default for a fresh prefix. No upscaling leaves the last
    # variant's files where they were, so only the pick itself can say it.
    if saved and (store.get("remember") or saved == OFF):
        current = saved
    else:
        current = installed if installed in known else saved or default
    ini = os.path.join(prefix, "pfx", "drive_c", "windows", "system32", "umu", "OptiScaler.ini")
    if installed != current:
        # The prefix holds another variant (or one from an older package): the
        # launch starts it fresh, so the box shows what the fresh seed does.
        return store, current, FRESH_ON.get(current, False), ini
    return store, current, fg_state(current, read_ini_sections(ini) if prefix else {}), ini


def decide(prefix, env):
    """Should the menu appear for this launch? (owner's rules, no code in the
    launcher about menu state)."""
    store, current, fg_on, _ = state(prefix, env)
    saved = int(store.get("remember", 0))
    # =1 shows again and clears the save on the way out; =0 starts the game on
    # current, the prefix's choice, without asking.
    auto = env.get("BC250_MENU_AUTO", "").strip() != "0"
    return should_show(env, store, auto), current, fg_on, saved


def answer(result, current, base, fg_states, spoof_states=None, ini_sections=None,
           dlssg_states=None, upscaler="ffx"):
    """What the launcher gets back for the player's pick.

    result["preset"] is the picked row: an upscaler of UPSCALERS, KEEP or OFF.
    The launcher gets the variant (the payload, or OFF) as "preset" and the
    upscaler as Upscalers.Dx12Upscaler among the changed keys, only when it
    differs from upscaler, what the launch would run with anyway.

    base is the variant the prefix's files and ini belong to: the current one, or
    under No upscaling the one installed before it, so that going back to it is
    not a switch and keeps the player's settings. ini_sections is the prefix's
    ini, which belongs to base. fg_states, spoof_states and dlssg_states are by
    variant.
    """
    row = result["preset"]
    new = OFF if row == OFF else VARIANT
    is_on = bool(int(result["enable_framegen"]))
    switched = new != OFF and new != base
    # A switch starts fresh (the launcher removes the prefix's ini and
    # protonfixes re-copies it), and fg_states holds that seed for every variant
    # but base: the box is handed back only where the player changed it.
    changed = {} if new == OFF else change(new, fg_states.get(new, False), is_on,
                                           DEFINABLE.get(new, set()),
                                           ini_sections if new == base else {})
    if new != OFF and row in LABELS and row != upscaler:
        changed.update(upscaler_keys(row))
    explicit = []  # keys the player set by hand, which beat a game preset's
    spoof = result.get("spoof", "auto")
    if new != OFF and spoof != (spoof_states or {}).get(new, "auto"):
        changed["Spoofing.Dxgi"] = spoof
    # The input, like the other boxes, only when the player changed it; unticked
    # it goes back to OptiFG, the variant's own input.
    use_dlssg = bool(int(result.get("dlssg", 0)))
    if (new != OFF and use_dlssg != bool((dlssg_states or {}).get(new, False))
            and "framegen.fginput" in DEFINABLE.get(new, set())):
        changed["FrameGen.FGInput"] = DLSSG_ON if use_dlssg else DLSSG_OFF
        explicit.append("FrameGen.FGInput")
    return {
        "preset": new,
        "enable_framegen": int(result["enable_framegen"]),
        "remember": int(result.get("remember", 0)),
        "switched": int(switched),
        "changed": ";".join(k + "=" + v for k, v in changed.items()),
        "explicit": ";".join(explicit),
        # No upscaling has no OptiScaler.ini to apply settings to.
        "apply_preset": "" if new == OFF else result.get("apply_preset", ""),
    }


def rows(upscaler, off_default=True):
    """The window's rows: (name, label, sub-label, choices). A row with choices
    (HLX DLSS) is picked by its choices' names; the others by their own.
    off_default: a new prefix starts on No upscaling, and its row says so."""
    by_value = {value: (value, label, sub, None) for value, label, sub in UPSCALERS}
    off = (OFF, OFF_ROW[1], OFF_DEFAULT_SUB if off_default else OFF_ROW[2], None)
    out = [off, by_value["ffx"], (HLX_DLSS_E,) + HLX_DLSS_ROW, by_value["HLX FSR 4 Full"],
           by_value["FSR 4 RC12"]]
    if isinstance(upscaler, tuple):
        out.append((KEEP, KEEP_LABEL % upscaler[1],
                    "Picked in OptiScaler's overlay; the other rows replace it", None))
    return out


def main():
    prefix = os.environ.get("STEAM_COMPAT_DATA_PATH", "").strip()
    show, current, fg_on, saved = decide(prefix, os.environ)
    if sys.argv[1:2] == ["--decide"]:
        # The launcher asks this before it decides to open a window, and this
        # never needs a display, so it cannot fail a launch.
        print("show=%d" % int(show))
        print("current=%s" % current)
        print("fg_on=%d" % int(fg_on))
        print("saved=%d" % saved)
        return 0
    if not show:
        return 0
    fg_states = dict(FRESH_ON)
    # A variant that starts fresh gets the shared preset's auto.
    spoof_states = {}
    dlssg_states = {}
    installed = os.environ.get("BC250_MENU_INSTALLED", "")
    ini = os.path.join(prefix, "pfx", "drive_c", "windows", "system32", "umu", "OptiScaler.ini")
    sections = read_ini_sections(ini) if prefix else {}
    base = current
    if current == OFF:
        base = installed if installed in FG_ON else None
        if base:
            fg_on = fg_state(base, sections)
    if base:
        fg_states[base] = fg_on
        if base == installed:
            spoof_states[base] = spoof_state(sections)
            dlssg_states[base] = dlssg_state(sections)
    # The upscaler the payload runs with: what its ini has, or the seed of a
    # fresh one (an older package's prefix starts over).
    upscaler = upscaler_state(sections, installed != VARIANT,
                              os.environ.get("BC250_MENU_PREVIOUS", "").strip())
    if current == OFF:
        preselected = OFF
    else:
        preselected = KEEP if isinstance(upscaler, tuple) else upscaler
    window_rows = rows(upscaler, (os.environ.get("BC250_MENU_DEFAULT", "").strip() or OFF) == OFF)
    # The window shows the boxes by row; every row but No upscaling is the payload.
    names = [n for r in window_rows for n in ([c for c, _ in r[3]] if r[3] else [r[0]])]

    def per_row(states):
        return {n: states[v] for n in names
                for v in [OFF if n == OFF else VARIANT] if v in states}

    result = gui(window_rows, preselected, per_row(fg_states), per_row(spoof_states), saved,
                 os.environ.get("BC250_MENU_GAME_PRESET", "").strip(), per_row(dlssg_states))
    if result is None:
        # No window: keep the current choice and let the game start.
        return 3
    new = OFF if result["preset"] == OFF else VARIANT
    path = store_path(prefix)
    if path:
        with open(path, "w") as stream:
            json.dump({"variant": new, "remember": int(result.get("remember", 0))}, stream)
    for key, value in answer(result, current, base, fg_states, spoof_states, sections,
                             dlssg_states, upscaler).items():
        print("%s=%s" % (key, value))
    if path:
        print("store=%s" % path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit("bc250-menu: " + str(error))
