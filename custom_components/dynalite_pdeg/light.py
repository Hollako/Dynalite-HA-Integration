"""Dynalite light platform — dimmable and on/off channels."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .const import LOGGER, ha_brightness_to_pct, pct_to_ha_brightness, signal_channel
from .coordinator import AREA_TYPE_HVAC, CHANNEL_TYPE_DIMMER, CHANNEL_TYPE_ONOFF, ChannelState, DynaliteCoordinator
from .entity import DynaliteChannelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities.

    Entities are added dynamically as channels are discovered on the bus.
    The coordinator fires signal_channel() whenever a new channel appears;
    we also scan existing channels on load.
    """
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    def _add_new_channels() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            # HVAC areas have no light channels — their channels are mode/fan
            # control signals managed exclusively by the climate entity.
            if ar.area_type == AREA_TYPE_HVAC:
                continue
            # Channels used as the DOWN partner of a cover must not get a light entity
            cover_partners = {
                ch.cover_partner_ch0
                for ch in ar.channels.values()
                if ch.cover_partner_ch0 is not None
            }
            for ch in ar.channels.values():
                key = (ch.area, ch.ch0)
                if key in known:
                    continue
                known.add(key)
                if ch.ch0 in cover_partners:
                    continue  # this is the DOWN relay of a cover — no light entity
                if ch.channel_type == CHANNEL_TYPE_DIMMER:
                    new_entities.append(DynaliteDimmableLight(coordinator, ch.area, ch.ch0))
                elif ch.channel_type == CHANNEL_TYPE_ONOFF:
                    new_entities.append(DynaliteOnOffLight(coordinator, ch.area, ch.ch0))
                # switch / cover handled by their own platforms
        if new_entities:
            async_add_entities(new_entities)

    # Scan on load
    _add_new_channels()

    # Subscribe to new channel signals (area * channel wildcard not possible in HA
    # dispatcher, so coordinator calls this helper when new channels appear)
    coordinator.on_new_channel_cbs.append(_add_new_channels)


# ── Dimmable light ────────────────────────────────────────────────────────────

class DynaliteDimmableLight(DynaliteChannelEntity, LightEntity):
    """A dimmable Dynalite channel."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: DynaliteCoordinator, area: int, ch0: int) -> None:
        super().__init__(coordinator, area, ch0)
        self._attr_unique_id = f"{coordinator.host}_a{area}_c{ch0}_light"
        self._attr_name = self._default_name()

    def _default_name(self) -> str:
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._ch0) if ar else None
        if ch and ch.name:
            return ch.name
        return f"Ch {self._ch0 + 1}"

    @property
    def brightness(self) -> int:
        ch = self._ch_state()
        return pct_to_ha_brightness(ch.pct) if ch else 0

    @property
    def is_on(self) -> bool:
        ch = self._ch_state()
        return ch.is_on if ch else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        pct = 100
        if ATTR_BRIGHTNESS in kwargs:
            pct = ha_brightness_to_pct(kwargs[ATTR_BRIGHTNESS])
            pct = max(1, pct)
        LOGGER.info("[Light/Dim] turn_on  A%d Ch%d → %d%%", self._area, self._ch0 + 1, pct)
        # Optimistic update — reflect immediately, bus report will confirm
        ch = self._ch_state()
        if ch:
            ch.pct = pct
            ch.is_on = pct > 0
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, pct)

    async def async_turn_off(self, **kwargs: Any) -> None:
        LOGGER.info("[Light/Dim] turn_off A%d Ch%d", self._area, self._ch0 + 1)
        # Optimistic update
        ch = self._ch_state()
        if ch:
            ch.pct = 0
            ch.is_on = False
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, 0)

    def _ch_state(self) -> ChannelState | None:
        ar = self._coordinator.areas.get(self._area)
        return ar.channels.get(self._ch0) if ar else None

    @callback
    def _on_channel_update(self, ch: ChannelState) -> None:
        # Update name if it has changed
        if ch.name:
            self._attr_name = ch.name
        self.async_write_ha_state()


# ── On/Off light ──────────────────────────────────────────────────────────────

class DynaliteOnOffLight(DynaliteChannelEntity, LightEntity):
    """A non-dimmable (relay) Dynalite channel exposed as a light."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator: DynaliteCoordinator, area: int, ch0: int) -> None:
        super().__init__(coordinator, area, ch0)
        self._attr_unique_id = f"{coordinator.host}_a{area}_c{ch0}_light_onoff"
        ar = coordinator.areas.get(area)
        ch = ar.channels.get(ch0) if ar else None
        self._attr_name = (ch.name if ch and ch.name else f"Ch {ch0 + 1}")

    @property
    def is_on(self) -> bool:
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._ch0) if ar else None
        return ch.is_on if ch else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        LOGGER.info("[Light/OnOff] turn_on  A%d Ch%d", self._area, self._ch0 + 1)
        # Optimistic update
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._ch0) if ar else None
        if ch:
            ch.pct = 100
            ch.is_on = True
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, 100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        LOGGER.info("[Light/OnOff] turn_off A%d Ch%d", self._area, self._ch0 + 1)
        # Optimistic update
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._ch0) if ar else None
        if ch:
            ch.pct = 0
            ch.is_on = False
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, 0)
