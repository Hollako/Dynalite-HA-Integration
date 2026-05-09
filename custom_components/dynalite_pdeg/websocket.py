"""HA websocket commands for the Dynalite PDEG config panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from .coordinator import DynaliteCoordinator


def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register all custom websocket commands."""
    websocket_api.async_register_command(hass, ws_list_areas)
    websocket_api.async_register_command(hass, ws_update_area)
    websocket_api.async_register_command(hass, ws_add_area)
    websocket_api.async_register_command(hass, ws_delete_area)
    websocket_api.async_register_command(hass, ws_add_channel)
    websocket_api.async_register_command(hass, ws_update_channel)
    websocket_api.async_register_command(hass, ws_delete_channel)
    websocket_api.async_register_command(hass, ws_run_scan)
    websocket_api.async_register_command(hass, ws_set_pir)
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_update_device)
    websocket_api.async_register_command(hass, ws_add_device)
    websocket_api.async_register_command(hass, ws_delete_device)
    websocket_api.async_register_command(hass, ws_request_signon)
    websocket_api.async_register_command(hass, ws_request_signon_device)
    websocket_api.async_register_command(hass, ws_get_settings)
    websocket_api.async_register_command(hass, ws_set_settings)
    websocket_api.async_register_command(hass, ws_parse_xml)
    websocket_api.async_register_command(hass, ws_import_logical)
    websocket_api.async_register_command(hass, ws_import_devices)
    LOGGER.debug("[WS] websocket commands registered")


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> DynaliteCoordinator | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry and hasattr(entry, "runtime_data") and entry.runtime_data:
        return entry.runtime_data
    return None


