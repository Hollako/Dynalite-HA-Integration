"""Dynalite climate platform — HVAC areas mapped to presets."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .coordinator import AreaState, DynaliteCoordinator
from .entity import DynaliteAreaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Climate entities are added when an area has temperature + setpoint data."""
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[int] = set()

    def _add_climate() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.has_temp and ar.has_setpt and ar.area not in known:
                known.add(ar.area)
                new_entities.append(DynaliteClimate(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_climate()
    coordinator.on_new_climate = _add_climate  # type: ignore[attr-defined]


class DynaliteClimate(DynaliteAreaEntity, ClimateEntity):
    """Climate entity for a Dynalite HVAC area.

    Modes are mapped to presets; temperature/setpoint come from bus opcodes.
    Mode list and fan speeds can be expanded via options flow (future).
    """

    _attr_name = "Climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 16.0
    _attr_max_temp = 32.0
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    # Preset mapping: hvac_mode → 1-based Dynalite preset
    _MODE_TO_PRESET: dict[str, int] = {
        HVACMode.OFF:      4,
        HVACMode.COOL:     1,
        HVACMode.HEAT:     2,
        HVACMode.FAN_ONLY: 3,
        HVACMode.AUTO:     5,
    }
    _PRESET_TO_MODE: dict[int, str] = {v: k for k, v in _MODE_TO_PRESET.items()}

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_climate"

    @property
    def current_temperature(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.has_temp and not math.isnan(ar.temp_c):
            return round(ar.temp_c, 1)
        return None

    @property
    def target_temperature(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.has_setpt and not math.isnan(ar.setpt_c):
            return round(ar.setpt_c, 1)
        return None

    @property
    def hvac_mode(self) -> HVACMode | None:
        ar = self._coordinator.areas.get(self._area)
        if ar is None or ar.preset0 == 0xFF:
            return None
        mode = self._PRESET_TO_MODE.get(ar.preset0 + 1)
        return HVACMode(mode) if mode else HVACMode.AUTO

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        preset1 = self._MODE_TO_PRESET.get(hvac_mode, 1)
        await self._coordinator.cmd_select_preset(self._area, preset1)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Setpoint changes are sent via a dedicated opcode (future)."""
        # TODO: send setpoint opcode once spec is confirmed
        pass

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()
