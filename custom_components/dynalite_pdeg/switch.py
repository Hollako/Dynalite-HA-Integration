"""Dynalite switch platform — occupancy toggle and on/off channel switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .const import LOGGER
from .coordinator import CHANNEL_TYPE_SWITCH, AreaState, ChannelState, DynaliteCoordinator
from .entity import DynaliteAreaEntity, DynaliteChannelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DynaliteCoordinator = entry.runtime_data

    # ── Occupancy switches (one per PIR area) ─────────────────────────────────
    known_pir: set[int] = set()

    def _add_occ_switches() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.has_pir and ar.area not in known_pir:
                known_pir.add(ar.area)
                new_entities.append(DynaliteOccupancySwitch(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    def _remove_occ_switch(area: int) -> None:
        """Allow the occupancy switch to be re-added if PIR is re-enabled."""
        known_pir.discard(area)

    _add_occ_switches()
    coordinator.on_new_pir_cbs.append(_add_occ_switches)
    coordinator.on_remove_pir_cbs.append(_remove_occ_switch)

    # ── Channel switches (channel_type == "switch") ───────────────────────────
    known_ch: set[tuple[int, int]] = set()

    def _add_channel_switches() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            for ch in ar.channels.values():
                key = (ch.area, ch.ch0)
                if ch.channel_type == CHANNEL_TYPE_SWITCH and key not in known_ch:
                    known_ch.add(key)
                    new_entities.append(DynaliteChannelSwitch(coordinator, ch.area, ch.ch0))
        if new_entities:
            async_add_entities(new_entities)

    def _forget_channel_switch(area: int, ch0: int) -> None:
        known_ch.discard((area, ch0))

    _add_channel_switches()
    coordinator.on_new_channel_cbs.append(_add_channel_switches)
    coordinator.on_channel_type_change_cbs.append(_forget_channel_switch)


# ── Occupancy enable/disable switch ───────────────────────────────────────────

class DynaliteOccupancySwitch(DynaliteAreaEntity, SwitchEntity):
    """Toggle occupancy detection on/off for a PIR area (0x3B / 0x3A)."""

    _attr_name = "En/Dis Occupancy"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_occ_switch"

    @property
    def is_on(self) -> bool:
        ar = self._coordinator.areas.get(self._area)
        return ar.occ_enabled if ar else True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coordinator.cmd_occupancy_enable(self._area)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.cmd_occupancy_disable(self._area)

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()


# ── Channel switch (on/off via set_level 100 / 0) ─────────────────────────────

class DynaliteChannelSwitch(DynaliteChannelEntity, SwitchEntity):
    """A Dynalite channel exposed as a HA switch (full on / full off)."""

    _attr_icon = "mdi:toggle-switch-variant"

    def __init__(self, coordinator: DynaliteCoordinator, area: int, ch0: int) -> None:
        super().__init__(coordinator, area, ch0)
        self._attr_unique_id = f"{coordinator.host}_a{area}_c{ch0}_switch"
        self._attr_name = self._default_name()

    def _default_name(self) -> str:
        ar = self._coordinator.areas.get(self._area)
        ch = ar.channels.get(self._ch0) if ar else None
        return ch.name if ch and ch.name else f"Ch {self._ch0 + 1}"

    def _ch_state(self) -> ChannelState | None:
        ar = self._coordinator.areas.get(self._area)
        return ar.channels.get(self._ch0) if ar else None

    @property
    def is_on(self) -> bool:
        ch = self._ch_state()
        return ch.is_on if ch else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        LOGGER.info("[Switch] turn_on  A%d Ch%d", self._area, self._ch0 + 1)
        ch = self._ch_state()
        if ch:
            ch.pct = 100
            ch.is_on = True
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, 100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        LOGGER.info("[Switch] turn_off A%d Ch%d", self._area, self._ch0 + 1)
        ch = self._ch_state()
        if ch:
            ch.pct = 0
            ch.is_on = False
        self.async_write_ha_state()
        await self._coordinator.cmd_set_level(self._area, self._ch0, 0)

    @callback
    def _on_channel_update(self, ch: ChannelState) -> None:
        if ch.name:
            self._attr_name = ch.name
        self.async_write_ha_state()