def _remove_channel_entity(
    hass: HomeAssistant,
    host: str,
    area: int,
    ch0: int,
    channel_type: str,
    cover_partner_ch0: int | None = None,
) -> None:
    """Remove a channel's entity from the HA entity registry (before type change)."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)

    if channel_type in ("dimmer",):
        platform = "light"
        uid = f"{host}_a{area}_c{ch0}_light"
    elif channel_type == "onoff":
        platform = "light"
        uid = f"{host}_a{area}_c{ch0}_light_onoff"
    elif channel_type == "switch":
        platform = "switch"
        uid = f"{host}_a{area}_c{ch0}_switch"
    elif channel_type == "cover" and cover_partner_ch0 is not None:
        platform = "cover"
        uid = f"{host}_a{area}_cover_{ch0}_{cover_partner_ch0}"
    else:
        return

    entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, uid)
    if entity_id:
        ent_reg.async_remove(entity_id)
        LOGGER.info("[WS] removed old entity %s before type change", entity_id)


# ── list_areas ────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/list_areas",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_list_areas(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found or not loaded")
        return

    areas = []
    for ar in sorted(coord.areas.values(), key=lambda a: a.area):
        areas.append({
            "area":         ar.area,
            "name":         ar.name,
            "fade_tenths":  ar.fade_tenths,
            "preset_count": ar.preset_count,
            "area_type":    ar.area_type,
            "has_pir":      ar.has_pir,
            "channels": sorted(
                [
                    {
                        "ch0":               ch.ch0,
                        "name":              ch.name,
                        "channel_type":      ch.channel_type,
                        "cover_partner_ch0": ch.cover_partner_ch0,
                    }
                    for ch in ar.channels.values()
                ],
                key=lambda c: c["ch0"],
            ),
        })
    connection.send_result(msg["id"], {"areas": areas, "connected": coord.connected})


# ── update_area ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/update_area",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
    vol.Optional("name",         default=""): str,
    vol.Optional("fade_tenths",  default=20): vol.All(int, vol.Range(min=0, max=6000)),
    vol.Optional("preset_count", default=4):  vol.All(int, vol.Range(min=1, max=255)),
    vol.Optional("area_type",    default="light"): str,
})
@websocket_api.async_response
async def ws_update_area(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    ar = coord._touch_area(msg["area"])  # noqa: SLF001
    ar.name         = msg["name"]
    ar.fade_tenths  = msg["fade_tenths"]
    ar.preset_count = msg["preset_count"]
    ar.area_type    = msg["area_type"]
    coord.schedule_save()
    LOGGER.info("[WS] updated area %d", msg["area"])
    connection.send_result(msg["id"], {"ok": True})


# ── add_area ──────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/add_area",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
})
@websocket_api.async_response
async def ws_add_area(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    coord._touch_area(msg["area"])  # noqa: SLF001
    LOGGER.info("[WS] added area %d", msg["area"])
    connection.send_result(msg["id"], {"ok": True})


# ── delete_area ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/delete_area",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
})
@websocket_api.async_response
async def ws_delete_area(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    area_num = msg["area"]
    if area_num in coord.areas:
        del coord.areas[area_num]
        coord.schedule_save()
        LOGGER.info("[WS] deleted area %d", area_num)
    connection.send_result(msg["id"], {"ok": True})


# ── add_channel ───────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):         "dynalite_pdeg/add_channel",
    vol.Required("entry_id"):     str,
    vol.Required("area"):         vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("ch0"):          vol.All(int, vol.Range(min=0, max=63)),
    vol.Optional("channel_type",       default="dimmer"): str,
    vol.Optional("name",               default=""):        str,
    vol.Optional("cover_partner_ch0"):  vol.All(int, vol.Range(min=0, max=63)),
})
@websocket_api.async_response
async def ws_add_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    ar          = coord._touch_area(msg["area"])       # noqa: SLF001
    ch          = coord._touch_channel(ar, msg["ch0"])  # noqa: SLF001
    old_type    = ch.channel_type
    old_partner = ch.cover_partner_ch0
    new_type    = msg["channel_type"]
    type_changed = new_type != old_type

    ch.channel_type = new_type
    ch.name         = msg["name"]
    if "cover_partner_ch0" in msg:
        ch.cover_partner_ch0 = msg["cover_partner_ch0"]
    coord.schedule_save()
    LOGGER.info("[WS] added channel A%d Ch%d type=%s", msg["area"], msg["ch0"], new_type)

    if type_changed:
        _remove_channel_entity(hass, coord.host, msg["area"], msg["ch0"], old_type, old_partner)
        hass.async_create_task(hass.config_entries.async_reload(msg["entry_id"]))
        connection.send_result(msg["id"], {"ok": True, "reloading": True})
    else:
        connection.send_result(msg["id"], {"ok": True, "reloading": False})


# ── update_channel ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):         "dynalite_pdeg/update_channel",
    vol.Required("entry_id"):     str,
    vol.Required("area"):         vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("ch0"):          vol.All(int, vol.Range(min=0, max=63)),
    vol.Optional("channel_type"):      str,
    vol.Optional("name"):              str,
    vol.Optional("cover_partner_ch0"): vol.All(int, vol.Range(min=0, max=63)),
})
@websocket_api.async_response
async def ws_update_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    ar = coord.areas.get(msg["area"])
    if not ar:
        connection.send_error(msg["id"], "not_found", f"Area {msg['area']} not found")
        return
    ch = ar.channels.get(msg["ch0"])
    if not ch:
        connection.send_error(msg["id"], "not_found", f"Channel {msg['ch0']} not found")
        return

    old_type       = ch.channel_type
    old_partner    = ch.cover_partner_ch0
    type_changed   = False

    if "channel_type" in msg and msg["channel_type"] != ch.channel_type:
        ch.channel_type = msg["channel_type"]
        type_changed = True
    elif "channel_type" in msg:
        ch.channel_type = msg["channel_type"]
    if "name" in msg:
        ch.name = msg["name"]
    if "cover_partner_ch0" in msg:
        ch.cover_partner_ch0 = msg["cover_partner_ch0"]
    coord.schedule_save()
    LOGGER.info("[WS] updated channel A%d Ch%d (type_changed=%s)", msg["area"], msg["ch0"], type_changed)

    if type_changed:
        # Remove old entity from registry before reload so it doesn't linger
        _remove_channel_entity(hass, coord.host, msg["area"], msg["ch0"], old_type, old_partner)
        hass.async_create_task(hass.config_entries.async_reload(msg["entry_id"]))
        connection.send_result(msg["id"], {"ok": True, "reloading": True})
    else:
        connection.send_result(msg["id"], {"ok": True, "reloading": False})


# ── delete_channel ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/delete_channel",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("ch0"):      vol.All(int, vol.Range(min=0, max=63)),
})
@websocket_api.async_response
async def ws_delete_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    ar = coord.areas.get(msg["area"])
    if ar and msg["ch0"] in ar.channels:
        del ar.channels[msg["ch0"]]
        coord.schedule_save()
        LOGGER.info("[WS] deleted channel A%d Ch%d", msg["area"], msg["ch0"])
    connection.send_result(msg["id"], {"ok": True})


# ── run_scan ──────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/run_scan",
    vol.Required("entry_id"): str,
    vol.Optional("area_min",      default=2):  vol.All(int, vol.Range(min=1, max=255)),
    vol.Optional("area_max",      default=20): vol.All(int, vol.Range(min=1, max=255)),
    vol.Optional("channel_count", default=8):  vol.All(int, vol.Range(min=1, max=64)),
    vol.Optional("delay_ms",      default=50): vol.All(int, vol.Range(min=10, max=500)),
})
@websocket_api.async_response
async def ws_run_scan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    import asyncio  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    asyncio.ensure_future(
        coord.async_scan(
            area_min=msg["area_min"],
            area_max=msg["area_max"],
            channel_count=msg["channel_count"],
            delay_ms=msg["delay_ms"],
        )
    )
    LOGGER.info("[WS] scan triggered")
    connection.send_result(msg["id"], {"ok": True})


# ── set_pir ───────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/set_pir",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("has_pir"):  bool,
})
@websocket_api.async_response
async def ws_set_pir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Enable or disable a PIR motion sensor on a logical area.

    Enabling  → sets has_pir=True, fires on_new_pir_cbs to create the entity.
    Disabling → sets has_pir=False, removes the entity from the registry,
                fires on_remove_pir_cbs so the area can be re-enabled later.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    area_num = msg["area"]
    ar = coord.areas.get(area_num)
    if not ar:
        connection.send_error(msg["id"], "not_found", f"Area {area_num} not found")
        return

    ar.has_pir = msg["has_pir"]
    coord.schedule_save()

    if msg["has_pir"]:
        # Fire callbacks → binary_sensor platform creates the motion entity
        for cb in coord.on_new_pir_cbs:
            cb()
        LOGGER.info("[WS] PIR enabled for area %d", area_num)
    else:
        # Remove the motion sensor entity from HA
        ent_reg   = er.async_get(hass)
        uid       = f"{coord.host}_a{area_num}_motion"
        entity_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, uid)
        if entity_id:
            ent_reg.async_remove(entity_id)
            LOGGER.info("[WS] removed motion entity %s", entity_id)
        # Update known_pir closure so PIR can be re-enabled without a restart
        for cb in coord.on_remove_pir_cbs:
            cb(area_num)
        LOGGER.info("[WS] PIR disabled for area %d", area_num)

    connection.send_result(msg["id"], {"ok": True, "has_pir": ar.has_pir})


# ── list_devices ──────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/list_devices",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_list_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return all discovered physical devices with online/offline state."""
    import time as _time  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found or not loaded")
        return

    now     = _time.monotonic()
    devices = []
    for key, dev in sorted(coord.devices.items(), key=lambda kv: (kv[1].box_number, kv[1].device_code)):
        last_seen = coord._device_last_seen.get(key)  # noqa: SLF001
        online    = coord.device_online.get(key, False)
        age_s     = round(now - last_seen) if last_seen else None
        devices.append({
            "device_code": dev.device_code,
            "box_number":  dev.box_number,
            "model":       dev.model,
            "name":        dev.name,
            "online":      online,
            "last_seen_s": age_s,
        })

    connection.send_result(msg["id"], {
        "devices":   devices,
        "connected": coord.connected,
    })


