"""Parser for Dynalite System Builder XML export files.

Two export types are supported:

  Logical XML  (<LogicalExport …>)
    → Area id/name/category/preset_count + Channel id/name/type
    → Use this to import areas and channels into the integration.

  Devices XML  (<DeviceExport …>)
    → DeviceInfo device_code (decimal)/box_number/name/product_name/is_sensor
    → Use this to import physical devices into the integration.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


# ── Category → area_type ──────────────────────────────────────────────────────
_AREA_CATEGORY: dict[str, str] = {
    "Lighting": "light",
    "HVAC":     "hvac",
    "Custom":   "blind",   # "Custom" in System Builder = curtains / blinds
}

# ── XML tag detection ─────────────────────────────────────────────────────────

def detect_xml_type(content: str) -> str | None:
    """Return 'logical', 'devices', or None if unrecognised."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    if root.tag == "LogicalExport":
        return "logical"
    if root.tag == "DeviceExport":
        return "devices"
    return None


# ── Logical XML parser ────────────────────────────────────────────────────────

def parse_logical_xml(content: str) -> list[dict]:
    """Parse a System Builder Logical XML export.

    Returns a list of area dicts:
      {
        "area":         int,           # Dynalite area number (1-based)
        "name":         str,
        "area_type":    str,           # "light" | "hvac" | "blind"
        "preset_count": int,
        "fade_tenths":  int,           # 2 s default (not in XML)
        "channels": [
          {"ch0": int, "name": str, "channel_type": str}
        ]
      }
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    areas: list[dict] = []

    for area_el in root.findall("Area"):
        try:
            area_id = int(area_el.get("id", "0"))
        except ValueError:
            continue
        if area_id <= 0:
            continue

        name         = (area_el.get("name") or f"Area {area_id}").strip()
        category     = area_el.get("category") or "Lighting"
        preset_count = max(1, int(area_el.get("preset_count") or "4"))
        area_type    = _AREA_CATEGORY.get(category, "light")

        channels: list[dict] = []
        for ch_el in area_el.findall("Channel"):
            try:
                ch_id = int(ch_el.get("id", "0"))
            except ValueError:
                continue
            if ch_id <= 0:
                continue

            ch0      = ch_id - 1   # XML is 1-based; HA/coordinator is 0-based
            ch_name  = (ch_el.get("name") or f"Channel {ch_id}").strip()
            try:
                ch_type_val = int(ch_el.get("type") or "3")
            except ValueError:
                ch_type_val = 3
            channel_type = _map_channel_type(ch_type_val, area_type)

            channels.append({
                "ch0":          ch0,
                "name":         ch_name,
                "channel_type": channel_type,
            })

        areas.append({
            "area":         area_id,
            "name":         name,
            "area_type":    area_type,
            "preset_count": preset_count,
            "fade_tenths":  20,     # 2 s default; XML does not store fade time
            "channels":     channels,
        })

    return areas


# ── Devices XML parser ────────────────────────────────────────────────────────

def parse_devices_xml(content: str) -> list[dict]:
    """Parse a System Builder Devices XML export.

    Returns a list of physical device dicts (de-duplicated by code+box):
      {
        "device_code": int,     # decimal (e.g. 220 = 0xDC)
        "box_number":  int,
        "name":        str,     # user-given name in System Builder
        "model":       str,     # product_name (e.g. "DUS360CR")
        "is_sensor":   bool,
      }
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    seen:    set[tuple[int, int]] = set()
    devices: list[dict]           = []

    for dd in root.findall("DeviceDetails"):
        info = dd.find("DeviceInfo")
        if info is None:
            continue
        try:
            device_code = int(info.get("device_code") or "0")
            box_number  = int(info.get("box_number")  or "0")
        except ValueError:
            continue

        key = (device_code, box_number)
        if key in seen:
            continue
        seen.add(key)

        name         = (info.get("name")         or "").strip()
        product_name = (info.get("product_name") or "").strip()
        is_sensor    = (info.get("is_sensor")    or "false").lower() == "true"

        devices.append({
            "device_code": device_code,
            "box_number":  box_number,
            "name":        name,
            "model":       product_name,
            "is_sensor":   is_sensor,
        })

    devices.sort(key=lambda d: (d["box_number"], d["device_code"]))
    return devices


# ── Helpers ───────────────────────────────────────────────────────────────────

def _map_channel_type(type_val: int, area_type: str) -> str:
    """Map System Builder Channel.type to HA channel_type string.

    System Builder Channel type values observed:
      0  = Standard (non-tunable) dimmer
      3  = LED dimmer (most common)
      19 = Tunable White / DALI
    All are treated as "dimmer" since we cannot distinguish relay vs dimmer
    from the XML alone.  Channels inside "blind" (Custom) areas default to
    "switch" — the user pairs them as covers manually if needed.
    """
    if area_type == "blind":
        return "switch"
    return "dimmer"
