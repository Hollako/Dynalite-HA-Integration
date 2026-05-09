"""Persistence layer for Dynalite PDEG integration.

Saves discovered areas/channels to HA's .storage directory so that entities
survive restarts without waiting for bus traffic.

Storage format (version 1):
{
  "areas": [
    {
      "area": 3,
      "name": "Living Room",
      "preset_count": 4,
      "fade_tenths": 20,
      "has_pir": true,
      "occ_enabled": true,
      "channels": [
        {"ch0": 0, "name": "Main Light", "is_dimmable": true},
        {"ch0": 1, "name": "Wall Light", "is_dimmable": false}
      ]
    }
  ]
}

Only structural data is persisted (names, types, counts).
Runtime state (levels, temps, motion) is intentionally excluded — it is
re-populated from the bus within seconds of connecting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, LOGGER, SIGNON_INTERVAL
from .coordinator import (
    AREA_TYPE_LIGHT,
    CHANNEL_TYPE_DIMMER,
    CHANNEL_TYPE_ONOFF,
    AreaState,
    ChannelState,
    PhysicalDevice,
)

if TYPE_CHECKING:
    from .coordinator import DynaliteCoordinator

STORAGE_VERSION = 1


class DynaliteStorage:
    """Wraps HA Store for Dynalite entity persistence."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}_{entry_id}",
            private=True,
            atomic_writes=True,
        )

    # ── Load ──────────────────────────────────────────────────────────────────

    async def async_load(self, coordinator: DynaliteCoordinator) -> None:
        """Populate coordinator with persisted areas/channels.

        Must be called BEFORE the TCP client is started so that platform
        setup_entry can immediately register entities without waiting for
        live bus traffic.
        """
        raw = await self._store.async_load()
        if not raw:
            LOGGER.debug("[Storage] no saved state found")
            return

        loaded_areas = 0
        loaded_channels = 0

        for a in raw.get("areas", []):
            area_num = a.get("area")
            if not area_num:
                continue

            ar = AreaState(
                area=area_num,
                name=a.get("name", ""),
                preset_count=int(a.get("preset_count", 4)),
                fade_tenths=int(a.get("fade_tenths", 20)),
                area_type=a.get("area_type", AREA_TYPE_LIGHT),
                has_pir=bool(a.get("has_pir", False)),
                occ_enabled=bool(a.get("occ_enabled", True)),
            )

            for c in a.get("channels", []):
                ch0 = c.get("ch0")
                if ch0 is None:
                    continue
                # Backward compat: old files used is_dimmable bool
                if "channel_type" in c:
                    ch_type = c["channel_type"]
                elif c.get("is_dimmable", True):
                    ch_type = CHANNEL_TYPE_DIMMER
                else:
                    ch_type = CHANNEL_TYPE_ONOFF
                partner = c.get("cover_partner_ch0")
                ch = ChannelState(
                    area=area_num,
                    ch0=int(ch0),
                    name=c.get("name", ""),
                    channel_type=ch_type,
                    cover_partner_ch0=int(partner) if partner is not None else None,
                )
                ar.channels[ch.ch0] = ch
                loaded_channels += 1

            coordinator.areas[area_num] = ar
            loaded_areas += 1

        # ── Restore device names ──────────────────────────────────────────────
        for d in raw.get("devices", []):
            code = d.get("device_code")
            box  = d.get("box_number")
            if code is None or box is None:
                continue
            key = (int(code), int(box))
            from .const import DEVICE_NAMES  # noqa: PLC0415
            model = DEVICE_NAMES.get(int(code), f"Device 0x{int(code):02X}")
            coordinator.devices[key] = PhysicalDevice(
                device_code=int(code),
                box_number=int(box),
                model=model,
                name=d.get("name", ""),
            )

        # Restore configurable settings
        if "signon_interval" in raw:
            coordinator.signon_interval = int(raw["signon_interval"])

        LOGGER.info(
            "[Storage] restored %d areas, %d channels, %d devices  signon_interval=%ds",
            loaded_areas,
            loaded_channels,
            len(coordinator.devices),
            coordinator.signon_interval,
        )

    # ── Save ──────────────────────────────────────────────────────────────────

    async def async_save(self, coordinator: DynaliteCoordinator) -> None:
        """Serialise coordinator state and write to .storage."""
        data = self._serialize(coordinator)
        await self._store.async_save(data)
        LOGGER.debug(
            "[Storage] saved %d areas", len(data["areas"])
        )

    async def async_remove(self) -> None:
        """Wipe the storage file (called on integration unload/delete)."""
        await self._store.async_remove()

    # ── Serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(coordinator: DynaliteCoordinator) -> dict:
        areas = []
        for ar in coordinator.areas.values():
            channels = []
            for ch in ar.channels.values():
                entry: dict = {
                    "ch0": ch.ch0,
                    "name": ch.name,
                    "channel_type": ch.channel_type,
                }
                if ch.cover_partner_ch0 is not None:
                    entry["cover_partner_ch0"] = ch.cover_partner_ch0
                channels.append(entry)
            areas.append(
                {
                    "area": ar.area,
                    "name": ar.name,
                    "preset_count": ar.preset_count,
                    "fade_tenths": ar.fade_tenths,
                    "area_type": ar.area_type,
                    "has_pir": ar.has_pir,
                    "occ_enabled": ar.occ_enabled,
                    "channels": channels,
                }
            )

        # Persist ALL discovered devices (so binary sensors survive restarts)
        devices = [
            {
                "device_code": dev.device_code,
                "box_number":  dev.box_number,
                "name":        dev.name,
            }
            for dev in coordinator.devices.values()
        ]

        return {
            "areas":           areas,
            "devices":         devices,
            "signon_interval": coordinator.signon_interval,
        }
