"""Dynalite cover platform — two-channel relay blinds (up + down)."""

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
from .coordinator import CHANNEL_TYPE_COVER, DynaliteCoordinator
from .entity import DynaliteAreaEntity

# Time (seconds) to stop the opposite relay before engaging the new direction.
# Prevents both relays being energised simultaneously.
_STOP_DELAY = 0.5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register a cover entity for every channel-pair marked as cover type."""
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()   # (area, up_ch0)

    def _add_covers() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            for ch in ar.channels.values():
                key = (ch.area, ch.ch0)
                if (
                    ch.channel_type == CHANNEL_TYPE_COVER
                    and ch.cover_partner_ch0 is not None
                    and key not in known
                ):
                    known.add(key)
                    new_entities.append(
                        DynaliteChannelCover(
                            coordinator, ch.area, ch.ch0, ch.cover_partner_ch0
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    _add_covers()
    coordinator.on_new_channel_cbs.append(_add_covers)


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
        self._attr_is_closed  = None   # optimistic: unknown position
        self._refresh_name()

    # ── Name ─────────────────────────────────────────────────────────────────

    def _refresh_name(self) -> None:
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._up_ch0) if ar else None
        if ch and ch.name:
            self._attr_name = ch.name
        else:
            self._attr_name = f"Cover {self._up_ch0 + 1}/{self._down_ch0 + 1}"

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_closed(self) -> bool | None:
        return self._attr_is_closed

    @property
    def is_opening(self) -> bool:
        return self._attr_is_opening

    @property
    def is_closing(self) -> bool:
        return self._attr_is_closing

    # ── Commands ─────────────────────────────────────────────────────────────

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Stop downward motion, wait, then drive upward."""
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 0,   fade_tenths=0)
        await asyncio.sleep(_STOP_DELAY)
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   100, fade_tenths=0)
        self._attr_is_opening = True
        self._attr_is_closing = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Stop upward motion, wait, then drive downward."""
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   0,   fade_tenths=0)
        await asyncio.sleep(_STOP_DELAY)
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 100, fade_tenths=0)
        self._attr_is_closing = True
        self._attr_is_opening = False
        self._attr_is_closed  = False
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """De-energise both relays."""
        await self._coordinator.cmd_set_level(self._area, self._up_ch0,   0, fade_tenths=0)
        await self._coordinator.cmd_set_level(self._area, self._down_ch0, 0, fade_tenths=0)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.async_write_ha_state()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    @callback
    def _on_area_update(self, ar) -> None:
        self._refresh_name()
        self.async_write_ha_state()