# ── update_device ─────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/update_device",
    vol.Required("entry_id"):    str,
    vol.Required("device_code"): int,
    vol.Required("box_number"):  int,
    vol.Optional("name", default=""): str,
})
@websocket_api.async_response
async def ws_update_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Rename a physical device (persists name + updates entity registry)."""
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    key = (msg["device_code"], msg["box_number"])
    dev = coord.devices.get(key)
    if not dev:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return

    dev.name = msg["name"]
    coord.schedule_save()

    new_name   = msg["name"].strip() if msg["name"] else ""
    device_uid = f"{coord.host}_{msg['device_code']}_{msg['box_number']}"
    model      = dev.model or f"Device 0x{msg['device_code']:02X}"
    display    = new_name or f"{model} (Box {msg['box_number']})"

    # Update the HA device registry so the device card name refreshes immediately
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
    dev_reg   = dr.async_get(hass)
    ha_device = dev_reg.async_get_device(identifiers={(DOMAIN, device_uid)})
    if ha_device:
        dev_reg.async_update_device(ha_device.id, name=display)

    # Update the HA entity registry (the connectivity sensor name resets to device default)
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    ent_reg   = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{coord.host}_device_{msg['device_code']}_{msg['box_number']}")
    if entity_id:
        ent_reg.async_update_entity(entity_id, name=None)  # let device name drive it

    # Dispatch so the entity's `name` property is re-evaluated immediately
    from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
    from .const import signal_device  # noqa: PLC0415
    async_dispatcher_send(
        hass, signal_device(msg["device_code"], msg["box_number"]), coord.device_online.get((msg["device_code"], msg["box_number"]), False)
    )

    LOGGER.info("[WS] renamed device box %d → '%s'", msg["box_number"], msg["name"])
    connection.send_result(msg["id"], {"ok": True})


# ── add_device ────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/add_device",
    vol.Required("entry_id"):    str,
    vol.Required("device_code"): vol.All(int, vol.Range(min=0, max=255)),
    vol.Required("box_number"):  vol.All(int, vol.Range(min=0, max=255)),
    vol.Optional("name", default=""): str,
})
@websocket_api.async_response
async def ws_add_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Manually add a physical device (box) entry."""
    from .coordinator import PhysicalDevice  # noqa: PLC0415
    from .const import DEVICE_NAMES          # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    key = (msg["device_code"], msg["box_number"])
    if key in coord.devices:
        connection.send_error(msg["id"], "already_exists",
                              f"Box {msg['box_number']} code 0x{msg['device_code']:02X} already exists")
        return

    model = DEVICE_NAMES.get(msg["device_code"], f"Device 0x{msg['device_code']:02X}")
    coord.devices[key] = PhysicalDevice(
        device_code=msg["device_code"],
        box_number=msg["box_number"],
        model=model,
        name=msg["name"],
    )
    coord.schedule_save()

    # Notify binary_sensor platform to create the new entity
    for cb in coord.on_new_device_cbs:
        cb()

    LOGGER.info("[WS] manually added device 0x%02X box %d", msg["device_code"], msg["box_number"])
    connection.send_result(msg["id"], {"ok": True})


