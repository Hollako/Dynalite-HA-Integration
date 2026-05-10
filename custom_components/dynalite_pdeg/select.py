"""Dynalite select platform — preset selector per area."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DynaliteConfigEntry
from .coordinator import AREA_TYPE_LIGHT, AreaState, DynaliteCoordinator
from .entity import DynaliteAreaEntity

# Default Dynalite preset names (1-indexed)
_DEFAULT_PRESET_NAMES = {1: "High", 2: "Medium", 3: "Low", 4: "Off"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DynaliteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: DynaliteCoordinator = entry.runtime_data
    known: set[int] = set()

    def _add_selects() -> None:
        new_entities = []
        for ar in coordinator.areas.values():
            if ar.area_type == AREA_TYPE_LIGHT and ar.area not in known:
                known.add(ar.area)
                new_entities.append(DynalitePresetSelect(coordinator, ar.area))
        if new_entities:
            async_add_entities(new_entities)

    _add_selects()
    coordinator.on_new_area_cbs.append(_add_selects)


def _preset_label(preset1: int, ar: AreaState | None) -> str:
    """Return display name for a 1-based preset.

    Priority: user-defined name (ar.preset_names) → default name → "Preset N".
    """
    if ar and ar.preset_names.get(preset1):
        return ar.preset_names[preset1]
    return _DEFAULT_PRESET_NAMES.get(preset1, f"Preset {preset1}")


class DynalitePresetSelect(DynaliteAreaEntity, SelectEntity):
    """Preset select for a Dynalite area (1 to preset_count presets)."""

    _attr_name = "Preset"
    _attr_icon = "mdi:tune"

    def __init__(self, coordinator: DynaliteCoordinator, area: int) -> None:
        super().__init__(coordinator, area)
        self._attr_unique_id = f"{coordinator.host}_a{area}_preset"
        self._update_options()

    def _update_options(self) -> None:
        ar = self._coordinator.areas.get(self._area)
        count = ar.preset_count if ar else 4
        self._attr_options = [
            _preset_label(i, ar) for i in range(1, count + 1)
        ]

    @property
    def current_option(self) -> str | None:
        ar = self._coordinator.areas.get(self._area)
        if ar is None or ar.preset0 == 0xFF:
            return None
        preset1 = ar.preset0 + 1
        label = _preset_label(preset1, ar)
        return label if label in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        # Find preset1 from label
        ar = self._coordinator.areas.get(self._area)
        count = ar.preset_count if ar else 4
        for i in range(1, count + 1):
            if _preset_label(i, ar) == option:
                # Optimistic update — show selection immediately without waiting for bus echo
                if ar:
                    ar.preset0 = i - 1
                self.async_write_ha_state()
                await self._coordinator.cmd_select_preset(self._area, i)
                return

    @callback
    def _on_area_update(self, ar: AreaState) -> None:
        self._update_options()
        self.async_write_ha_state()
