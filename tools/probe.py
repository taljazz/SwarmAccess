"""Run the add-on's model and pixel reader against the live Swarm II window.

This is the bench for everything that does not need NVDA: it takes the same
UI Automation snapshot the add-on takes, builds the same settings list, and
reads values from the same pixels, so a wrong label or a misread slider shows
up here before it ever reaches a screen reader.

    tools/.venv/Scripts/python tools/probe.py list [--scroll]
    tools/.venv/Scripts/python tools/probe.py set "Noise gate level" 20
    tools/.venv/Scripts/python tools/probe.py snapshot tests/fixtures/name.json
    tools/.venv/Scripts/python tools/probe.py scroll 560

Needs comtypes, and Pillow for ``grab`` (tools/requirements.txt).  Read-only
apart from ``scroll`` and ``list --scroll``, which move Swarm II's page, and
``set``, which really changes the headset setting it names.
"""

from __future__ import annotations

import ctypes
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "addon" / "appModules"))

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, like NVDA and UIA

import comtypes.client  # noqa: E402

from _swarmAccess import model, page, screen, uia  # noqa: E402

WINDOW_TITLE = "Turtle Beach Swarm II"


def client():
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA
    return comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation), UIA


def swarm_window() -> int:
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        sys.exit("Swarm II's window was not found.")
    return hwnd


def snapshot():
    uia_client, UIA = client()
    root = uia_client.ElementFromHandle(swarm_window())
    snap, live = uia.take_snapshot(uia_client, root)
    return snap, live, UIA


def open_page() -> page.SwarmPage:
    uia_client, UIA = client()
    swarm = page.SwarmPage(uia_client, UIA.IUIAutomationRangeValuePattern, swarm_window())
    swarm.refresh()
    return swarm


def cmd_list(args):
    """Every setting and its value; with --scroll, scrolls each one into view first."""
    scroll = "--scroll" in args
    swarm = open_page()
    section = None
    for s in swarm.settings:
        if s.section != section:
            section = s.section
            print(f"\n== {section}")
        reading = swarm.read(s, scroll=scroll)
        rect = swarm.rect(s)
        where = f"{rect.left},{rect.top} {rect.width}x{rect.height}" if rect else "-"
        print(f"  {s.label}, {s.kind}, {reading.describe(s)}    [{where}]")


def find_setting(swarm, label):
    wanted = label.lower()
    for s in swarm.settings:
        if s.label.lower() == wanted:
            return s
    sys.exit(f"No setting called {label!r}.")


def cmd_set(args):
    """Change a setting, then report what the screen shows: set "<label>" on|off|toggle|<number>."""
    swarm = open_page()
    setting = find_setting(swarm, args[0])
    wanted = args[1].lower()
    if setting.kind == model.SWITCH:
        on = {"on": True, "off": False, "toggle": None}[wanted]
        before, after = swarm.set_switch(setting, on)
    elif setting.kind == model.SLIDER:
        before, after = swarm.set_slider(setting, float(wanted))
    else:
        sys.exit("Only switches and sliders can be set.")
    print(f"{setting.label}: {before.describe(setting)} -> {after.describe(setting)}")


def cmd_snapshot(args):
    snap, _live, _ = snapshot()
    rows = []
    for e in snap.elements:
        rows.append({
            "aid": e.automation_id, "cls": e.class_name, "name": e.name, "value": e.value,
            "rect": [e.rect.left, e.rect.top, e.rect.width, e.rect.height] if e.rect else None,
        })
    path = pathlib.Path(args[0])
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{len(rows)} elements written to {path}")


def cmd_scroll(args):
    snap, live, UIA = snapshot()
    bar = next(
        (el for e, el in zip(snap.elements, live) if e.class_name == "roccat_scrollbar_c" and e.rect and e.rect.height > 500),
        None,
    )
    pattern = uia.range_value_pattern(bar, UIA.IUIAutomationRangeValuePattern)
    print("was", pattern.CurrentValue, "of", pattern.CurrentMaximum)
    if args:
        pattern.SetValue(float(args[0]))
        print("now", pattern.CurrentValue)


def cmd_grab(args):
    """Save one setting's pixels as a test fixture: grab "<label>" <file.png>."""
    from PIL import Image
    snap, _live, _ = snapshot()
    wanted = args[0].lower()
    setting = next(s for s in model.build_settings(snap) if s.label.lower() == wanted)
    if not screen.is_showing(swarm_window(), setting.rect):
        sys.exit(f"{setting.label} is not showing on screen.")
    captured = screen.capture(setting.rect)
    image = Image.new("RGB", (captured.width, captured.height))
    image.putdata([captured.pixel(x, y) for y in range(captured.height) for x in range(captured.width)])
    image.save(args[1])
    print(f"{setting.label}: {setting.rect} saved to {args[1]}")


COMMANDS = {"list": cmd_list, "set": cmd_set, "snapshot": cmd_snapshot, "scroll": cmd_scroll, "grab": cmd_grab}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](sys.argv[2:])
