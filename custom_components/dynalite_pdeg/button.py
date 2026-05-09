"""Dynalite button platform — Save Preset button per area."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .coordinator import AREA_TYPE_LIGHT, DynaliteCoordinator
from .entity import DynaliteAreaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[int] = set()

    def _add_buttons() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.area_type == AREA_TYPE_LIGHT and ar.area not in known:
                known.add(ar.area)
                new_entities.append(DynaliteSavePresetButton(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_buttons()
    coordinator.on_new_area_cbs.append(_add_buttons)


class DynaliteSavePresetButton(DynaliteAreaEntity, ButtonEntity):
    """Saves the current channel levels to the active preset for the area.

    Uses opcode 0x08 (Program Current Preset) — saves whatever the channels
    are currently set to into whichever preset is currently active.
    """

    _attr_name = "Save Preset"
    _attr_icon = "mdi:content-save"

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_save_preset"

    async def async_press(self) -> None:
        """Send Program Current Preset (0x08) to save current levels."""
        await self._coordinator.cmd_program_current_preset(self._area)
