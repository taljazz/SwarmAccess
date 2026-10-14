"""Screen capture, visibility checks and mouse input, with plain ctypes.

Kept free of NVDA so ``tools/probe.py`` exercises exactly the code the
add-on runs.  All coordinates are physical screen pixels, which is what UI
Automation reports and what NVDA (a per-monitor DPI aware process) uses.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

from .model import Rect
from .pixels import PixelSource

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GA_ROOT = 2
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class CapturedPixels(PixelSource):
    """A rectangle copied off the screen, as 32-bit BGRA rows."""

    def __init__(self, rect: Rect, data: bytes):
        self.rect = rect
        self.width = rect.width
        self.height = rect.height
        self._data = data

    def pixel(self, x: int, y: int):
        i = (y * self.width + x) * 4
        b, g, r = self._data[i], self._data[i + 1], self._data[i + 2]
        return (r, g, b)


def capture(rect: Rect) -> CapturedPixels:
    """Copy what is on screen inside ``rect``: exactly what a sighted user sees there."""
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, rect.width, rect.height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        gdi32.BitBlt(mem_dc, 0, 0, rect.width, rect.height, screen_dc, rect.left, rect.top,
                     SRCCOPY | CAPTUREBLT)
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = rect.width
        header.biHeight = -rect.height  # negative: rows run top to bottom
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(rect.width * rect.height * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, rect.height, buffer, ctypes.byref(header), DIB_RGB_COLORS)
        return CapturedPixels(rect, buffer.raw)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def window_at(x: int, y: int) -> Optional[int]:
    """The top-level window a click at (x, y) would land in."""
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return None
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def is_showing(top_level: int, rect: Rect, inset: int = 2) -> bool:
    """True when every corner and the centre of ``rect`` belong to ``top_level``.

    This is what makes pixel reading and clicking safe: a window covering any
    part of the control, the taskbar, or the edge of the screen all fail it,
    so the add-on says the control is hidden instead of reading or clicking
    something else.
    """
    points = (
        (rect.left + inset, rect.top + inset),
        (rect.right - 1 - inset, rect.top + inset),
        (rect.left + inset, rect.bottom - 1 - inset),
        (rect.right - 1 - inset, rect.bottom - 1 - inset),
        (int(rect.center_x), int(rect.center_y)),
    )
    return all(window_at(x, y) == top_level for x, y in points)


def process_of(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def belongs_to_process(top_level: int, rect: Rect) -> bool:
    """True when the centre of ``rect`` is in a window of ``top_level``'s process.

    Used for a combo box's popup list, which is a top-level window of its own.
    """
    owner = window_at(int(rect.center_x), int(rect.center_y))
    return owner is not None and process_of(owner) == process_of(top_level)


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def click(x: int, y: int, settle: float = 0.03) -> None:
    """Left-click at (x, y), then put the mouse pointer back where it was."""
    drag(x, y, x, y, settle)


def drag(from_x: int, from_y: int, to_x: int, to_y: int, settle: float = 0.03) -> None:
    """Press at one point, move to another and release, then restore the pointer.

    A drag from the thumb works on any slider, whereas a click on the track
    might only page the thumb towards the click.
    """
    original = cursor_position()
    try:
        user32.SetCursorPos(int(from_x), int(from_y))
        time.sleep(settle)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(settle)
        if (to_x, to_y) != (from_x, from_y):
            # Move in a few steps so the widget sees a drag, not a jump.
            steps = 4
            for i in range(1, steps + 1):
                user32.SetCursorPos(int(round(from_x + (to_x - from_x) * i / steps)),
                                    int(round(from_y + (to_y - from_y) * i / steps)))
                time.sleep(settle)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(settle)
    finally:
        user32.SetCursorPos(*original)
