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

The state rules (owner's decisions, 2026-10-26): single choice among the presets,
the variant the prefix is on pre-selected; the frame-generation row shows the
prefix's real current state and is written only when the player changes it;
switching variant means starting fresh (the launcher removes the prefix's
OptiScaler.ini, protonfixes re-copies it); "Save selection" skips the menu from
then on; PROTON_OPTISCALER_MENU=1 shows it again and clears the save. No
timeout: the menu waits for a choice. Never block a launch.
"""
import configparser
import ctypes
import json
import os
import sys

# name, label, sub-label. The order is the order in the window.
PRESETS = [
    ("freefg-hlxfsr4", "FreeFG + HLX FSR 4", "FreeFG 1.1.6 frame generation, HelixSR 3.2.0's HLX FSR 4 upscaler"),
    ("freefg", "FreeFG + FSR4 RC12", "FreeFG 1.1.6 frame generation, FSR4 RC12 upscaler"),
    ("helixsr", "HelixSR Scaler", "HelixSR Scaler 2.1.0, HelixSR 3.2.0: HLX DLSS, or HLX FSR 4 from its menu"),
    ("fsr412f", "FSR4 RC12", "FSR4 RC12 upscaler only, no FreeFG"),
    (OFF := "off", "No upscaling", "The game as it ships: no OptiScaler, no FSR4"),
]
# A choice saved by an older package that names a variant it no longer has
# (HelixSR 2.0 went in 2026-10): what that name selects now.
RETIRED = {"freefg-helixsr": "freefg-hlxfsr4", "helixsr-ffx": "helixsr"}
FG_LABEL = "Enable frame generation"
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

# Which keys mean "frame generation on" for each build, verified from the build's
# own OptiScaler.ini comments and the HelixSR Scaler README:
#   freefg*:               [FrameGen] Enabled (+ FGOutput=xefg, that is the wiring)
#   helixsr (the Scaler):  [FrameGen] Enabled + FG_WIRING -- HelixSR 3.x has no
#                          frame generation of its own, OptiScaler's is all there is
#   fsr412f:               [FrameGen] Enabled + FG_WIRING, the stock nightly's keys
FG_ON = {
    "freefg-hlxfsr4": {"FrameGen.Enabled": "true"},
    "freefg": {"FrameGen.Enabled": "true"},
    "helixsr": {"FrameGen.Enabled": "true"},
    "fsr412f": {"FrameGen.Enabled": "true"},
}
FG_OFF = {
    "freefg-hlxfsr4": {"FrameGen.Enabled": "false"},
    "freefg": {"FrameGen.Enabled": "false"},
    "helixsr": {"FrameGen.Enabled": "false"},
    "fsr412f": {"FrameGen.Enabled": "false"},
}
# Enabled alone does nothing in these builds: FGInput and FGOutput both default
# (auto) to nofg. FreeFG gets its wiring from its variant preset; these get it
# when the player turns frame generation on, and only where the ini still says
# auto/nofg, so an output picked in the overlay stays. OptiFG (upscaler input)
# works in any game whose upscaler OptiScaler sees; FSR FG is the output, its DLLs
# are in the nightly, and it needs neither FreeFG's wrapper nor XeFG's runtime.
FG_WIRING = {
    "helixsr": {"FrameGen.FGInput": "upscaler", "FrameGen.FGOutput": "fsrfg"},
    "fsr412f": {"FrameGen.FGInput": "upscaler", "FrameGen.FGOutput": "fsrfg"},
}
UNWIRED = ("auto", "nofg")
# What a variant does with frame generation on a fresh prefix (its seed): every
# variant starts with it off and writes FrameGen.Enabled=false into the fresh ini
# (owner's decision, 2026-10-30), so the box shows the prefix's own answer from
# then on, the overlay's FG mode included.
FRESH_ON = {"freefg-hlxfsr4": False, "freefg": False,
            "helixsr": False, "fsr412f": False, OFF: False}
# Keys a build's own OptiScaler.ini does not define: protonfixes refuses the
# launch, so the menu must not offer them (the fork ini has no [HelixSR] keys).
DEFINABLE = {
    "freefg-hlxfsr4": {"framegen.enabled", "framegen.fginput", "framegen.fgoutput", "spoofing.dxgi"},
    "freefg": {"framegen.enabled", "framegen.fginput", "framegen.fgoutput", "spoofing.dxgi"},
    "helixsr": {"framegen.enabled", "framegen.fginput", "framegen.fgoutput", "spoofing.dxgi"},
    "fsr412f": {"framegen.enabled", "framegen.fginput", "framegen.fgoutput", "spoofing.dxgi"},
}


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


def should_show(env, store, menu_enabled_default=True):
    """The menu is on by default: it shows unless it was saved away, and a launch
    option both shows it again and clears the save."""
    if env.get("PROTON_USE_OPTISCALER", "").strip() not in ("", "0"):
        return False
    if env.get("PROTON_OPTISCALER_MENU", "") == "1":
        return True
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


def tag_steam_game(surface, env=os.environ):
    """Mark the menu's X11 window as the game's, as Steam's overlay does for the game.

    Gamescope only shows windows whose STEAM_GAME property is the running app id.
    The game's own processes get it from Steam's LD_PRELOAD overlay; the SLR and GE
    packages start this menu beside the Steam client (steam-runtime-launch-client
    --alongside-steam), without that preload, so in Gaming Mode the window stayed
    hidden behind the launch spinner. Harmless on a desktop.
    """
    try:
        appid = int(env.get("SteamAppId") or env.get("SteamGameId") or 0)
    except ValueError:
        appid = 0
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


def gui(preset_names, preselected, fg_states, spoof_states, saved_on, known=""):
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
    for name, label, sub in preset_names:
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
        r.set_active(name == preselected)
        radios.append((name, r))
        box.append(r)
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

    def picked(button, name):
        # Ticked when frame generation is on. The prefix's own variant shows its
        # real state (its ini, the overlay's FG mode and Save Settings included);
        # another one starts fresh, with it off. No upscaling has nothing to switch.
        if button.get_active():
            fg.set_active(fg_states.get(name, False))
            fg.set_sensitive(name in FG_ON)
            for value, s in spoofs:
                s.set_active(value == spoof_states.get(name, "auto"))
                s.set_sensitive(name in FG_ON)

    for name, r in radios:
        r.connect("toggled", picked, name)
        if name == preselected:
            picked(r, name)
    box.append(fg)
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
                result["preset"] = name
        result["enable_framegen"] = int(fg.get_active())
        result["spoof"] = next((value for value, s in spoofs if s.get_active()), "auto")
        result["remember"] = int(keep.get_active())
        result["apply_preset"] = (next((v for v, a in applies if a.get_active()), "matching")
                                  if force is not None and force.get_active() else "")
        loop.quit()

    start.connect("clicked", finish)
    win.connect("close-request", lambda *_: (loop.quit(), False)[1])

    # Own focus order for the pad: GTK's directional focus keeps a radio group's
    # focus inside the group, so the pad could not leave the four presets.
    def move(d):
        extra = [force] if force is not None else []
        if force is not None and force.get_active():
            extra += [a for _, a in applies]
        order = [r for _, r in radios] + [s for _, s in spoofs] + [fg, *extra, keep, start]
        cur = win.get_focus()
        while cur is not None and cur not in order:
            cur = cur.get_parent()
        i = order.index(cur) if cur in order else 0
        i = max(0, min(len(order) - 1, i + (1 if d == Gtk.DirectionType.DOWN else -1)))
        order[i].grab_focus()
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
    known = {name for name, _, _ in PRESETS}
    saved = RETIRED.get(store.get("variant"), store.get("variant"))
    saved = saved if saved in known else None
    installed = env.get("BC250_MENU_INSTALLED", "")
    default = env.get("BC250_MENU_DEFAULT", "") or "freefg-hlxfsr4"
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
    if env.get("PROTON_USE_OPTISCALER", "").strip() not in ("", "0"):
        return False, current, fg_on, int(store.get("remember", 0))
    if env.get("PROTON_OPTISCALER_MENU", "") == "1":
        # Shows again, and clears the save on the way out.
        return True, current, fg_on, int(store.get("remember", 0))
    return not int(store.get("remember", 0)), current, fg_on, int(store.get("remember", 0))


def answer(result, current, base, fg_states, spoof_states=None, ini_sections=None):
    """What the launcher gets back for the player's pick.

    base is the variant the prefix's files and ini belong to: the current one, or
    under No upscaling the one installed before it, so that going back to it is
    not a switch and keeps the player's settings. ini_sections is the prefix's
    ini, which belongs to base.
    """
    new = result["preset"]
    is_on = bool(int(result["enable_framegen"]))
    switched = new != OFF and new != base
    # A switch starts fresh (the launcher removes the prefix's ini and
    # protonfixes re-copies it), and fg_states holds that seed for every variant
    # but base: the box is handed back only where the player changed it.
    changed = {} if new == OFF else change(new, fg_states.get(new, False), is_on,
                                           DEFINABLE.get(new, set()),
                                           ini_sections if new == base else {})
    spoof = result.get("spoof", "auto")
    if new != OFF and spoof != (spoof_states or {}).get(new, "auto"):
        changed["Spoofing.Dxgi"] = spoof
    return {
        "preset": new,
        "enable_framegen": int(result["enable_framegen"]),
        "remember": int(result.get("remember", 0)),
        "switched": int(switched),
        "changed": ";".join(k + "=" + v for k, v in changed.items()),
        # No upscaling has no OptiScaler.ini to apply settings to.
        "apply_preset": "" if new == OFF else result.get("apply_preset", ""),
    }


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
    result = gui(PRESETS, current, fg_states, spoof_states, saved,
                 os.environ.get("BC250_MENU_GAME_PRESET", "").strip())
    if result is None:
        # No window: keep the current choice and let the game start.
        return 3
    path = store_path(prefix)
    if path:
        with open(path, "w") as stream:
            json.dump({"variant": result["preset"], "remember": int(result.get("remember", 0))}, stream)
    for key, value in answer(result, current, base, fg_states, spoof_states, sections).items():
        print("%s=%s" % (key, value))
    if path:
        print("store=%s" % path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit("bc250-menu: " + str(error))
