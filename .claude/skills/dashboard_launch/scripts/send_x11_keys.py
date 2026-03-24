#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Send a key combo to an X11 window by title substring using ctypes + libX11 + libXtst.

Focuses the window, sends the key combo via XTest fake key events, then flushes.

Usage: python3 send_x11_keys.py "RLM Live Recursive Dashboard" ctrl+shift+i
"""
import ctypes
import sys
import time

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XInternAtom.restype = ctypes.c_ulong
x11.XKeysymToKeycode.restype = ctypes.c_ubyte
x11.XStringToKeysym.restype = ctypes.c_ulong

xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")

# Modifier name -> X11 keysym name
MODIFIER_MAP = {
    "ctrl": "Control_L",
    "shift": "Shift_L",
    "alt": "Alt_L",
    "super": "Super_L",
    "meta": "Meta_L",
}


def find_window_by_title(display, title_substr: str) -> int | None:
    root = x11.XDefaultRootWindow(display)
    atoms = {
        name: x11.XInternAtom(display, name, False)
        for name in [b"_NET_CLIENT_LIST", b"_NET_WM_NAME", b"UTF8_STRING"]
    }

    t, f, ni, ba, d = (
        ctypes.c_ulong(),
        ctypes.c_int(),
        ctypes.c_ulong(),
        ctypes.c_ulong(),
        ctypes.c_void_p(),
    )
    x11.XGetWindowProperty(
        display, root, atoms[b"_NET_CLIENT_LIST"],
        0, 1024, False, 33,  # XA_WINDOW
        *[ctypes.byref(v) for v in (t, f, ni, ba, d)],
    )
    if not d.value:
        return None

    wids = list((ctypes.c_ulong * ni.value).from_address(d.value))

    for wid in wids:
        t2, f2, ni2, ba2, d2 = (
            ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(),
            ctypes.c_ulong(), ctypes.c_void_p(),
        )
        x11.XGetWindowProperty(
            display, wid, atoms[b"_NET_WM_NAME"],
            0, 1024, False, atoms[b"UTF8_STRING"],
            *[ctypes.byref(v) for v in (t2, f2, ni2, ba2, d2)],
        )
        if d2.value and ni2.value > 0:
            title = ctypes.string_at(d2.value, ni2.value).decode("utf-8", errors="replace")
            x11.XFree(d2)
            if title_substr in title:
                return wid
    return None


def send_keys(title_substr: str, combo: str) -> bool:
    display = x11.XOpenDisplay(None)
    if not display:
        print("Cannot open X display")
        return False

    wid = find_window_by_title(display, title_substr)
    if wid is None:
        print(f"No window found matching: {title_substr}")
        x11.XCloseDisplay(display)
        return False

    # Focus the window
    x11.XRaiseWindow(display, wid)
    x11.XSetInputFocus(display, wid, 1, 0)  # RevertToParent=1, CurrentTime=0
    x11.XFlush(display)
    time.sleep(0.1)

    # Parse combo like "ctrl+shift+i"
    parts = combo.lower().split("+")
    key_name = parts[-1]
    modifier_names = parts[:-1]

    # Resolve keycodes
    if len(key_name) == 1:
        keysym = x11.XStringToKeysym(key_name.encode())
    else:
        keysym = x11.XStringToKeysym(key_name.encode())
    keycode = x11.XKeysymToKeycode(display, keysym)
    if keycode == 0:
        print(f"Cannot resolve keycode for: {key_name}")
        x11.XCloseDisplay(display)
        return False

    mod_keycodes = []
    for mod in modifier_names:
        sym_name = MODIFIER_MAP.get(mod, mod)
        mod_sym = x11.XStringToKeysym(sym_name.encode())
        mod_kc = x11.XKeysymToKeycode(display, mod_sym)
        if mod_kc == 0:
            print(f"Cannot resolve modifier keycode for: {mod}")
            x11.XCloseDisplay(display)
            return False
        mod_keycodes.append(mod_kc)

    # Press modifiers down
    for mkc in mod_keycodes:
        xtst.XTestFakeKeyEvent(display, mkc, True, 0)  # KeyPress
    # Press and release main key
    xtst.XTestFakeKeyEvent(display, keycode, True, 0)   # KeyPress
    xtst.XTestFakeKeyEvent(display, keycode, False, 0)  # KeyRelease
    # Release modifiers (reverse order)
    for mkc in reversed(mod_keycodes):
        xtst.XTestFakeKeyEvent(display, mkc, False, 0)  # KeyRelease

    x11.XFlush(display)
    x11.XCloseDisplay(display)
    print(f"Sent {combo} to: {hex(wid)} | {title_substr}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <title_substr> <key_combo>")
        print(f"Example: {sys.argv[0]} 'Dashboard' ctrl+shift+i")
        sys.exit(1)
    if not send_keys(sys.argv[1], sys.argv[2]):
        sys.exit(1)
