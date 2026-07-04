"""Dynalite sensor platform — temperature and illuminance sensors."""

from __future__ import annotations

import math

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .const import DOMAIN, signal_connection, signal_lux
from .coordinator import AreaState, DynaliteCoordinator
from .entity import DynaliteAreaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DynaliteCoordinator = entry.runtime_data

    # ── Temperature sensors (area-based) ─────────────────────────────────────
    known_temp: set[int] = set()

    def _add_sensors() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.has_temp and ar.area not in known_temp:
                known_temp.add(ar.area)
                new_entities.append(DynaliteTempSensor(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    def _remove_sensor(area_num: int) -> None:
        known_temp.discard(area_num)

    _add_sensors()
    coordinator.on_new_sensor_cbs.append(_add_sensors)
    coordinator.on_remove_sensor_cbs.append(_remove_sensor)

    # ── Lux sensors (physical-device-based) ──────────────────────────────────
    known_lux: set[tuple[int, int]] = set()

    def _add_lux_sensors() -> None:
        new_entities = []
        for key, dev in coordinator.devices.items():
            if dev.has_lux and key not in known_lux:
                known_lux.add(key)
                new_entities.append(DynaliteLuxSensor(coordinator, dev.device_code, dev.box_number))
        if new_entities:
            async_add_entities(new_entities)

    def _remove_lux_sensor(device_code: int, box_number: int) -> None:
        known_lux.discard((device_code, box_number))

    _add_lux_sensors()
    coordinator.on_new_lux_cbs.append(_add_lux_sensors)
    coordinator.on_remove_lux_cbs.append(_remove_lux_sensor)


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


# ── Lux (illuminance) sensor — one per physical device with has_lux=True ─────

class DynaliteLuxSensor(SensorEntity):
    """Ambient light level sensor from a Dynalite physical device (opcode 0xB8)."""

    _attr_device_class                = SensorDeviceClass.ILLUMINANCE
    _attr_state_class                 = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement  = LIGHT_LUX
    _attr_name                        = "Illuminance"
    _attr_should_poll                 = False
    _attr_has_entity_name             = True
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: DynaliteCoordinator,
        device_code: int,
        box_number: int,
    ) -> None:
        self._coordinator  = coordinator
        self._device_code  = device_code
        self._box_number   = box_number
        self._key          = (device_code, box_number)

        dev      = coordinator.devices.get(self._key)
        model    = dev.model if dev else f"Device 0x{device_code:02X}"
        dev_name = (dev.name if dev and dev.name else None) or f"{model} (Box {box_number})"

        self._attr_unique_id   = f"{coordinator.host}_lux_{device_code}_{box_number}"
        self._attr_device_info = DeviceInfo(
            identifiers  = {(DOMAIN, f"{coordinator.host}_{device_code}_{box_number}")},
            name         = dev_name,
            manufacturer = "Philips Dynalite",
            model        = model,
            via_device   = (DOMAIN, f"{coordinator.host}_gateway"),
        )

    @property
    def available(self) -> bool:
        return self._coordinator.connected

    @property
    def native_value(self) -> float | None:
        dev = self._coordinator.devices.get(self._key)
        return dev.lux_value if dev is not None else None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_lux(self._coordinator.host, self._device_code, self._box_number),
                self._on_lux_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_connection(self._coordinator.host),
                self._on_connection,
            )
        )

    @callback
    def _on_lux_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _on_connection(self, connected: bool) -> None:  # noqa: FBT001
        self.async_write_ha_state()

