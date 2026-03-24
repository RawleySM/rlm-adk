#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Move and resize an X11 window by title substring using only ctypes + libX11.

Usage: uv run scripts/position_x11_window.py "RLM Live Recursive Dashboard" 121 534 1745 2120
"""
import ctypes
import sys

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XInternAtom.restype = ctypes.c_ulong


def position_window_by_title(
    title_substr: str, x: int, y: int, width: int, height: int
) -> bool:
    display = x11.XOpenDisplay(None)
    if not display:
        print("Cannot open X display")
        return False

    root = x11.XDefaultRootWindow(display)
    atoms = {
        name: x11.XInternAtom(display, name, False)
        for name in [b"_NET_CLIENT_LIST", b"_NET_WM_NAME", b"UTF8_STRING"]
    }

    # Get window list from root
    t, f, ni, ba, d = (
        ctypes.c_ulong(),
        ctypes.c_int(),
        ctypes.c_ulong(),
        ctypes.c_ulong(),
        ctypes.c_void_p(),
    )
    x11.XGetWindowProperty(
        display,
        root,
        atoms[b"_NET_CLIENT_LIST"],
        0,
        1024,
        False,
        33,  # XA_WINDOW
        *[ctypes.byref(v) for v in (t, f, ni, ba, d)],
    )
    if not d.value:
        x11.XCloseDisplay(display)
        return False

    wids = list((ctypes.c_ulong * ni.value).from_address(d.value))
    moved = 0

    for wid in wids:
        t2, f2, ni2, ba2, d2 = (
            ctypes.c_ulong(),
            ctypes.c_int(),
            ctypes.c_ulong(),
            ctypes.c_ulong(),
            ctypes.c_void_p(),
        )
        x11.XGetWindowProperty(
            display,
            wid,
            atoms[b"_NET_WM_NAME"],
            0,
            1024,
            False,
            atoms[b"UTF8_STRING"],
            *[ctypes.byref(v) for v in (t2, f2, ni2, ba2, d2)],
        )
        if d2.value and ni2.value > 0:
            title = ctypes.string_at(d2.value, ni2.value).decode(
                "utf-8", errors="replace"
            )
            x11.XFree(d2)
            if title_substr in title:
                x11.XMoveResizeWindow(display, wid, x, y, width, height)
                print(f"Positioned: {hex(wid)} | {title} -> {x},{y} {width}x{height}")
                moved += 1

    x11.XFlush(display)
    x11.XCloseDisplay(display)
    return moved > 0


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(f"Usage: {sys.argv[0]} <title_substr> <x> <y> <width> <height>")
        sys.exit(1)
    title = sys.argv[1]
    x, y, w, h = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    if not position_window_by_title(title, x, y, w, h):
        print(f"No window found matching: {title}")
        sys.exit(1)
