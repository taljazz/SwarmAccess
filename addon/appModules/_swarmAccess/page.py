"""Swarm II's settings page: find, read and change its controls.

This is everything the add-on does to Swarm II, kept apart from NVDA's
speech and keyboard handling so ``tools/probe.py`` can drive the very same
code against the live app:

* the settings list, rebuilt from a fresh UI Automation snapshot;
* scrolling a control into view through the page scrollbar's RangeValue
  pattern, which Swarm II does expose;
* reading a switch or slider from the screen, but only after checking that
  nothing is covering it;
* changing one with a mouse click or drag at a position worked out from its
  rectangle, then reading it back to confirm what actually happened.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from . import model, pixels, screen, uia
from .model import Rect, Setting

# How long to wait for Swarm II to repaint after a scroll or a click.
SCROLL_SETTLE = 0.12
CHANGE_TIMEOUT = 0.8
CHANGE_POLL = 0.05

VIEWPORT_SUFFIX = "main_page_fm_c.scrollArea.qt_scrollarea_viewport"
CONTENT_SUFFIX = VIEWPORT_SUFFIX + ".scrollAreaWidgetContents"
SCROLLBAR_CLASS = "roccat_scrollbar_c"


@dataclass
class Reading:
    """What a control showed when it was looked at."""

    value: object = None      # True/False for a switch, a number for a slider, text otherwise
    enabled: bool = True
    hidden: bool = False      # covered, scrolled away or off screen: nothing could be read

    def describe(self, setting: Setting) -> str:
        if self.hidden:
            return "not visible"
        if setting.kind == model.SWITCH:
            text = pixels.describe_switch(self.value)
        elif setting.kind == model.SLIDER:
            text = setting.format_value(self.value)
        else:
            text = str(self.value) if self.value else "blank"
        return text if self.enabled else text + ", unavailable"


class SwarmPage:
    """The live settings page of one Swarm II window."""

    def __init__(self, client, range_value_interface, hwnd: int):
        self.client = client
        self.range_value_interface = range_value_interface
        self.hwnd = hwnd
        self.settings: list[Setting] = []
        self._live: list = []
        self._viewport = None
        self._content = None
        self._scrollbar = None

    # -- snapshot -----------------------------------------------------------

    def refresh(self) -> None:
        root = self.client.ElementFromHandle(self.hwnd)
        snap, live = uia.take_snapshot(self.client, root)
        self._live = live
        self.settings = model.build_settings(snap)
        self._viewport = self._content = self._scrollbar = None
        viewport_rect = None
        for element, live_element in zip(snap.elements, live):
            if element.automation_id.endswith(VIEWPORT_SUFFIX):
                self._viewport, viewport_rect = live_element, element.rect
            elif element.automation_id.endswith(CONTENT_SUFFIX):
                self._content = live_element
        if viewport_rect is not None:
            # The page's scrollbar is the one standing against the viewport's right edge.
            for element, live_element in zip(snap.elements, live):
                if (element.class_name == SCROLLBAR_CLASS and element.rect is not None
                        and abs(element.rect.left - viewport_rect.right) <= 8
                        and abs(element.rect.top - viewport_rect.top) <= 8):
                    self._scrollbar = live_element

    def live(self, element: model.Element):
        return self._live[element.index]

    def rect(self, setting: Setting) -> Optional[Rect]:
        return uia.current_rect(self.live(setting.element))

    # -- scrolling ----------------------------------------------------------

    def bring_into_view(self, setting: Setting) -> Optional[Rect]:
        """Scroll until the control is wholly on screen; its rectangle, or None if it cannot be seen."""
        rect = self.rect(setting)
        if rect is None:
            return None
        viewport = uia.current_rect(self._viewport) if self._viewport is not None else None
        if viewport is not None and not viewport.contains(rect) and self._scroll_to(rect, viewport):
            time.sleep(SCROLL_SETTLE)
            rect = self.rect(setting)
        if rect is None or not screen.is_showing(self.hwnd, rect):
            return None
        return rect

    def _scroll_to(self, rect: Rect, viewport: Rect) -> bool:
        if self._scrollbar is None or self._content is None:
            return False
        content = uia.current_rect(self._content)
        pattern = uia.range_value_pattern(self._scrollbar, self.range_value_interface)
        if content is None or pattern is None:
            return False
        low, high = pattern.CurrentMinimum, pattern.CurrentMaximum
        travel = content.height - viewport.height
        if high <= low or travel <= 0:
            return False
        # The scrollbar counts in Qt's logical pixels; the rectangles are
        # physical.  At 150% scaling one step of the bar is 1.5 pixels.
        per_step = travel / (high - low)
        wanted_top = (rect.top - content.top) + rect.height / 2 - viewport.height / 2
        pattern.SetValue(max(low, min(high, low + wanted_top / per_step)))
        return True

    # -- reading ------------------------------------------------------------

    def read(self, setting: Setting, scroll: bool = True) -> Reading:
        if setting.kind == model.STATUS:
            text = ""
            if setting.value_element is not None:
                text = uia.current_name(self.live(setting.value_element)).strip()
            return Reading(text or setting.status_value)
        if setting.kind == model.COMBO:
            return Reading(uia.current_value(self.live(setting.element)))
        rect = self.bring_into_view(setting) if scroll else self.rect(setting)
        if rect is None or not screen.is_showing(self.hwnd, rect):
            return Reading(hidden=True)
        return self._read_pixels(setting, rect)

    def _read_pixels(self, setting: Setting, rect: Rect) -> Reading:
        captured = screen.capture(rect)
        if setting.kind == model.SWITCH:
            state = pixels.read_switch(captured)
            return Reading(state)
        value, enabled = pixels.read_slider(captured, setting)
        return Reading(None if value is None else setting.snap(value), enabled)

    # -- changing -----------------------------------------------------------

    def toggle(self, setting: Setting) -> tuple[Reading, Reading]:
        """Click a switch; returns the readings before and after."""
        return self.set_switch(setting, None)

    def set_switch(self, setting: Setting, on: Optional[bool]) -> tuple[Reading, Reading]:
        """Turn a switch on or off (None flips it).  Clicks only if it needs to change."""
        rect = self.bring_into_view(setting)
        if rect is None:
            return Reading(hidden=True), Reading(hidden=True)
        before = self._read_pixels(setting, rect)
        if before.value is None or (on is not None and before.value == on):
            return before, before
        screen.click(int(rect.center_x), int(rect.center_y))
        return before, self._wait_for_change(setting, before)

    def set_slider(self, setting: Setting, target: float) -> tuple[Reading, Reading]:
        """Move a slider to ``target`` by dragging its thumb; returns the readings before and after."""
        rect = self.bring_into_view(setting)
        if rect is None:
            return Reading(hidden=True), Reading(hidden=True)
        captured = screen.capture(rect)
        center, enabled = pixels.thumb_center(captured, setting.vertical)
        before = self._read_pixels(setting, rect)
        if center is None or not enabled:
            return before, before
        target = setting.clamp(target)
        length = rect.height if setting.vertical else rect.width
        goal = pixels.position_for_value(target, length, setting.minimum, setting.maximum, setting.vertical)
        if setting.vertical:
            x = int(rect.center_x)
            screen.drag(x, int(rect.top + center), x, int(round(rect.top + goal)))
        else:
            y = int(rect.center_y)
            screen.drag(int(rect.left + center), y, int(round(rect.left + goal)), y)
        return before, self._wait_for_change(setting, before)

    def _wait_for_change(self, setting: Setting, before: Reading) -> Reading:
        """Read again until the control shows something new, or the timeout passes."""
        deadline = time.monotonic() + CHANGE_TIMEOUT
        latest = before
        while time.monotonic() < deadline:
            time.sleep(CHANGE_POLL)
            rect = self.rect(setting)
            if rect is None or not screen.is_showing(self.hwnd, rect):
                return Reading(hidden=True)
            latest = self._read_pixels(setting, rect)
            if latest.value != before.value and latest.value is not None:
                # A switch animates; give it one more beat to finish moving.
                time.sleep(CHANGE_POLL)
                return self._read_pixels(setting, rect)
        return latest

    def focus(self, setting: Setting) -> None:
        """Give keyboard focus to a real Swarm II control (the combo boxes can take it)."""
        self.live(setting.element).SetFocus()
