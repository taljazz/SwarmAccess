"""Read Swarm II's switches and sliders from screen pixels.

Swarm II gives screen readers nothing about these widgets except where they
are, so the only way to know a switch's state or a slider's value is to look
at it, the way a sighted user does:

* A switch is a pill.  On, its track is Swarm II purple (about 117, 56, 255)
  with the white knob at the right; off, the track is grey and the knob sits
  at the left.
* A slider is a thin track with a round thumb.  The thumb is the only thing
  in the slider's rectangle that is tall and light grey to white (it dims when
  the slider is disabled), so the thumb's centre is found from the columns
  (rows, for the vertical equalizer bands) holding the most such pixels.

The thumb's centre never reaches the very ends of the rectangle: it stops
``THUMB_INSET`` pixels short of each end, measured on the live app.

Everything here works on a ``PixelSource``, so the tests can feed in recorded
pixels and NVDA can feed in a fresh screen capture.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

Pixel = Tuple[int, int, int]

# Distance, in physical pixels, from either end of a slider's rectangle to the
# thumb's centre at that end of the range.  Measured 2026-10-14; see README.
THUMB_INSET = 12.0

# A switch counts as on when at least this share of its middle row is purple.
SWITCH_ON_SHARE = 0.25
# ...and as off when no more than this share is.
SWITCH_OFF_SHARE = 0.05


class PixelSource:
    """A rectangle of screen pixels, addressed from its own top-left corner."""

    width: int
    height: int

    def pixel(self, x: int, y: int) -> Pixel:
        raise NotImplementedError


class GridSource(PixelSource):
    """Pixels held as rows of (r, g, b) tuples; used by the tests."""

    def __init__(self, rows: Sequence[Sequence[Pixel]]):
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0]) if rows else 0

    def pixel(self, x: int, y: int) -> Pixel:
        return tuple(self.rows[y][x][:3])


def is_purple(p: Pixel) -> bool:
    r, g, b = p
    return b >= 150 and b - g >= 80 and b - r >= 40


def is_thumb(p: Pixel, floor: int = 150) -> bool:
    """Light, colourless pixels: the white thumb (or, with a lower floor, a dimmed one)."""
    r, g, b = p
    return min(r, g, b) >= floor and max(r, g, b) - min(r, g, b) <= 40


def read_switch(src: PixelSource) -> Optional[bool]:
    """True for on, False for off, None when the pixels look like neither."""
    if src.width < 8 or src.height < 4:
        return None
    y = src.height // 2
    row = [src.pixel(x, y) for x in range(src.width)]
    purple = sum(1 for p in row if is_purple(p)) / len(row)
    knob = [x for x, p in enumerate(row) if is_thumb(p)]
    if not knob:
        return None
    knob_right = sum(knob) / len(knob) > src.width / 2
    if purple >= SWITCH_ON_SHARE and knob_right:
        return True
    if purple <= SWITCH_OFF_SHARE and not knob_right:
        return False
    return None


def describe_switch(state: Optional[bool]) -> str:
    return {True: "on", False: "off"}.get(state, "unknown")


# Brightness floors for the two kinds of thumb.  An enabled thumb is pure
# white; a disabled one (Superhuman Hearing's level while it is switched off)
# is a dull grey, about (73, 76, 82), only a little lighter than the track.
ENABLED_FLOOR = 150
DISABLED_FLOOR = 66
# A thumb is about 22 pixels across; anything much thinner is a tick mark or
# the track, anything much wider is something covering the slider.
THUMB_MIN_SPAN = 12
THUMB_MAX_SPAN = 40


def _thumb_run(src: PixelSource, vertical: bool, floor: int) -> Optional[float]:
    length = src.height if vertical else src.width
    across = src.width if vertical else src.height
    counts = []
    for along in range(length):
        count = 0
        for side in range(across):
            p = src.pixel(side, along) if vertical else src.pixel(along, side)
            if is_thumb(p, floor):
                count += 1
        counts.append(count)
    peak = max(counts) if counts else 0
    if peak < 8:
        return None
    threshold = peak * 0.5
    best = max(range(length), key=lambda i: counts[i])
    start = best
    while start > 0 and counts[start - 1] >= threshold:
        start -= 1
    end = best
    while end < length - 1 and counts[end + 1] >= threshold:
        end += 1
    if not THUMB_MIN_SPAN <= end - start + 1 <= THUMB_MAX_SPAN:
        return None
    run = range(start, end + 1)
    total = sum(counts[i] for i in run)
    return sum(i * counts[i] for i in run) / total + 0.5


def thumb_center(src: PixelSource, vertical: bool = False) -> tuple[Optional[float], bool]:
    """Where the thumb's centre is along the slider, and whether it looks enabled.

    The position is in pixels from the start of the rectangle; for a vertical
    slider, from the *top*.  Returns (None, False) when no thumb is visible.
    """
    center = _thumb_run(src, vertical, ENABLED_FLOOR)
    if center is not None:
        return center, True
    return _thumb_run(src, vertical, DISABLED_FLOOR), False


def value_from_position(position: float, length: int, minimum: float, maximum: float,
                        vertical: bool = False, inset: float = THUMB_INSET) -> float:
    """Turn a thumb position into a slider value.  Vertical sliders grow upwards."""
    usable = max(1.0, length - 2 * inset)
    fraction = (position - inset) / usable
    fraction = max(0.0, min(1.0, fraction))
    if vertical:
        fraction = 1.0 - fraction
    return minimum + fraction * (maximum - minimum)


def position_for_value(value: float, length: int, minimum: float, maximum: float,
                       vertical: bool = False, inset: float = THUMB_INSET) -> float:
    """Where to put the thumb's centre for ``value``: the inverse of value_from_position."""
    span = maximum - minimum
    fraction = 0.0 if span == 0 else (value - minimum) / span
    fraction = max(0.0, min(1.0, fraction))
    if vertical:
        fraction = 1.0 - fraction
    return inset + fraction * max(1.0, length - 2 * inset)


def read_slider(src: PixelSource, setting) -> tuple[Optional[float], bool]:
    """A slider's value read from its pixels, and whether it is enabled.

    The value is None if no thumb can be seen.
    """
    center, enabled = thumb_center(src, setting.vertical)
    if center is None:
        return None, False
    length = src.height if setting.vertical else src.width
    return value_from_position(center, length, setting.minimum, setting.maximum, setting.vertical), enabled
