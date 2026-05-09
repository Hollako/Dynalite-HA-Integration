"""HA services for Dynalite PDEG integration."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, LOGGER

# ── Service names ────────────────────────────────────────────────────────────
SERVICE_SCAN          = "scan"
SERVICE_SELECT_PRESET = "select_preset"
SERVICE_SET_LEVEL     = "set_level"
SERVICE_SEND_RAW      = "send_raw_frame"

# ── Schemas ──────────────────────────────────────────────────────────────────
SCAN_SCHEMA = vol.Schema(
    {
        vol.Optional("area_min", default=2):      vol.All(int, vol.Range(min=1, max=255)),
        vol.Optional("area_max", default=20):     vol.All(int, vol.Range(min=1, max=255)),
        vol.Optional("channel_count", default=8): vol.All(int, vol.Range(min=1, max=64)),
        vol.Optional("delay_ms", default=50):     vol.All(int, vol.Range(min=10, max=500)),
    }
)

SELECT_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("area"):   vol.All(int, vol.Range(min=1, max=255)),
        vol.Required("preset"): vol.All(int, vol.Range(min=1, max=255)),
    }
)

SET_LEVEL_SCHEMA = vol.Schema(
    {
        vol.Required("area"):    vol.All(int, vol.Range(min=1, max=255)),
        vol.Required("channel"): vol.All(int, vol.Range(min=0, max=63)),
        vol.Required("level"):   vol.All(int, vol.Range(min=0, max=100)),
    }
)

SEND_RAW_SCHEMA = vol.Schema(
    {
        vol.Required("frame"): cv.string,
        vol.Optional("compute_checksum", default=True): cv.boolean,
    }
)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-level services."""

    def _get_coordinator(call: ServiceCall):
        """Return the first loaded coordinator (single-entry assumption)."""
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                return entry.runtime_data
        return None

    async def handle_scan(call: ServiceCall) -> None:
        coordinator = _get_coordinator(call)
        if not coordinator:
            LOGGER.error("[Service] scan: no active coordinator found")
            return
        await coordinator.async_scan(
            area_min=call.data["area_min"],
            area_max=call.data["area_max"],
            channel_count=call.data["channel_count"],
            delay_ms=call.data["delay_ms"],
        )

    async def handle_select_preset(call: ServiceCall) -> None:
        coordinator = _get_coordinator(call)
        if not coordinator:
            return
        await coordinator.cmd_select_preset(call.data["area"], call.data["preset"])

    async def handle_set_level(call: ServiceCall) -> None:
        coordinator = _get_coordinator(call)
        if not coordinator:
            return
        await coordinator.cmd_set_level(
            call.data["area"], call.data["channel"], call.data["level"]
        )

    async def handle_send_raw(call: ServiceCall) -> None:
        coordinator = _get_coordinator(call)
        if not coordinator:
            LOGGER.error("[Service] send_raw_frame: no active coordinator found")
            return
        raw = call.data["frame"]
        compute_cs = call.data["compute_checksum"]
        # Accept space-separated hex, e.g. "5C FF FF 40 00 00 0A 00"
        # or compact hex, e.g.            "5CFF FF400000 0A00"
        try:
            frame = bytes.fromhex(raw.replace(" ", "").replace(":", ""))
        except ValueError as exc:
            LOGGER.error("[Service] send_raw_frame: invalid hex '%s': %s", raw, exc)
            return
        if len(frame) < 2:
            LOGGER.error("[Service] send_raw_frame: frame too short (%d bytes)", len(frame))
            return
        if compute_cs:
            # Replace last byte with correct checksum over all preceding bytes
            cs = (-sum(frame[:-1])) & 0xFF
            frame = frame[:-1] + bytes([cs])
            LOGGER.info("[Service] send_raw_frame (cs=0x%02X computed): %s",
                        cs, frame.hex(" ").upper())
        else:
            LOGGER.info("[Service] send_raw_frame (cs=as-given): %s", frame.hex(" ").upper())
        if not coordinator.client.connected:
            LOGGER.warning("[Service] send_raw_frame: not connected, frame dropped")
            return
        coordinator.client._writer.write(frame)
        await coordinator.client._writer.drain()

    hass.services.async_register(DOMAIN, SERVICE_SCAN,          handle_scan,          SCAN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SELECT_PRESET, handle_select_preset, SELECT_PRESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_LEVEL,     handle_set_level,     SET_LEVEL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_RAW,      handle_send_raw,      SEND_RAW_SCHEMA)
    LOGGER.debug("[Services] registered: scan, select_preset, set_level, send_raw_frame")
