"""Turn a snapshot of Swarm II's UI Automation tree into named settings.

Swarm II is a Qt application whose switches and sliders are custom widgets.
UI Automation sees them as unnamed groups with no toggle or range pattern, and
the text describing each one is a separate label.  What *is* reliable is:

* every widget's AutomationId, which Qt fills with the dotted path of object
  names from the main window down (``...wg_area_noise.wg_title_noise.switchbox_noise``);
* every widget's bounding rectangle, in physical screen pixels.

This module pairs each control with its label using those two facts, and
works out which section it belongs to and what range a slider covers.  The
label text comes from Swarm II itself, so it follows whatever the app shows.

Nothing here touches NVDA, the screen or the mouse; ``tests/test_model.py``
runs it against snapshots recorded from the real app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# Qt class names of the controls Swarm II draws for itself.
SWITCH_CLASS = "roccat_switch_box_c"
SLIDER_CLASSES = ("roccat_slider_c", "eq_slider_c")
COMBO_CLASS = "roccat_combobox_c"
LABEL_CLASSES = ("QLabel", "elide_label_c")

SWITCH = "switch"
SLIDER = "slider"
COMBO = "combo box"
STATUS = "status"

# The equalizer draws its band names itself, so they are not in the tree.
# Read off the screen on 2026-10-14; there are always ten.
EQ_BANDS = ("32 Hz", "63 Hz", "125 Hz", "250 Hz", "500 Hz",
            "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz")
# Likewise its scale, which is drawn from -9 to +9 dB.
EQ_MIN_DB = -9.0
EQ_MAX_DB = 9.0

# Read-only facts Swarm II shows as a pair of labels: (title, value).
STATUS_PAIRS = (
    ("lb_battery_status", "lb_battery_level"),
    ("lb_drivers", "lb_driver_status"),
    ("lb_connection", "lb_connection_type"),
    ("lb_status", "lb_transmitter_status"),
    ("lb_platform_mode", "lb_platform_mode_status"),
    ("label_title_high_bandwidth", "label_content_high_band"),
)
# Status titles that mean nothing on their own: under Device Status, "STATUS"
# and "PLATFORM" sit beneath a "TRANSMITTER" heading.
STATUS_LABELS = {"lb_status": "Transmitter status", "lb_platform_mode": "Transmitter platform"}

# Labels too vague to stand alone; the section name goes in front.
GENERIC_LABELS = {"levels", "level"}

# Words kept in capitals when Swarm II's ALL CAPS labels are tidied.
ACRONYMS = {"LED", "EQ", "PC", "USB", "3D", "II"}

_VALUE_LIKE = re.compile(r"^[-+]?\d+(\.\d+)?\s*(%|dB|Hz|kHz)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Rect:
    """A rectangle in physical screen pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2

    def overlaps_vertically(self, other: "Rect") -> bool:
        return self.top < other.bottom and other.top < self.bottom

    def overlaps_horizontally(self, other: "Rect") -> bool:
        return self.left < other.right and other.left < self.right

    def contains(self, other: "Rect") -> bool:
        return (self.left <= other.left and self.top <= other.top
                and other.right <= self.right and other.bottom <= self.bottom)


@dataclass(frozen=True)
class Element:
    """One node of the UI Automation tree, as much as the model needs."""

    automation_id: str
    class_name: str
    name: str = ""
    value: str = ""
    rect: Optional[Rect] = None
    index: int = 0

    @property
    def object_name(self) -> str:
        return self.automation_id.rsplit(".", 1)[-1]

    @property
    def parent_path(self) -> str:
        return self.automation_id.rsplit(".", 1)[0] if "." in self.automation_id else ""

    @classmethod
    def from_dict(cls, data: dict, index: int = 0) -> "Element":
        rect = data.get("rect")
        return cls(
            automation_id=data.get("aid", ""),
            class_name=data.get("cls", ""),
            name=data.get("name", "") or "",
            value=data.get("value", "") or "",
            rect=Rect(*(int(round(v)) for v in rect)) if rect else None,
            index=index,
        )