# ── delete_device ─────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/delete_device",
    vol.Required("entry_id"):    str,
    vol.Required("device_code"): int,
    vol.Required("box_number"):  int,
})
@websocket_api.async_response
async def ws_delete_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Remove a physical device entry and its binary sensor entity."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    key = (msg["device_code"], msg["box_number"])

    # Remove from coordinator state (may already be absent — that's fine)
    coord.devices.pop(key, None)
    coord.device_online.pop(key, None)
    coord._device_last_seen.pop(key, None)  # noqa: SLF001
    coord.schedule_save()

    # Remove the binary_sensor entity from HA entity registry
    ent_reg   = er.async_get(hass)
    uid       = f"{coord.host}_device_{msg['device_code']}_{msg['box_number']}"
    entity_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, uid)
    if entity_id:
        ent_reg.async_remove(entity_id)
        LOGGER.info("[WS] removed entity %s", entity_id)

    LOGGER.info("[WS] deleted device 0x%02X box %d", msg["device_code"], msg["box_number"])
    connection.send_result(msg["id"], {"ok": True})


# ── request_signon ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/request_signon",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_request_signon(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Manually trigger a targeted sign-on poll for all known devices."""
    import asyncio as _asyncio  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return
    if not coord.client.connected:
        connection.send_error(msg["id"], "not_connected", "PDEG not connected")
        return
    if not coord.devices:
        connection.send_error(msg["id"], "no_devices",
                              "No devices known — add devices first via the Physical tab")
        return
    LOGGER.info("[WS] manual sign-on poll triggered (%d devices)", len(coord.devices))
    _asyncio.ensure_future(coord._poll_all_devices())  # noqa: SLF001
    connection.send_result(msg["id"], {
        "ok":          True,
        "device_count": len(coord.devices),
    })


