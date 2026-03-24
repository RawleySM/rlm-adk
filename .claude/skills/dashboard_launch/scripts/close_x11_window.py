#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Close an X11 window by title substring using only ctypes + libX11.

Usage: uv run scripts/close_x11_window.py "RLM Live Recursive Dashboard"
"""
import ctypes
import sys

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XInternAtom.restype = ctypes.c_ulong


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class XEvent(ctypes.Union):
    _fields_ = [("xclient", XClientMessageEvent), ("pad", ctypes.c_char * 192)]


def close_window_by_title(title_substr: str) -> bool:
    display = x11.XOpenDisplay(None)
    if not display:
        print("Cannot open X display")
        return False

    root = x11.XDefaultRootWindow(display)
    atoms = {
        name: x11.XInternAtom(display, name, False)
        for name in [
            b"_NET_CLIENT_LIST",
            b"_NET_WM_NAME",
            b"_NET_CLOSE_WINDOW",
            b"UTF8_STRING",
        ]
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
    closed = 0

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
                ev = XEvent()
                ev.xclient.type = 33  # ClientMessage
                ev.xclient.send_event = 1
                ev.xclient.display = display
                ev.xclient.window = wid
                ev.xclient.message_type = atoms[b"_NET_CLOSE_WINDOW"]
                ev.xclient.format = 32
                ev.xclient.data[0] = 0  # timestamp
                ev.xclient.data[1] = 1  # source indication (app)
                x11.XSendEvent(
                    display, root, False, 0x180000, ctypes.byref(ev)
                )
                print(f"Closed: {hex(wid)} | {title}")
                closed += 1

    x11.XFlush(display)
    x11.XCloseDisplay(display)
    return closed > 0


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "RLM Live Recursive Dashboard"
    if not close_window_by_title(title):
        print(f"No window found matching: {title}")
        sys.exit(1)
