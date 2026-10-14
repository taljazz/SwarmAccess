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
SLIDER_ATTEMPTS = 5
SMALL_DRAG = 10  # pixels
POPUP_SETTLE = 0.35

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

    def __init__(self, client, interfaces, hwnd: int):
        """``interfaces`` is comtypes' generated UIAutomationClient module."""
        self.client = client
        self.interfaces = interfaces
        self.range_value_interface = interfaces.IUIAutomationRangeValuePattern
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
        """Move a slider to ``target`` by dragging its thumb; returns the readings before and after.

        Where Swarm II puts the thumb for a given drag wobbles by about one
        step (0.1 dB on the equalizer, under 3 pixels), so the slider is read
        back after each drag.  If it landed short or long, the aim is moved by
        that many steps' worth of pixels (half as far once it has overshot) and
        the thumb dragged again, up to ``SLIDER_ATTEMPTS`` drags in all.
        """
        rect = self.bring_into_view(setting)
        if rect is None:
            return Reading(hidden=True), Reading(hidden=True)
        before = self._read_pixels(setting, rect)
        if before.value is None or not before.enabled:
            return before, before
        target = setting.snap(target)
        length, thickness = (rect.height, rect.width) if setting.vertical else (rect.width, rect.height)
        insets = pixels.insets_for(setting, thickness)
        goal = pixels.position_for_value(target, length, setting.minimum, setting.maximum, setting.vertical, insets)
        pixels_per_unit = (length - insets[0] - insets[1]) / (setting.maximum - setting.minimum)
        latest = before
        gain = 1.0
        last_miss = 0.0
        for _attempt in range(SLIDER_ATTEMPTS):
            if latest.value == target:
                break
            if not self._drag_thumb(setting, rect, goal):
                break
            landed = self._settled_reading(setting)
            if landed.hidden or landed.value is None:
                return before, landed
            if landed.value != target:
                # Aim off by however far it missed (upwards is smaller on a
                # vertical slider).  If the last correction overshot, halve
                # the next one, so the aim closes in from both sides.
                miss = (target - landed.value) * pixels_per_unit
                if miss * last_miss < 0:
                    gain /= 2
                last_miss = miss
                goal += (-miss if setting.vertical else miss) * gain
            latest = landed
        return before, latest

    def _drag_thumb(self, setting: Setting, rect: Rect, goal: float) -> bool:
        """Drag the thumb from where it is drawn to ``goal`` (pixels from the slider's start)."""
        center = self._thumb(setting, rect)
        if center is None:
            return False
        if abs(goal - center) < SMALL_DRAG:
            # Swarm II ignores a drag of only a few pixels, and one that swings
            # out and back within a single press.  So a small correction is two
            # drags: well away first, then back to the goal.
            away = center - SMALL_DRAG * 2 if center - SMALL_DRAG * 2 > 0 else center + SMALL_DRAG * 2
            self._drag_along(setting, rect, center, away)
            time.sleep(CHANGE_POLL * 2)
            center = self._thumb(setting, rect)
            if center is None:
                return False
        self._drag_along(setting, rect, center, goal)
        return True

    def _thumb(self, setting: Setting, rect: Rect) -> Optional[float]:
        center, enabled = pixels.thumb_center(screen.capture(rect), setting.vertical)
        return center if enabled else None

    @staticmethod
    def _drag_along(setting: Setting, rect: Rect, start: float, end: float) -> None:
        """Drag along the slider's axis between two positions measured from its start."""
        if setting.vertical:
            x = int(rect.center_x)
            screen.drag(x, int(round(rect.top + start)), x, int(round(rect.top + end)))
        else:
            y = int(rect.center_y)
            screen.drag(int(round(rect.left + start)), y, int(round(rect.left + end)), y)

    def _settled_reading(self, setting: Setting) -> Reading:
        """Read a control once it has stopped moving after a drag."""
        time.sleep(SCROLL_SETTLE)
        previous = None
        deadline = time.monotonic() + CHANGE_TIMEOUT
        while True:
            rect = self.rect(setting)
            if rect is None or not screen.is_showing(self.hwnd, rect):
                return Reading(hidden=True)
            reading = self._read_pixels(setting, rect)
            if (previous is not None and reading.value == previous.value) or time.monotonic() > deadline:
                return reading
            previous = reading
            time.sleep(CHANGE_POLL)

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

    def choose_option(self, setting: Setting, step: int) -> tuple[Reading, Reading, list[str]]:
        """Pick the next (+1) or previous (-1) option of a combo box.

        Swarm II's combo boxes open a standard Qt list, and UI Automation can
        open it and name its items.  But neither Invoke nor Select on an item
        commits the choice (tried 2026-10-14), so the option is clicked, once
        the click point is confirmed to be Swarm II's own popup.
        Returns the readings before and after, and the option names.
        """
        combo = self.live(setting.element)
        before = Reading(uia.current_value(combo))
        expander = uia.pattern(combo, uia.UIA_ExpandCollapsePatternId,
                               self.interfaces.IUIAutomationExpandCollapsePattern)
        if expander is None:
            return before, before, []
        expander.Expand()
        try:
            items = []
            deadline = time.monotonic() + CHANGE_TIMEOUT
            while not items and time.monotonic() < deadline:
                time.sleep(CHANGE_POLL)
                items = uia.list_items(self.client, combo)
            names = [item.CurrentName for item in items]
            if not items:
                return before, before, names
            # The popup slides open; a click while it moves can change what the
            # combo box shows without Swarm II acting on it (seen 2026-10-14).
            time.sleep(POPUP_SETTLE)
            current = names.index(before.value) if before.value in names else 0
            wanted = current + step
            if not 0 <= wanted < len(items):
                return before, before, names
            target = uia.current_rect(items[wanted])
            if target is None or not screen.belongs_to_process(self.hwnd, target):
                return before, Reading(hidden=True), names
            screen.click(int(target.center_x), int(target.center_y))
        finally:
            time.sleep(CHANGE_POLL)
            if expander.CurrentExpandCollapseState != uia.ExpandCollapseState_Collapsed:
                expander.Collapse()
        deadline = time.monotonic() + CHANGE_TIMEOUT
        after = before
        while time.monotonic() < deadline:
            after = Reading(uia.current_value(combo))
            if after.value != before.value:
                break
            time.sleep(CHANGE_POLL)
        return before, after, names

    def open_list(self, setting: Setting) -> bool:
        """Open a combo box's popup and give focus to its chosen option."""
        combo = self.live(setting.element)
        expander = uia.pattern(combo, uia.UIA_ExpandCollapsePatternId,
                               self.interfaces.IUIAutomationExpandCollapsePattern)
        if expander is None:
            return False
        combo.SetFocus()
        expander.Expand()
        current = uia.current_value(combo)
        deadline = time.monotonic() + CHANGE_TIMEOUT
        while time.monotonic() < deadline:
            items = uia.list_items(self.client, combo)
            if items:
                chosen = next((i for i in items if i.CurrentName == current), items[0])
                chosen.SetFocus()
                return True
            time.sleep(CHANGE_POLL)
        return False

    def focus(self, setting: Setting) -> None:
        """Give keyboard focus to a real Swarm II control (the combo boxes can take it)."""
        self.live(setting.element).SetFocus()