@dataclass
class Setting:
    """A control the settings list can announce, and change if it is not a status."""

    key: str
    kind: str
    label: str
    section: str
    element: Element
    minimum: float = 0.0
    maximum: float = 100.0
    vertical: bool = False
    end_names: Optional[tuple] = None  # ("G", "C") for the game/chat mix
    unit: str = ""
    status_value: str = ""
    value_element: Optional[Element] = None  # the label holding a status line's value

    @property
    def rect(self) -> Optional[Rect]:
        return self.element.rect

    @property
    def is_equalizer_band(self) -> bool:
        return self.kind == SLIDER and self.vertical

    @property
    def step(self) -> float:
        """Left/Right arrow step: 5 on a 0-100 slider, 1 on anything smaller."""
        return 5.0 if self.maximum - self.minimum >= 50 else 1.0

    @property
    def fine_step(self) -> float:
        return 1.0

    def clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))

    def snap(self, value: float) -> float:
        """Round a measured value to the nearest whole step Swarm II can hold."""
        return self.clamp(round(value))

    def format_value(self, value: Optional[float]) -> str:
        if value is None:
            return "unknown"
        if self.kind != SLIDER:
            return str(value)
        number = self.snap(value)
        text = _format_number(number)
        if self.unit == "dB":
            return ("+" if number > 0 else "") + text + " dB"
        if self.end_names:
            middle = (self.minimum + self.maximum) / 2
            if number == middle:
                return text + ", balanced"
            towards = self.end_names[1] if number > middle else self.end_names[0]
            return f"{text}, toward {towards}"
        return text


def _format_number(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:.1f}"


def tidy_label(text: str) -> str:
    """Make Swarm II's ALL CAPS labels speak naturally ("WAVES 3D" -> "Waves 3D")."""
    text = text.strip()
    if not text.isupper():
        return text.replace("&", "and")
    words = text.split()
    tidied = []
    for i, word in enumerate(words):
        if word in ACRONYMS or any(ch.isdigit() for ch in word):
            tidied.append(word)
        elif i == 0:
            tidied.append(word.capitalize())
        else:
            tidied.append(word.lower())
    return " ".join(tidied).replace("&", "and")


def is_value_like(text: str) -> bool:
    """True for labels that show a number or an end marker rather than a name."""
    text = text.strip()
    return len(text) <= 1 or bool(_VALUE_LIKE.match(text))


def section_frame(automation_id: str) -> str:
    """The AutomationId prefix of the panel ("..._func_fm_c" or "eq_fm_c") a control sits in."""
    parts = automation_id.split(".")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith("_func_fm_c") or parts[i] == "eq_fm_c":
            return ".".join(parts[: i + 1])
    return ""


class Snapshot:
    """A list of elements with the lookups the pairing rules need."""

    def __init__(self, elements: Iterable[Element]):
        self.elements: list[Element] = list(elements)
        self.labels = [
            e for e in self.elements
            if e.class_name in LABEL_CLASSES and e.name.strip() and e.rect is not None
        ]

    @classmethod
    def from_dicts(cls, rows: Sequence[dict]) -> "Snapshot":
        return cls(Element.from_dict(row, i) for i, row in enumerate(rows))

    def find(self, object_name: str, within: str = "") -> Optional[Element]:
        for e in self.elements:
            if e.object_name == object_name and e.automation_id.startswith(within):
                return e
        return None

    def section_title(self, frame: str) -> str:
        if not frame:
            return ""
        if frame.endswith("eq_fm_c"):
            return "Equalizer"
        for e in self.labels:
            if e.object_name == "lb_func_name" and e.automation_id.startswith(frame + "."):
                return tidy_label(e.name)
        return ""


