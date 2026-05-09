"""Dynalite climate platform — HVAC areas with configurable mode and fan control."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .coordinator import AREA_TYPE_HVAC, AreaState, DynaliteCoordinator
from .entity import DynaliteAreaEntity

# Tolerance (% points) when reverse-mapping a channel level back to a mode/fan label
_LEVEL_TOLERANCE = 5

# All HVAC modes the panel can assign
HVAC_MODE_LABELS: dict[str, str] = {
    "off":      "Off",
    "cool":     "Cool",
    "heat":     "Heat",
    "fan_only": "Fan Only",
    "auto":     "Auto",
    "dry":      "Dry",
}

# All fan-speed strings the panel can assign
FAN_MODE_LABELS: dict[str, str] = {
    "off":    "Off",
    "low":    "Low",
    "medium": "Medium",
    "high":   "High",
    "auto":   "Auto",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Climate entities are added for every area with area_type == 'hvac'."""
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[int] = set()

    def _add_climate() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.area_type == AREA_TYPE_HVAC and ar.area not in known:
                known.add(ar.area)
                # Seed a default setpoint so the entity shows a value immediately
                if not ar.has_setpt or math.isnan(ar.setpt_c):
                    ar.has_setpt = True
                    ar.setpt_c   = 22.0
                new_entities.append(DynaliteClimate(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_climate()
    coordinator.on_new_climate_cbs.append(_add_climate)
    coordinator.on_new_area_cbs.append(_add_climate)


class DynaliteClimate(DynaliteAreaEntity, ClimateEntity):
    """Climate entity for a Dynalite HVAC area.

    HVAC mode and fan speed are each independently configurable as either:
      - Preset-based: selecting a Dynalite preset activates a mode/speed
      - Channel-based: setting a channel level % activates a mode/speed

    Temperature setpoint uses opcode 0x48 (Q2 signed int16, °C × 4).
    """

    _attr_name             = "Climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp         = 16.0
    _attr_max_temp         = 32.0

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_climate"

    # ── Dynamic capability properties ─────────────────────────────────────────

    @property
    def target_temperature_step(self) -> float:
        ar = self._coordinator.areas.get(self._area)
        return ar.setpt_step if ar else 0.5

    @property
    def hvac_modes(self) -> list[HVACMode]:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.hvac_mode_map:
            modes = []
            for key in ar.hvac_mode_map:
                try:
                    modes.append(HVACMode(key))
                except ValueError:
                    pass
            if modes:
                return modes
        # Fallback: at least OFF
        return [HVACMode.OFF]

    @property
    def fan_modes(self) -> list[str] | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.hvac_fan_method and ar.hvac_fan_map:
            return list(ar.hvac_fan_map.keys())
        return None

    @property
    def supported_features(self) -> ClimateEntityFeature:
        ar = self._coordinator.areas.get(self._area)
        feats = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if ar and ar.hvac_fan_method and ar.hvac_fan_map:
            feats |= ClimateEntityFeature.FAN_MODE
        return feats

    # ── State properties ──────────────────────────────────────────────────────

    @property
    def current_temperature(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        # Show temperature whenever bus data is available — has_temp flag is for
        # the standalone sensor entity only; the climate entity always shows temp.
        if ar and not math.isnan(ar.temp_c):
            return round(ar.temp_c, 1)
        return None

    @property
    def target_temperature(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.has_setpt and not math.isnan(ar.setpt_c):
            return round(ar.setpt_c, 1)
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        ar = self._coordinator.areas.get(self._area)
        if ar is None or not ar.hvac_mode_method or not ar.hvac_mode_map:
            return HVACMode.OFF

        ctl_ar = self._coordinator.areas.get(ar.hvac_mode_area or self._area)

        if ar.hvac_mode_method == "preset":
            if ctl_ar is None or ctl_ar.preset0 == 0xFF:
                return HVACMode.OFF
            preset1 = ctl_ar.preset0 + 1
            for mode_str, p in ar.hvac_mode_map.items():
                if p == preset1:
                    try:
                        return HVACMode(mode_str)
                    except ValueError:
                        pass
            return HVACMode.OFF

        if ar.hvac_mode_method == "channel":
            if ctl_ar is None:
                return HVACMode.OFF
            ch = ctl_ar.channels.get(ar.hvac_mode_ch0)
            if ch is None:
                return HVACMode.OFF
            return self._level_to_mode(ch.pct, ar.hvac_mode_map) or HVACMode.OFF

        return HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        ar = self._coordinator.areas.get(self._area)
        if ar is None or not ar.hvac_fan_method or not ar.hvac_fan_map:
            return None

        ctl_ar = self._coordinator.areas.get(ar.hvac_fan_area or self._area)

        if ar.hvac_fan_method == "preset":
            if ctl_ar is None or ctl_ar.preset0 == 0xFF:
                return None
            preset1 = ctl_ar.preset0 + 1
            for fan_str, p in ar.hvac_fan_map.items():
                if p == preset1:
                    return fan_str
            return None

        if ar.hvac_fan_method == "channel":
            if ctl_ar is None:
                return None
            ch = ctl_ar.channels.get(ar.hvac_fan_ch0)
            if ch is None:
                return None
            return self._level_to_mode(ch.pct, ar.hvac_fan_map)

        return None

    # ── Commands ──────────────────────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        ar = self._coordinator.areas.get(self._area)
        if ar is None:
            return
        mode_str = hvac_mode.value
        ctl_area = ar.hvac_mode_area or self._area

        if ar.hvac_mode_method == "preset":
            preset1 = ar.hvac_mode_map.get(mode_str)
            if preset1 is not None:
                await self._coordinator.cmd_select_preset(ctl_area, int(preset1))

        elif ar.hvac_mode_method == "channel":
            level = ar.hvac_mode_map.get(mode_str)
            if level is not None:
                await self._coordinator.cmd_set_level(ctl_area, ar.hvac_mode_ch0, int(level))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        ar = self._coordinator.areas.get(self._area)
        if ar is None:
            return
        ctl_area = ar.hvac_fan_area or self._area

        if ar.hvac_fan_method == "preset":
            preset1 = ar.hvac_fan_map.get(fan_mode)
            if preset1 is not None:
                await self._coordinator.cmd_select_preset(ctl_area, int(preset1))

        elif ar.hvac_fan_method == "channel":
            level = ar.hvac_fan_map.get(fan_mode)
            if level is not None:
                await self._coordinator.cmd_set_level(ctl_area, ar.hvac_fan_ch0, int(level))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Send setpoint using opcode 0x48 (Q2 format, °C × 4)."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self._coordinator.cmd_set_setpoint(self._area, float(temp))

    async def async_turn_on(self) -> None:
        """Turn on: pick first non-off mode, or AUTO if nothing configured."""
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.hvac_mode_map:
            for mode_str in ar.hvac_mode_map:
                if mode_str != "off":
                    try:
                        await self.async_set_hvac_mode(HVACMode(mode_str))
                        return
                    except ValueError:
                        pass
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _level_to_mode(pct: int, mapping: dict) -> str | None:
        """Reverse-map a channel level % to a mode/fan string (nearest within tolerance)."""
        best_key  = None
        best_diff = _LEVEL_TOLERANCE + 1
        for key, level in mapping.items():
            diff = abs(pct - int(level))
            if diff < best_diff:
                best_diff = diff
                best_key  = key
        return best_key if best_diff <= _LEVEL_TOLERANCE else None
