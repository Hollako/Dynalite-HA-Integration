"""Dynalite cover platform — two types:

- DynaliteAreaCover  : area_type == "blind" — controlled via 3 configurable presets
                       (Open / Stop / Close).  One cover entity per area.
- DynaliteChannelCover: channel_type == "cover" in any area — paired UP/DOWN relay
                        channels with interlock delay.  Unchanged behaviour.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .coordinator import AREA_TYPE_BLIND, CHANNEL_TYPE_COVER, DynaliteCoordinator
from .entity import DynaliteAreaEntity

# Time (seconds) to stop the opposite relay before engaging the new direction.
_STOP_DELAY = 0.5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register cover entities for both blind areas and cover channels."""
    coordinator: DynaliteCoordinator = entry.runtime_data
    known_channels: set[tuple[int, int]]     = set()   # (area, up_ch0)
    known_curtains: set[tuple[int, int]]     = set()   # (area, curtain_idx)

    def _add_covers() -> None:
        new_entities: list = []

        # ── Preset-based blind areas (one cover entity per curtain) ───────────
        for ar in coordinator.areas.values():
            if ar.area_type == AREA_TYPE_BLIND:
                for idx, curtain in enumerate(ar.curtains):
                    key = (ar.area, idx)
                    if key not in known_curtains:
                        known_curtains.add(key)
                        new_entities.append(DynaliteAreaCover(coordinator, ar.area, idx))

        # ── Channel-based relay covers ────────────────────────────────────────
        for ar in coordinator.areas.values():
            for ch in ar.channels.values():
                key = (ch.area, ch.ch0)
                if (
                    ch.channel_type == CHANNEL_TYPE_COVER
                    and ch.cover_partner_ch0 is not None
                    and key not in known_channels
                ):
                    known_channels.add(key)
                    new_entities.append(
                        DynaliteChannelCover(
                            coordinator, ch.area, ch.ch0, ch.cover_partner_ch0
                        )
                    )

        if new_entities:
            async_add_entities(new_entities)

    def _forget_channel_cover(area: int, ch0: int) -> None:
        known_channels.discard((area, ch0))

    _add_covers()
    coordinator.on_new_area_cbs.append(_add_covers)
    coordinator.on_new_channel_cbs.append(_add_covers)
    coordinator.on_channel_type_change_cbs.append(_forget_channel_cover)


# ── Preset-based area cover (Blind area type) ─────────────────────────────────

class DynaliteAreaCover(DynaliteAreaEntity, CoverEntity):
    """Cover entity for one curtain inside a Blind-type area.

    Each curtain has its own Open / Stop / Close preset numbers, configurable
    in the panel.  Multiple curtains may exist per area.  State is optimistic.
    """

    _attr_device_class        = CoverDeviceClass.BLIND
    _attr_supported_features  = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    _attr_assumed_state   = True
    _attr_should_poll     = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: DynaliteCoordinator, area: int, curtain_idx: int) -> None:
        super().__init__(coordinator, area)
        self._curtain_idx     = curtain_idx
        self._attr_unique_id  = f"{coordinator.host}_a{area}_curtain_{curtain_idx}"
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed  = None   # unknown until first command
        self._refresh_name()

    def _get_curtain(self) -> dict | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and self._curtain_idx < len(ar.curtains):
            return ar.curtains[self._curtain_idx]
        return None

    def _refresh_name(self) -> None:
        c = self._get_curtain()
        if c and c.get("name"):
            self._attr_name = c["name"]
        else:
            self._attr_name = f"Curtain {self._curtain_idx + 1}"

    @property
    def is_closed(self) -> bool | None:
        return self._attr_is_closed

    @property
    def is_opening(self) -> bool:
        return self._attr_is_opening

    @property
    def is_closing(self) -> bool:
        return self._attr_is_closing

    async def async_open_cover(self, **kwargs: Any) -> None:
        c      = self._get_curtain()
        preset = c["open_preset"] if c else 1
        await self._coordinator.cmd_select_preset(self._area, preset)
        self._attr_is_opening = True
        self._attr_is_closing = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        c      = self._get_curtain()
        preset = c["close_preset"] if c else 2
        await self._coordinator.cmd_select_preset(self._area, preset)
        self._attr_is_closing = True
        self._attr_is_opening = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        c      = self._get_curtain()
        preset = c["stop_preset"] if c else 3
        await self._coordinator.cmd_select_preset(self._area, preset)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.async_write_ha_state()

    @callback
    def _on_area_update(self, ar) -> None:
        self._refresh_name()
        self.async_write_ha_state()


# ── Channel-based relay cover (paired Up/Down channels) ───────────────────────

class DynaliteChannelCover(DynaliteAreaEntity, CoverEntity):
    """Cover controlled by two Dynalite relay channels: up and down.

    Control logic:
    - Open  → stop DOWN relay → 0.5 s → energise UP relay
    - Close → stop UP relay   → 0.5 s → energise DOWN relay
    - Stop  → de-energise both relays immediately

    State is fully optimistic (no position sensor).
    """

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    _attr_assumed_state = True
    _attr_should_poll   = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DynaliteCoordinator,
        area: int,
        up_ch0: int,
        down_ch0: int,
    ) -> None:
        super().__init__(coordinator, area)
        self._up_ch0   = up_ch0
        self._down_ch0 = down_ch0
        self._attr_unique_id  = f"{coordinator.host}_a{area}_cover_{up_ch0}_{down_ch0}"
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed  = None
        self._refresh_name()

    def _refresh_name(self) -> None:
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._up_ch0) if ar else None
        if ch and ch.name:
            self._attr_name = ch.name
        else:
            self._attr_name = f"Cover {self._up_ch0 + 1}/{self._down_ch0 + 1}"

    @property
    def is_closed(self) -> bool | None:
        return self._attr_is_closed

    @property
    def is_opening(self) -> bool:
        return self._attr_is_opening

    @property
    def is_closing(self) -> bool:
        return self._attr_is_closing

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 0,   fade_tenths=0)
        await asyncio.sleep(_STOP_DELAY)
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   100, fade_tenths=0)
        self._attr_is_opening = True
        self._attr_is_closing = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   0,   fade_tenths=0)
        await asyncio.sleep(_STOP_DELAY)
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 100, fade_tenths=0)
        self._attr_is_closing = True
        self._attr_is_opening = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   0, fade_tenths=0)
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 0, fade_tenths=0)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.async_write_ha_state()

    @callback
    def _on_area_update(self, ar) -> None:
        self._refresh_name()
        self.async_write_ha_state()
