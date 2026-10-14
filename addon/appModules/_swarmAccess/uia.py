"""Take a snapshot of Swarm II's UI Automation tree in one cross-process call.

Works with any comtypes ``IUIAutomation`` client: inside NVDA that is
``UIAHandler.handler.clientObject``; ``tools/probe.py`` creates its own.
Property and pattern ids are the documented numeric constants, so this module
needs no generated comtypes wrappers of its own.
"""

from __future__ import annotations

import math
from typing import Optional

from .model import Element, Rect, Snapshot

UIA_BoundingRectanglePropertyId = 30001
UIA_NamePropertyId = 30005
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_ValueValuePropertyId = 30045
UIA_RangeValuePatternId = 10003
TreeScope_Element = 1
TreeScope_Descendants = 4

_PROPERTIES = (
    UIA_AutomationIdPropertyId,
    UIA_ClassNamePropertyId,
    UIA_NamePropertyId,
    UIA_ValueValuePropertyId,
    UIA_BoundingRectanglePropertyId,
)


def rect_from_uia(value) -> Optional[Rect]:
    """UIA reports (left, top, width, height); offscreen widgets report infinities."""
    try:
        left, top, width, height = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (left, top, width, height)) or width <= 0 or height <= 0:
        return None
    return Rect(int(round(left)), int(round(top)), int(round(width)), int(round(height)))


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def take_snapshot(client, root) -> tuple[Snapshot, list]:
    """Snapshot every element under ``root`` (a window's IUIAutomationElement).

    Returns the snapshot and the live UIA elements in the same order, so a
    caller can go back to the real element for a setting it found.
    """
    request = client.CreateCacheRequest()
    for prop in _PROPERTIES:
        request.AddProperty(prop)
    found = root.FindAllBuildCache(TreeScope_Descendants, client.CreateTrueCondition(), request)
    elements = []
    live = []
    for i in range(found.Length):
        el = found.GetElement(i)
        elements.append(Element(
            automation_id=_text(el.GetCachedPropertyValue(UIA_AutomationIdPropertyId)),
            class_name=_text(el.GetCachedPropertyValue(UIA_ClassNamePropertyId)),
            name=_text(el.GetCachedPropertyValue(UIA_NamePropertyId)),
            value=_text(el.GetCachedPropertyValue(UIA_ValueValuePropertyId)),
            rect=rect_from_uia(el.GetCachedPropertyValue(UIA_BoundingRectanglePropertyId)),
            index=i,
        ))
        live.append(el)
    return Snapshot(elements), live


def current_rect(element) -> Optional[Rect]:
    """A live element's rectangle now, which changes whenever the page scrolls."""
    return rect_from_uia(element.GetCurrentPropertyValue(UIA_BoundingRectanglePropertyId))


def current_name(element) -> str:
    return _text(element.GetCurrentPropertyValue(UIA_NamePropertyId))


def current_value(element) -> str:
    return _text(element.GetCurrentPropertyValue(UIA_ValueValuePropertyId))


def range_value_pattern(element, interface):
    """The element's RangeValue pattern as ``interface`` (IUIAutomationRangeValuePattern)."""
    unknown = element.GetCurrentPattern(UIA_RangeValuePatternId)
    return unknown.QueryInterface(interface) if unknown else None
