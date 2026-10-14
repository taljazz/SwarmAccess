"""The NVDA app module for Turtle Beach Swarm II.

Two things happen here:

1. **Names.**  Swarm II's combo boxes and buttons can take keyboard focus but
   have no names, so Tab lands on "combo box, BOLD" or just "button".  An
   overlay class gives each one the name ``model.name_for_focusable`` works
   out from the label beside it.

2. **The settings list.**  Swarm II's switches and sliders cannot take focus
   at all.  While Swarm II's main window has focus, the arrow keys walk a
   list of every setting instead, and Left/Right, Space and Home/End change
   the one you are on.  See ``SwarmAppModule.__gestures`` for the keys.
"""

from __future__ import annotations

import time

import addonHandler
import api
import appModuleHandler
import controlTypes
import mouseHandler
import ui
import UIAHandler
import winUser
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from NVDAObjects.UIA import UIA
from scriptHandler import script

from . import model
from .page import SwarmPage

try:
    addonHandler.initTranslation()
except Exception:  # running from NVDA's developer scratchpad, outside an add-on
    pass

WINDOW_TITLE = "Turtle Beach Swarm II"
CATEGORY = "SwarmAccess"
# Swarm II classes that can take focus or be reached by object navigation
# but arrive without a name.
UNNAMED_CLASSES = {
    "roccat_combobox_c",
    "roccat_rotation_button_c",
    "roccat_fade_button_c",
    "roccat_colorize_button_c",
}
# Space and Enter belong to these when they have focus (Reset, Help, Save...).
BUTTON_ROLES = {controlTypes.Role.BUTTON, controlTypes.Role.TOGGLEBUTTON}
# Focus in any of these means a popup or text field is in charge of the arrows.
PASS_THROUGH_ROLES = {
    controlTypes.Role.LIST,
    controlTypes.Role.LISTITEM,
    controlTypes.Role.MENU,
    controlTypes.Role.MENUITEM,
    controlTypes.Role.POPUPMENU,
    controlTypes.Role.EDITABLETEXT,
}
# Spoken for each kind of setting, through NVDA's own role names so they
# follow the user's language.
ROLE_FOR_KIND = {
    model.SWITCH: controlTypes.Role.SWITCH,
    model.SLIDER: controlTypes.Role.SLIDER,
    model.COMBO: controlTypes.Role.COMBOBOX,
}
# How long a snapshot of the page stays good enough for naming focus.
NAME_SNAPSHOT_AGE = 2.0


def _uia_class(obj) -> str:
    try:
        return obj.UIAElement.cachedClassName
    except Exception:  # not in NVDA's cache request on every version
        return obj.UIAElement.currentClassName


class NamedSwarmControl(UIA):
    """A Swarm II control named from the label beside it."""

    def _get_name(self):
        name = super().name
        if name:
            return name
        return self.appModule.name_for(self) or name