# ── request_signon_device ─────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/request_signon_device",
    vol.Required("entry_id"):    str,
    vol.Required("device_code"): int,
    vol.Required("box_number"):  int,
})
@websocket_api.async_response
async def ws_request_signon_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Send a targeted sign-on poll to a single device."""
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return
    if not coord.client.connected:
        connection.send_error(msg["id"], "not_connected", "PDEG not connected")
        return

    key = (msg["device_code"], msg["box_number"])
    if key not in coord.devices:
        connection.send_error(msg["id"], "not_found",
                              f"Device 0x{msg['device_code']:02X} box {msg['box_number']} not found")
        return

    await coord.client.request_device_signon(msg["device_code"], msg["box_number"])
    LOGGER.info("[WS] single sign-on sent → dc=0x%02X box=%d", msg["device_code"], msg["box_number"])
    connection.send_result(msg["id"], {"ok": True})


# ── get_settings ──────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/get_settings",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_get_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return integration-level settings (e.g. signon_interval)."""
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return
    connection.send_result(msg["id"], {
        "signon_interval": coord.signon_interval,
    })


# ── set_settings ──────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/set_settings",
    vol.Required("entry_id"): str,
    vol.Optional("signon_interval"): vol.All(int, vol.Range(min=60, max=86400)),
})
@websocket_api.async_response
async def ws_set_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Update integration-level settings at runtime (persisted to storage)."""
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return
    if "signon_interval" in msg:
        coord.signon_interval = msg["signon_interval"]
        LOGGER.info("[WS] signon_interval → %ds", coord.signon_interval)
    coord.schedule_save()
    connection.send_result(msg["id"], {
        "ok":              True,
        "signon_interval": coord.signon_interval,
    })


# ── parse_xml ─────────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/parse_xml",
    vol.Required("entry_id"):    str,
    vol.Required("xml_content"): str,
})
@websocket_api.async_response
async def ws_parse_xml(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Auto-detect and parse a System Builder XML export.

    Returns either:
      {"xml_type": "logical", "areas":   [...]} — parse_logical_xml output
      {"xml_type": "devices", "devices": [...]} — parse_devices_xml output
    """
    from .xml_parser import detect_xml_type, parse_logical_xml, parse_devices_xml  # noqa: PLC0415

    content = msg["xml_content"]
    xml_type = detect_xml_type(content)
    if xml_type is None:
        connection.send_error(msg["id"], "invalid_xml",
                              "Could not detect XML type — must be a LogicalExport or DeviceExport file")
        return

    try:
        if xml_type == "logical":
            areas = parse_logical_xml(content)
            connection.send_result(msg["id"], {"xml_type": "logical", "areas": areas})
        else:  # devices
            devices = parse_devices_xml(content)
            connection.send_result(msg["id"], {"xml_type": "devices", "devices": devices})
    except ValueError as exc:
        connection.send_error(msg["id"], "parse_error", str(exc))


