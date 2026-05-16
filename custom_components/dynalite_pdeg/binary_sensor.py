"""Dynalite binary sensor platform — PIR motion sensors + physical device connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .const import DOMAIN, signal_connection, signal_device, signal_device_motion
from .coordinator import AreaState, DynaliteCoordinator
from .entity import DynaliteAreaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DynaliteCoordinator = entry.runtime_data

    # ── PIR / motion sensors (one per area that has a PIR) ────────────────────
    known_pir: set[int] = set()

    def _add_pir_sensors() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.has_pir and ar.area not in known_pir:
                known_pir.add(ar.area)
                new_entities.append(DynaliteMotionSensor(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_pir_sensors()
    coordinator.on_new_pir_cbs.append(_add_pir_sensors)

    def _remove_pir_sensor(area: int) -> None:
        """Allow the area to be re-added later if PIR is re-enabled."""
        known_pir.discard(area)

    coordinator.on_remove_pir_cbs.append(_remove_pir_sensor)

    # ── Physical device connectivity (one per discovered box/module) ──────────
    known_devices: set[tuple[int, int]] = set()

    def _add_device_sensors() -> None:
        new_entities = []
        for key, dev in coordinator.devices.items():
            if key not in known_devices:
                known_devices.add(key)
                new_entities.append(
                    DynaliteDeviceConnectivity(
                        coordinator, dev.device_code, dev.box_number
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    def _remove_device_sensor(device_code: int, box_number: int) -> None:
        """Allow the device to be re-added later if rediscovered."""
        known_devices.discard((device_code, box_number))

    _add_device_sensors()
    coordinator.on_new_device_cbs.append(_add_device_sensors)
    coordinator.on_remove_device_cbs.append(_remove_device_sensor)

    # ── Physical device motion sensors (D5 Sensor etc.) ──────────────────────
    known_device_motion: set[tuple[int, int]] = set()

    def _add_device_motion_sensors() -> None:
        new_entities = []
        for key, dev in coordinator.devices.items():
            if dev.has_motion and key not in known_device_motion:
                known_device_motion.add(key)
                new_entities.append(
                    DynaliteDeviceMotionSensor(
                        coordinator, dev.device_code, dev.box_number
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    _add_device_motion_sensors()
    coordinator.on_new_device_motion_cbs.append(_add_device_motion_sensors)


# ── PIR motion sensor ─────────────────────────────────────────────────────────

class DynaliteMotionSensor(DynaliteAreaEntity, BinarySensorEntity):
    """Motion sensor mapped to a Dynalite PIR area (opcode 0x31)."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_name = "Motion"

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_motion"

    @property
    def is_on(self) -> bool:
        ar = self._coordinator.areas.get(self._area)
        return ar.pir_occupied if ar else False

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self.async_write_ha_state()


# ── Physical device connectivity sensor ───────────────────────────────────────

class DynaliteDeviceConnectivity(BinarySensorEntity):
    """Online/offline connectivity sensor for a physical Dynalite device (box/module).

    Each physical box gets its own HA device entry (linked to the gateway via
    via_device), so users can assign boxes to HA rooms/areas and see per-device
    connectivity status directly on the device card.
    """

    _attr_device_class                    = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name                 = True
    _attr_name                            = None
    _attr_should_poll                     = False
    _attr_entity_category                 = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_visible_default = False  # hidden from all entity lists/pickers

    def __init__(
        self,
        coordinator: DynaliteCoordinator,
        device_code: int,
        box_number: int,
    ) -> None:
        self._coordinator = coordinator
        self._device_code = device_code
        self._box_number  = box_number
        self._key         = (device_code, box_number)

        dev         = coordinator.devices.get(self._key)
        self._model = dev.model if dev else f"Device 0x{device_code:02X}"
        dev_name    = (dev.name if dev and dev.name else None) or f"{self._model} (Box {box_number})"

        self._attr_unique_id   = f"{coordinator.host}_device_{device_code}_{box_number}"
        # Each physical box is its own HA device, linked to the gateway hub
        self._attr_device_info = DeviceInfo(
            identifiers  = {(DOMAIN, f"{coordinator.host}_{device_code}_{box_number}")},
            name         = dev_name,
            manufacturer = "Philips Dynalite",
            model        = self._model,
            via_device   = (DOMAIN, "gateway"),
        )

    @property
    def available(self) -> bool:
        """False when gateway is offline OR device has not responded to sign-on polls."""
        return (
            self._coordinator.connected
            and self._coordinator.device_online.get(self._key, False)
        )

    @property
    def is_on(self) -> bool:
        """Always True — the sensor only exists when the device is reachable (available=True)."""
        return True

    @callback
    def _on_device_update(self, online: bool) -> None:  # noqa: FBT001
        self.async_write_ha_state()

    @callback
    def _on_connection(self, connected: bool) -> None:  # noqa: FBT001
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_device(self._device_code, self._box_number),
                self._on_device_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_connection(),
                self._on_connection,
            )
        )


# ── Physical device motion sensor ─────────────────────────────────────────────

class DynaliteDeviceMotionSensor(BinarySensorEntity):
    """Motion sensor for a physical Dynalite device (e.g. D5 Sensor).

    Created the first time the device reports a motion frame (opcode 0xB8,
    sub-type 0x0D).  State is updated in real time via dispatcher signal.
    """

    _attr_device_class   = BinarySensorDeviceClass.MOTION
    _attr_has_entity_name = True
    _attr_name           = "Motion"
    _attr_should_poll    = False

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

        self._attr_unique_id   = f"{coordinator.host}_device_{device_code}_{box_number}_motion"
        self._attr_device_info = DeviceInfo(
            identifiers  = {(DOMAIN, f"{coordinator.host}_{device_code}_{box_number}")},
            name         = dev_name,
            manufacturer = "Philips Dynalite",
            model        = model,
            via_device   = (DOMAIN, "gateway"),
        )

    @property
    def available(self) -> bool:
        """False when the gateway is offline."""
        return self._coordinator.connected

    @property
    def is_on(self) -> bool:
        dev = self._coordinator.devices.get(self._key)
        return bool(dev.motion_detected) if dev and dev.motion_detected is not None else False

    @callback
    def _on_motion_update(self, detected: bool) -> None:  # noqa: FBT001
        self.async_write_ha_state()

    @callback
    def _on_connection(self, connected: bool) -> None:  # noqa: FBT001
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_device_motion(self._device_code, self._box_number),
                self._on_motion_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_connection(),
                self._on_connection,
            )
        )