def _same_row_label(snap: Snapshot, control: Element) -> Optional[Element]:
    """The nearest naming label on the same row, preferring the control's own container."""
    rect = control.rect
    frame = section_frame(control.automation_id)

    def candidates(same_parent: bool):
        for label in snap.labels:
            if is_value_like(label.name) or label.object_name == "lb_func_name":
                continue
            if same_parent and label.parent_path != control.parent_path:
                continue
            if not same_parent and section_frame(label.automation_id) != frame:
                continue
            if label.rect.overlaps_vertically(rect) and abs(label.rect.center_y - rect.center_y) <= max(rect.height, label.rect.height) / 2:
                yield label

    for same_parent in (True, False):
        found = list(candidates(same_parent))
        if found:
            def gap(label: Element) -> float:
                if label.rect.right <= rect.left:
                    return rect.left - label.rect.right
                if rect.right <= label.rect.left:
                    return label.rect.left - rect.right
                return 0
            return min(found, key=gap)
    return None


def _label_above(snap: Snapshot, control: Element, max_gap: int = 150) -> Optional[Element]:
    """The nearest naming label above a control and overlapping it horizontally."""
    rect = control.rect
    frame = section_frame(control.automation_id)
    best = None
    best_gap = None
    for label in snap.labels:
        if is_value_like(label.name) or label.object_name == "lb_func_name":
            continue
        if section_frame(label.automation_id) != frame:
            continue
        if not label.rect.overlaps_horizontally(rect):
            continue
        gap = rect.top - label.rect.bottom
        if -4 <= gap <= max_gap and (best_gap is None or gap < best_gap):
            best, best_gap = label, gap
    return best


def _slider_range(snap: Snapshot, control: Element) -> tuple[float, float, Optional[tuple]]:
    """Read a slider's range from the "0" and "100" labels Swarm II puts at its ends."""
    minimum = maximum = None
    for label in snap.labels:
        if label.parent_path != control.parent_path:
            continue
        if label.object_name.startswith("label_mini"):
            minimum = label.name.strip()
        elif label.object_name.startswith("label_max"):
            maximum = label.name.strip()
    try:
        return float(minimum), float(maximum), None
    except (TypeError, ValueError):
        pass
    if minimum and maximum:
        # Named ends, such as G and C on the game/chat mix: an unmarked 0 to 100.
        return 0.0, 100.0, (_end_name(minimum), _end_name(maximum))
    return 0.0, 100.0, None


def _end_name(letter: str) -> str:
    return {"G": "game", "C": "chat"}.get(letter.upper(), letter)


def build_settings(snap: Snapshot) -> list[Setting]:
    """Every switch, slider, combo box and status line, in Swarm II's own order."""
    settings: list[Setting] = []
    seen_keys: dict[str, int] = {}
    eq_bands = sorted(
        (e for e in snap.elements
         if e.class_name in SLIDER_CLASSES and e.rect is not None and "eq_setting_fm_c" in e.automation_id),
        key=lambda e: e.rect.left,
    )

    def key_for(element: Element) -> str:
        count = seen_keys.get(element.automation_id, 0)
        seen_keys[element.automation_id] = count + 1
        return element.automation_id if count == 0 else f"{element.automation_id}#{count}"

    status_titles = {title: value for title, value in STATUS_PAIRS}

    for element in snap.elements:
        if element.rect is None:
            continue
        frame = section_frame(element.automation_id)
        section = snap.section_title(frame)
        cls = element.class_name

        if cls == SWITCH_CLASS or cls == COMBO_CLASS:
            label = _same_row_label(snap, element)
            settings.append(Setting(
                key=key_for(element),
                kind=SWITCH if cls == SWITCH_CLASS else COMBO,
                label=tidy_label(label.name) if label else _fallback_label(element),
                section=section,
                element=element,
            ))
        elif cls in SLIDER_CLASSES:
            if element in eq_bands:
                band = eq_bands.index(element)
                name = EQ_BANDS[band] if len(eq_bands) == len(EQ_BANDS) else f"Band {band + 1}"
                settings.append(Setting(
                    key=key_for(element), kind=SLIDER, label=name, section=section,
                    element=element, minimum=EQ_MIN_DB, maximum=EQ_MAX_DB,
                    vertical=True, unit="dB",
                ))
                continue
            label = _label_above(snap, element)
            text = tidy_label(label.name) if label else _fallback_label(element)
            if text.lower() in GENERIC_LABELS and section:
                text = f"{section} level"
            minimum, maximum, ends = _slider_range(snap, element)
            settings.append(Setting(
                key=key_for(element), kind=SLIDER, label=text, section=section,
                element=element, minimum=minimum, maximum=maximum, end_names=ends,
                vertical=element.rect.height > element.rect.width,
            ))
        elif cls in LABEL_CLASSES and element.object_name in status_titles:
            value = snap.find(status_titles[element.object_name], within=element.parent_path)
            if value is None or not value.name.strip():
                continue
            text = STATUS_LABELS.get(element.object_name) or tidy_label(element.name)
            settings.append(Setting(
                key=key_for(element), kind=STATUS, label=text, section=section,
                element=element, status_value=value.name.strip(), value_element=value,
            ))

    _disambiguate(settings)
    return settings


