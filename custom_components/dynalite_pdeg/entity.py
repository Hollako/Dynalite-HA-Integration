"""Base entity for Dynalite PDEG integration."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, signal_channel_remove, signal_connection
from .coordinator import DynaliteCoordinator


class DynaliteEntity(Entity):
    """Base class for all Dynalite entities.

    Handles:
    - HA device grouping (one device per area)
    - Availability tracking via the connection signal
    - Dispatcher subscription lifecycle
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        self._coordinator = coordinator
        self._area = area

    # ── Device info — one HA device per Dynalite area ─────────────────────────

    @property
    def device_info(self) -> DeviceInfo:
        host = self._coordinator.host
        ar = self._coordinator.areas.get(self._area)
        area_name = ar.display_name() if ar else f"Area {self._area}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{host}_area_{self._area}")},
            name=area_name,
            manufacturer="Philips Dynalite",
            model=f"Area {self._area}",
            via_device=(DOMAIN, f"{host}_gateway"),
        )

    # ── Availability ──────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._coordinator.connected

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection and state signals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_connection(self._coordinator.host),
                self._on_connection,
            )
        )
        await self._async_subscribe()

    async def _async_subscribe(self) -> None:
        """Override in subclasses to subscribe to area/channel signals."""

    @callback
    def _on_connection(self, connected: bool) -> None:
        self.async_write_ha_state()


class DynaliteAreaEntity(DynaliteEntity):
    """Entity tied to an area (subscribes to area-level signals)."""

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)

    async def _async_subscribe(self) -> None:
        from .const import signal_area
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_area(self._coordinator.host, self._area),
                self._on_area_update,
            )
        )

    @callback
    def _on_area_update(self, ar) -> None:
        """Override in subclasses to handle area state updates."""
        self.async_write_ha_state()


class DynaliteChannelEntity(DynaliteEntity):
    """Entity tied to a specific channel within an area."""

    def __init__(
        self, coordinator: DynaliteCoordinator, area: int, ch0: int
    ) -> None:
        super().__init__(coordinator, area)
        self._ch0 = ch0

    async def _async_subscribe(self) -> None:
        from .const import signal_channel
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_channel(self._coordinator.host, self._area, self._ch0),
                self._on_channel_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_channel_remove(self._coordinator.host, self._area, self._ch0),
                self._on_channel_remove,
            )
        )

    @callback
    def _on_channel_remove(self) -> None:
        self.hass.async_create_task(self.async_remove(force_remove=True))

    @callback
    def _on_channel_update(self, ch) -> None:
        """Override in subclasses to handle channel state updates."""
        self.async_write_ha_state()
