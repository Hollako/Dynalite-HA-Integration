"""Dynalite sensor platform — temperature and setpoint sensors."""

from __future__ import annotations

import math

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
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
    coordinator: DynaliteCoordinator = entry.runtime_data
    known_temp:  set[int] = set()
    known_setpt: set[int] = set()

    def _add_sensors() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.has_temp and ar.area not in known_temp:
                known_temp.add(ar.area)
                new_entities.append(DynaliteTempSensor(coordinator, ar.area))
            if ar.has_setpt and ar.area not in known_setpt:
                known_setpt.add(ar.area)
                new_entities.append(DynaliteSetpointSensor(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_sensors()
    coordinator.on_new_sensor = _add_sensors  # type: ignore[attr-defined]


class DynaliteTempSensor(DynaliteAreaEntity, SensorEntity):
    """Actual temperature sensor for a Dynalite area."""

    _attr_device_class   = SensorDeviceClass.TEMPERATURE
    _attr_state_class    = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Temperature"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_temp"

    @property
    def native_value(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.has_temp and not math.isnan(ar.temp_c):
            return round(ar.temp_c, 1)
        return None

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()


class DynaliteSetpointSensor(DynaliteAreaEntity, SensorEntity):
    """Setpoint temperature sensor for a Dynalite area."""

    _attr_device_class   = SensorDeviceClass.TEMPERATURE
    _attr_state_class    = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Setpoint"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_setpt"

    @property
    def native_value(self) -> float | None:
        ar = self._coordinator.areas.get(self._area)
        if ar and ar.has_setpt and not math.isnan(ar.setpt_c):
            return round(ar.setpt_c, 1)
        return None

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()