# ── import_logical ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/import_logical",
    vol.Required("entry_id"):    str,
    vol.Required("areas"):       list,
    vol.Optional("overwrite",   default=False): bool,
})
@websocket_api.async_response
async def ws_import_logical(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Import selected areas (and their channels) from a parsed Logical XML.

    Each area dict must have the shape returned by parse_logical_xml:
      {"area": int, "name": str, "area_type": str, "preset_count": int,
       "fade_tenths": int, "channels": [{"ch0": int, "name": str, "channel_type": str}]}

    If overwrite=False, areas that already exist in the coordinator are skipped.
    """
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    imported = 0
    skipped  = 0
    type_changed = False

    for area_dict in msg["areas"]:
        try:
            area_num = int(area_dict["area"])
        except (KeyError, ValueError, TypeError):
            continue

        already_exists = area_num in coord.areas
        if already_exists and not msg["overwrite"]:
            skipped += 1
            continue

        ar           = coord._touch_area(area_num)  # noqa: SLF001
        ar.name         = str(area_dict.get("name", "") or "").strip()
        ar.area_type    = str(area_dict.get("area_type", "light"))
        ar.preset_count = max(1, int(area_dict.get("preset_count") or 4))
        ar.fade_tenths  = max(0, int(area_dict.get("fade_tenths") or 20))

        for ch_dict in (area_dict.get("channels") or []):
            try:
                ch0 = int(ch_dict["ch0"])
            except (KeyError, ValueError, TypeError):
                continue
            ch = coord._touch_channel(ar, ch0)  # noqa: SLF001
            old_type = ch.channel_type
            ch.name         = str(ch_dict.get("name", "") or "").strip()
            ch.channel_type = str(ch_dict.get("channel_type", "dimmer"))
            if ch.channel_type != old_type:
                type_changed = True

        imported += 1

    coord.schedule_save()
    LOGGER.info("[WS] import_logical: imported=%d skipped=%d overwrite=%s", imported, skipped, msg["overwrite"])

    result: dict = {"ok": True, "imported": imported, "skipped": skipped}
    if type_changed:
        # Reload so entity types are updated
        hass.async_create_task(hass.config_entries.async_reload(msg["entry_id"]))
        result["reloading"] = True

    connection.send_result(msg["id"], result)


# ── import_devices ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/import_devices",
    vol.Required("entry_id"):    str,
    vol.Required("devices"):     list,
    vol.Optional("overwrite",   default=False): bool,
})
@websocket_api.async_response
async def ws_import_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Import selected physical devices from a parsed Devices XML.

    Each device dict must have the shape returned by parse_devices_xml:
      {"device_code": int, "box_number": int, "name": str, "model": str, "is_sensor": bool}

    If overwrite=False, devices that already exist are skipped.
    """
    from .coordinator import PhysicalDevice  # noqa: PLC0415
    from .const import DEVICE_NAMES          # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    imported    = 0
    skipped     = 0
    new_devices = False

    for dev_dict in msg["devices"]:
        try:
            device_code = int(dev_dict["device_code"])
            box_number  = int(dev_dict["box_number"])
        except (KeyError, ValueError, TypeError):
            continue

        key = (device_code, box_number)
        already_exists = key in coord.devices

        if already_exists:
            if not msg["overwrite"]:
                skipped += 1
                continue
            # Update name/model of existing entry
            dev = coord.devices[key]
            dev.name  = str(dev_dict.get("name",  "") or "").strip()
            dev.model = str(dev_dict.get("model", "") or "") or DEVICE_NAMES.get(device_code, f"Device 0x{device_code:02X}")
        else:
            model = str(dev_dict.get("model", "") or "") or DEVICE_NAMES.get(device_code, f"Device 0x{device_code:02X}")
            coord.devices[key] = PhysicalDevice(
                device_code=device_code,
                box_number=box_number,
                model=model,
                name=str(dev_dict.get("name", "") or "").strip(),
            )
            new_devices = True

        imported += 1

    coord.schedule_save()
    LOGGER.info("[WS] import_devices: imported=%d skipped=%d overwrite=%s", imported, skipped, msg["overwrite"])

    if new_devices:
        for cb in coord.on_new_device_cbs:
            cb()

    connection.send_result(msg["id"], {"ok": True, "imported": imported, "skipped": skipped})