class AppModule(appModuleHandler.AppModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page: SwarmPage | None = None
        self._position = 0
        self._name_snapshot = None
        self._name_snapshot_time = 0.0
        self._hinted = False

    # -- naming -------------------------------------------------------------

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        if isinstance(obj, UIA) and _uia_class(obj) in UNNAMED_CLASSES:
            clsList.insert(0, NamedSwarmControl)

    def name_for(self, obj) -> str | None:
        snap = self._snapshot_for_names(obj)
        if snap is None:
            return None
        automation_id = obj.UIAAutomationId
        if automation_id:
            element = next((e for e in snap.elements if e.automation_id == automation_id), None)
            return model.name_for_focusable(snap, element) if element else None
        if _uia_class(obj) == "roccat_colorize_button_c":
            return self._sidebar_name(snap, obj)
        return None

    def _sidebar_name(self, snap, obj) -> str | None:
        """The left-hand tool buttons have no object names, only an order."""
        tools = sorted(
            (e for e in snap.elements
             if e.class_name == "roccat_colorize_button_c" and not e.automation_id and e.rect),
            key=lambda e: e.rect.top,
        )
        location = obj.location
        if location is None or len(tools) != len(model.SIDEBAR_TOOLS):
            return None
        for element, name in zip(tools, model.SIDEBAR_TOOLS):
            if (element.rect.left, element.rect.top) == (location.left, location.top):
                return name
        return None

    def _snapshot_for_names(self, obj):
        now = time.monotonic()
        if self._name_snapshot is None or now - self._name_snapshot_time > NAME_SNAPSHOT_AGE:
            page = self._ensure_page(obj.windowHandle)
            if page is None:
                return None
            from .uia import take_snapshot
            try:
                root = page.client.ElementFromHandle(page.hwnd)
                self._name_snapshot, _ = take_snapshot(page.client, root)
            except Exception:
                log.debugWarning("SwarmAccess: snapshot for names failed", exc_info=True)
                return None
            self._name_snapshot_time = now
        return self._name_snapshot

    # -- the page -----------------------------------------------------------

    def _main_window(self, hwnd: int) -> int | None:
        if not hwnd:
            return None
        root = winUser.getAncestor(hwnd, winUser.GA_ROOT)
        return root if root and winUser.getWindowText(root) == WINDOW_TITLE else None

    def _ensure_page(self, hwnd: int) -> SwarmPage | None:
        main = self._main_window(hwnd)
        if main is None:
            return None
        if self._page is None or self._page.hwnd != main:
            self._page = SwarmPage(UIAHandler.handler.clientObject,
                                   UIAHandler.UIA.IUIAutomationRangeValuePattern, main)
            self._refresh()
        return self._page

    def _refresh(self) -> None:
        previous = self._current_key()
        try:
            self._page.refresh()
        except Exception:
            log.error("SwarmAccess: could not read Swarm II's controls", exc_info=True)
            self._page.settings = []
        settings = self._page.settings
        keys = [s.key for s in settings]
        self._position = keys.index(previous) if previous in keys else min(self._position, max(0, len(keys) - 1))

    def _current_key(self) -> str | None:
        if self._page and 0 <= self._position < len(self._page.settings):
            return self._page.settings[self._position].key
        return None

    def _list_ready(self, activating: bool = False) -> bool:
        """True when a key belongs to the settings list rather than to Swarm II.

        ``activating`` is for Space and Enter, which a focused button keeps.
        """
        focus = api.getFocusObject()
        if focus is None or focus.appModule is not self or focus.role in PASS_THROUGH_ROLES:
            return False
        if activating and focus.role in BUTTON_ROLES:
            return False
        if self._ensure_page(focus.windowHandle) is None:
            return False
        if not self._page.settings:
            self._refresh()
        return bool(self._page.settings)

    def event_appModule_gainFocus(self):
        # Swarm II's pages change behind our back (device unplugged, another
        # page opened), so start each visit from a fresh look at the window.
        if self._page is not None:
            self._refresh()

    def event_gainFocus(self, obj, nextHandler):
        nextHandler()
        if not self._hinted and self._main_window(obj.windowHandle):
            self._hinted = True
            ui.message(_("SwarmAccess: arrow keys move through the settings"))
        # Tabbing to a combo box that is in the list moves the list there too.
        if self._page and isinstance(obj, UIA) and obj.UIAAutomationId:
            for i, s in enumerate(self._page.settings):
                if s.element.automation_id == obj.UIAAutomationId:
                    self._position = i
                    break

    # -- speaking -----------------------------------------------------------

    @property
    def _setting(self) -> model.Setting:
        return self._page.settings[self._position]

    def _describe(self, setting: model.Setting, reading, with_section: bool = False) -> str:
        parts = []
        if with_section and setting.section:
            parts.append(setting.section)
        if setting.kind == model.STATUS:
            parts.append(f"{setting.label}: {reading.describe(setting)}")
        else:
            parts.append(setting.label)
            parts.append(ROLE_FOR_KIND[setting.kind].displayString)
            parts.append(reading.describe(setting))
        return ", ".join(parts)

    def _announce_current(self, previous_section: str | None = None) -> None:
        setting = self._setting
        reading = self._page.read(setting)
        ui.message(self._describe(setting, reading, setting.section != previous_section))

    def _move_to(self, index: int) -> None:
        settings = self._page.settings
        index = max(0, min(len(settings) - 1, index))
        previous_section = self._setting.section if settings else None
        self._position = index
        self._announce_current(previous_section)

    def _report_change(self, setting, before, after) -> None:
        if after.hidden:
            ui.message(_("{label} is not visible. Bring Swarm II to the front and try again.").format(label=setting.label))
        elif before.value == after.value and not (before.value is None and after.value is None):
            ui.message(_("{label} did not change, still {value}").format(label=setting.label, value=after.describe(setting)))
        else:
            ui.message(after.describe(setting))

    # -- scripts --------------------------------------------------------------

    def _pass_through(self, gesture, activating: bool = False) -> bool:
        """Send the key to Swarm II itself when the list is not in charge."""
        if self._list_ready(activating):
            return False
        gesture.send()
        return True

    @script(description=_("Next Swarm II setting"), category=CATEGORY, gesture="kb:downArrow")
    def script_next(self, gesture):
        if not self._pass_through(gesture):
            self._move_to(self._position + 1)

    @script(description=_("Previous Swarm II setting"), category=CATEGORY, gesture="kb:upArrow")
    def script_previous(self, gesture):
        if not self._pass_through(gesture):
            self._move_to(self._position - 1)

    @script(description=_("First Swarm II setting"), category=CATEGORY, gesture="kb:control+home")
    def script_first(self, gesture):
        if not self._pass_through(gesture):
            self._move_to(0)

    @script(description=_("Last Swarm II setting"), category=CATEGORY, gesture="kb:control+end")
    def script_last(self, gesture):
        if not self._pass_through(gesture):
            self._move_to(len(self._page.settings) - 1)

    @script(description=_("Next section of Swarm II settings"), category=CATEGORY, gesture="kb:pageDown")
    def script_next_section(self, gesture):
        if self._pass_through(gesture):
            return
        later = [i for i in model.sections(self._page.settings) if i > self._position]
        if later:
            self._move_to(later[0])
        else:
            ui.message(_("No more sections"))

    @script(description=_("Previous section of Swarm II settings"), category=CATEGORY, gesture="kb:pageUp")
    def script_previous_section(self, gesture):
        if self._pass_through(gesture):
            return
        starts = model.sections(self._page.settings)
        current = max(i for i in starts if i <= self._position)
        earlier = [i for i in starts if i < current]
        if earlier:
            self._move_to(earlier[-1])
        else:
            ui.message(_("No previous section"))

    @script(description=_("Toggle the current switch, or open the current combo box"),
            category=CATEGORY, gestures=("kb:space", "kb:enter"))
    def script_activate(self, gesture):
        if self._pass_through(gesture, activating=True):
            return
        setting = self._setting
        if setting.kind == model.SWITCH:
            before, after = self._click(lambda: self._page.toggle(setting))
            self._report_change(setting, before, after)
        elif setting.kind == model.COMBO:
            # The real combo box takes it from here, with its own list.
            self._page.focus(setting)
            KeyboardInputGesture.fromName("alt+downArrow").send()
        else:
            self._announce_current(setting.section)

    def _adjust(self, gesture, direction: int, fine: bool = False, to_end: bool = False):
        if self._pass_through(gesture):
            return
        setting = self._setting
        if setting.kind == model.SWITCH:
            if to_end:
                return
            before, after = self._click(lambda: self._page.set_switch(setting, direction > 0))
            self._report_change(setting, before, after)
        elif setting.kind == model.SLIDER:
            current = self._page.read(setting)
            if current.hidden:
                self._report_change(setting, current, current)
                return
            if current.value is None or not current.enabled:
                ui.message(_("{label} is unavailable").format(label=setting.label))
                return
            if to_end:
                target = setting.maximum if direction > 0 else setting.minimum
            else:
                step = setting.fine_step if fine else setting.step
                target = current.value + direction * step
            if setting.clamp(target) == current.value:
                ui.message(current.describe(setting))
                return
            before, after = self._click(lambda: self._page.set_slider(setting, target))
            self._report_change(setting, before, after)
        elif setting.kind == model.COMBO and not to_end:
            self._page.focus(setting)
            KeyboardInputGesture.fromName("downArrow" if direction > 0 else "upArrow").send()
        else:
            self._announce_current(setting.section)

    def _click(self, action):
        """Run a click or drag without NVDA's mouse tracking reporting it."""
        with mouseHandler.ignoreInjection():
            return action()

    @script(description=_("Increase the current slider, turn the switch on, or pick the next option"),
            category=CATEGORY, gesture="kb:rightArrow")
    def script_increase(self, gesture):
        self._adjust(gesture, +1)

    @script(description=_("Decrease the current slider, turn the switch off, or pick the previous option"),
            category=CATEGORY, gesture="kb:leftArrow")
    def script_decrease(self, gesture):
        self._adjust(gesture, -1)

    @script(description=_("Increase the current slider by one"), category=CATEGORY, gesture="kb:shift+rightArrow")
    def script_increase_fine(self, gesture):
        self._adjust(gesture, +1, fine=True)

    @script(description=_("Decrease the current slider by one"), category=CATEGORY, gesture="kb:shift+leftArrow")
    def script_decrease_fine(self, gesture):
        self._adjust(gesture, -1, fine=True)

    @script(description=_("Move the current slider to its maximum"), category=CATEGORY, gesture="kb:end")
    def script_maximum(self, gesture):
        self._adjust(gesture, +1, to_end=True)

    @script(description=_("Move the current slider to its minimum"), category=CATEGORY, gesture="kb:home")
    def script_minimum(self, gesture):
        self._adjust(gesture, -1, to_end=True)

    @script(description=_("Read Swarm II's settings again, after its page has changed"),
            category=CATEGORY, gesture="kb:NVDA+f5")
    def script_rescan(self, gesture):
        focus = api.getFocusObject()
        if self._ensure_page(focus.windowHandle) is None:
            gesture.send()
            return
        self._refresh()
        count = len(self._page.settings)
        ui.message(_("{count} settings").format(count=count) if count else _("No settings on this page"))
