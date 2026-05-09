"""Philips Dynalite PDEG integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_HOST, CONF_PORT, DOMAIN, LOGGER, PLATFORMS
from .coordinator import DynaliteCoordinator
from .services import async_setup_services
from .storage import DynaliteStorage
from .websocket import async_setup_websocket

type DynaliteConfigEntry = ConfigEntry[DynaliteCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: DynaliteConfigEntry
) -> bool:
    """Set up Dynalite PDEG from a config entry."""
    coordinator = DynaliteCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
    )

    # ── Attach storage and restore persisted entities BEFORE platform setup ───
    storage = DynaliteStorage(hass, entry.entry_id)
    coordinator._storage = storage  # noqa: SLF001
    await storage.async_load(coordinator)   # populates coordinator.areas + channels
    # ── Now platforms can register entities for already-known areas/channels ──

    if not await coordinator.async_setup():
        raise ConfigEntryNotReady("Unable to start Dynalite coordinator")

    entry.runtime_data = coordinator

    # Register the gateway as a hub device in the device registry
    from homeassistant.helpers import device_registry as dr
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "gateway")},
        name=entry.data.get("name", "Dynalite Gateway"),
        manufacturer="Philips Dynalite",
        model="PDEG",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)
    async_setup_websocket(hass)

    # ── Register config panel (full-page table UI) ────────────────────────────
    panel_url = f"dynalite-pdeg-{entry.entry_id[:8]}"
    try:
        import os  # noqa: PLC0415
        panel_dir = os.path.join(os.path.dirname(__file__), "panel")
        static_url = "/dynalite_pdeg_static"

        # Serve static files once globally (HA 2024.x+ API)
        if not hass.data.get("dynalite_pdeg_static_registered"):
            from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415
            await hass.http.async_register_static_paths([
                StaticPathConfig(static_url, panel_dir, False),
            ])
            hass.data["dynalite_pdeg_static_registered"] = True
            LOGGER.info("[Panel] static path registered: %s → %s", static_url, panel_dir)

        # Ensure panel_custom component is set up before using it
        from homeassistant.setup import async_setup_component  # noqa: PLC0415
        await async_setup_component(hass, "panel_custom", {})
        from homeassistant.components.panel_custom import async_register_panel  # noqa: PLC0415

        await async_register_panel(
            hass,
            webcomponent_name="dynalite-config-panel",
            sidebar_title=entry.data.get("name", "Dynalite"),
            sidebar_icon="mdi:lightbulb-group",
            frontend_url_path=panel_url,
            js_url=f"{static_url}/dynalite-config-panel.js?v=13",
            config={"entry_id": entry.entry_id, "name": entry.data.get("name", "Dynalite PDEG")},
            require_admin=True,
        )
        hass.data.setdefault("dynalite_pdeg_panels", set()).add(panel_url)
        LOGGER.info("[Panel] registered at /%s  (entry=%s)", panel_url, entry.entry_id)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("[Panel] could not register panel: %s  (%s)", exc, type(exc).__name__)

    LOGGER.info("Dynalite PDEG integration started (%s:%d)", entry.data[CONF_HOST], entry.data[CONF_PORT])
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DynaliteConfigEntry
) -> bool:
    """Unload a config entry."""
    coordinator: DynaliteCoordinator = entry.runtime_data
    await coordinator.async_unload()

    # Remove sidebar panel
    panel_url = f"dynalite-pdeg-{entry.entry_id[:8]}"
    try:
        from homeassistant.components.frontend import async_remove_panel  # noqa: PLC0415
        async_remove_panel(hass, panel_url)
        hass.data.get("dynalite_pdeg_panels", set()).discard(panel_url)
    except Exception:  # noqa: BLE001
        pass

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: DynaliteConfigEntry
) -> None:
    """Wipe storage when the user deletes the integration."""
    storage = DynaliteStorage(hass, entry.entry_id)
    await storage.async_remove()
    LOGGER.info("Dynalite PDEG storage wiped for entry %s", entry.entry_id)