def _fallback_label(element: Element) -> str:
    name = element.object_name
    for prefix in ("switchbox_", "slider_content_", "slider_", "cb_", "btn_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").strip().capitalize() or "Unlabelled"


def _disambiguate(settings: list[Setting]) -> None:
    """A switch, a combo box and a slider often share one label; tell them apart.

    "Noise gate" is the switch, "Noise gate level" its slider, and "Chat boost
    mode" the combo box beside the Chat boost switch.
    """
    switches = {(s.section, s.label) for s in settings if s.kind == SWITCH}
    for s in settings:
        if (s.section, s.label) not in switches:
            continue
        if s.kind == SLIDER:
            s.label += " level"
        elif s.kind == COMBO:
            s.label += " mode"


def sections(settings: Sequence[Setting]) -> list[int]:
    """Indexes where a new section starts, for Page Up and Page Down."""
    starts = []
    previous = None
    for i, s in enumerate(settings):
        if s.section != previous:
            starts.append(i)
            previous = s.section
    return starts


# Names for the controls Tab can reach, which Swarm II leaves unnamed.
# Keyed by Qt object name; a callable gets the snapshot and element.
def name_for_focusable(snap: Snapshot, element: Element) -> Optional[str]:
    """The name NVDA should give an unnamed Swarm II control, or None to leave it."""
    obj = element.object_name
    frame = section_frame(element.automation_id)
    section = snap.section_title(frame)
    if element.class_name == COMBO_CLASS:
        label = _same_row_label(snap, element)
        if label is None:
            return None
        text = tidy_label(label.name)
        partner_switch = any(
            e.class_name == SWITCH_CLASS and e.parent_path == element.parent_path for e in snap.elements
        )
        return text + (" mode" if partner_switch else "")
    if obj == "btn_reset":
        return f"Reset {section}" if section else "Reset"
    if obj == "btn_info":
        return f"{section} help" if section else "Help"
    if obj == "btn_high_band":
        title = snap.find("label_title_high_bandwidth", within=element.parent_path)
        value = snap.find("label_content_high_band", within=element.parent_path)
        if title is None:
            return None
        text = tidy_label(title.name)
        if value is not None and value.name.strip():
            text += f", {value.name.strip()}"
        return text + ", Windows sound settings"
    if obj == "btn_back":
        return "Back"
    if obj == "btn_minimized":
        return "Minimize"
    if obj == "btn_maximized":
        return "Maximize"
    if obj == "btn_close":
        return "Close"
    return None


# Swarm II's left-hand tool buttons have no object names, only their order.
# Their tooltips, read on 2026-10-14, top to bottom:
SIDEBAR_TOOLS = ("Macro Manager", "Settings", "Device Manager", "Help")
