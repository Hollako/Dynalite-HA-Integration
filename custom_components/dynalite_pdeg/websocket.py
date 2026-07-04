"""HA websocket commands for the Dynalite PDEG config panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, signal_channel_remove
from .coordinator import AREA_TYPE_BLIND, AREA_TYPE_HVAC, AREA_TYPE_LIGHT, ChannelState

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
    websocket_api.async_register_command(hass, ws_set_temp_sensor)
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
    websocket_api.async_register_command(hass, ws_set_lux_sensor)
    websocket_api.async_register_command(hass, ws_request_motion_status)
    websocket_api.async_register_command(hass, ws_update_preset_names)
    websocket_api.async_register_command(hass, ws_get_backup)
    websocket_api.async_register_command(hass, ws_restore_backup)
    LOGGER.debug("[WS] websocket commands registered")


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> DynaliteCoordinator | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry and hasattr(entry, "runtime_data") and entry.runtime_data:
        return entry.runtime_data
    return None


def _remove_all_area_entities(
    hass: HomeAssistant,
    host: str,
    area: int,
    ar,  # AreaState — used to know channel list, curtain count, area_type
) -> None:
    """Remove every HA entity that belongs to the given area number.

    Called when the user deletes an area from the panel so nothing lingers
    in the entity registry until the next restart.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    ent_reg = er.async_get(hass)

    # ── Preset selector + Save-preset button (light areas) ───────────────────
    _remove_uid(ent_reg, "select",        DOMAIN, f"{host}_a{area}_preset")
    _remove_uid(ent_reg, "button",        DOMAIN, f"{host}_a{area}_save_preset")

    # ── PIR motion sensor ─────────────────────────────────────────────────────
    _remove_uid(ent_reg, "binary_sensor", DOMAIN, f"{host}_a{area}_motion")

    # ── Temperature / setpoint sensors ───────────────────────────────────────
    _remove_uid(ent_reg, "sensor",        DOMAIN, f"{host}_a{area}_temp")
    _remove_uid(ent_reg, "sensor",        DOMAIN, f"{host}_a{area}_setpt")

    # ── Climate entity ────────────────────────────────────────────────────────
    _remove_uid(ent_reg, "climate",       DOMAIN, f"{host}_a{area}_climate")

    # ── Curtain cover entities (blind areas) ──────────────────────────────────
    for idx in range(len(ar.curtains)):
        _remove_uid(ent_reg, "cover", DOMAIN, f"{host}_a{area}_curtain_{idx}")

    # ── Channel-based entities (light areas) ──────────────────────────────────
    for ch0, ch in ar.channels.items():
        if ch.channel_type == "dimmer":
            _remove_uid(ent_reg, "light",  DOMAIN, f"{host}_a{area}_c{ch0}_light")
        elif ch.channel_type == "onoff":
            _remove_uid(ent_reg, "light",  DOMAIN, f"{host}_a{area}_c{ch0}_light_onoff")
        elif ch.channel_type == "switch":
            _remove_uid(ent_reg, "switch", DOMAIN, f"{host}_a{area}_c{ch0}_switch")
        elif ch.channel_type == "cover" and ch.cover_partner_ch0 is not None:
            _remove_uid(ent_reg, "cover",  DOMAIN,
                        f"{host}_a{area}_cover_{ch0}_{ch.cover_partner_ch0}")

    # ── Area device itself ────────────────────────────────────────────────────
    dev_reg   = dr.async_get(hass)
    ha_device = dev_reg.async_get_device(identifiers={(DOMAIN, f"{host}_area_{area}")})
    if ha_device:
        dev_reg.async_remove_device(ha_device.id)
        LOGGER.info("[WS] removed area device for area %d", area)

    LOGGER.info("[WS] removed all entities for area %d", area)


def _remove_light_only_entities(
    hass: HomeAssistant,
    host: str,
    area: int,
    channels: dict,
) -> None:
    """Remove preset-select, save-preset-button, and all light/switch channel entities.

    Called when an area's type changes away from 'light' so stale entities
    do not linger in the HA entity registry.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)

    # Preset selector
    _remove_uid(ent_reg, "select", DOMAIN, f"{host}_a{area}_preset")
    # Save-preset button
    _remove_uid(ent_reg, "button", DOMAIN, f"{host}_a{area}_save_preset")

    # Light / switch channel entities
    for ch0, ch in channels.items():
        if ch.channel_type == "dimmer":
            _remove_uid(ent_reg, "light", DOMAIN, f"{host}_a{area}_c{ch0}_light")
        elif ch.channel_type == "onoff":
            _remove_uid(ent_reg, "light", DOMAIN, f"{host}_a{area}_c{ch0}_light_onoff")
        elif ch.channel_type == "switch":
            _remove_uid(ent_reg, "switch", DOMAIN, f"{host}_a{area}_c{ch0}_switch")


def _remove_uid(ent_reg, platform: str, domain: str, uid: str) -> None:
    entity_id = ent_reg.async_get_entity_id(platform, domain, uid)
    if entity_id:
        ent_reg.async_remove(entity_id)
        LOGGER.info("[WS] removed entity %s", entity_id)


def _remove_curtain_entities_above(
    hass: HomeAssistant,
    host: str,
    area: int,
    new_count: int,
    old_count: int,
) -> None:
    """Remove cover entities for curtain indices that no longer exist."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    if new_count >= old_count:
        return
    ent_reg = er.async_get(hass)
    for idx in range(new_count, old_count):
        uid       = f"{host}_a{area}_curtain_{idx}"
        entity_id = ent_reg.async_get_entity_id("cover", DOMAIN, uid)
        if entity_id:
            ent_reg.async_remove(entity_id)
            LOGGER.info("[WS] removed orphaned curtain entity %s", entity_id)


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
            "area_type":       ar.area_type,
            "has_pir":         ar.has_pir,
            "has_temp":        ar.has_temp,
            "curtains":        ar.curtains,
            "hvac_mode_area":   ar.hvac_mode_area,
            "hvac_mode_method": ar.hvac_mode_method,
            "hvac_mode_ch0":    ar.hvac_mode_ch0,
            "hvac_mode_map":    ar.hvac_mode_map,
            "hvac_fan_area":    ar.hvac_fan_area,
            "hvac_fan_method":  ar.hvac_fan_method,
            "hvac_fan_ch0":     ar.hvac_fan_ch0,
            "hvac_fan_map":     ar.hvac_fan_map,
            "setpt_step":       ar.setpt_step,
            "preset_names":     {str(k): v for k, v in ar.preset_names.items()},
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
    vol.Optional("area_type",        default="light"): str,
    vol.Optional("curtains",         default=[]):      list,
    vol.Optional("hvac_mode_area",    default=0):       vol.All(int, vol.Range(min=0, max=255)),
    vol.Optional("hvac_mode_method", default=""):      str,
    vol.Optional("hvac_mode_ch0",    default=0):       int,
    vol.Optional("hvac_mode_map",    default={}):      dict,
    vol.Optional("hvac_fan_area",    default=0):       vol.All(int, vol.Range(min=0, max=255)),
    vol.Optional("hvac_fan_method",  default=""):      str,
    vol.Optional("hvac_fan_ch0",     default=0):       int,
    vol.Optional("hvac_fan_map",     default={}):      dict,
    vol.Optional("setpt_step",       default=0.5):     vol.All(vol.Coerce(float), vol.In([0.5, 1.0])),
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

    area_num = msg["area"]
    ar = coord._touch_area(area_num)  # noqa: SLF001
    old_type          = ar.area_type
    old_curtain_count = len(ar.curtains)

    ar.name         = msg["name"]
    ar.fade_tenths  = msg["fade_tenths"]
    ar.preset_count = msg["preset_count"]
    ar.area_type    = msg["area_type"]

    # Normalise each curtain dict to guarantee all required keys exist
    new_curtains: list[dict] = []
    for c in msg.get("curtains", []):
        new_curtains.append({
            "name":         str(c.get("name", "")),
            "open_preset":  int(c.get("open_preset",  1)),
            "stop_preset":  int(c.get("stop_preset",  3)),
            "close_preset": int(c.get("close_preset", 2)),
        })
    ar.curtains = new_curtains

    # HVAC mode / fan config (values are safe dicts/strings from the panel)
    ar.hvac_mode_area   = int(msg.get("hvac_mode_area", 0))
    ar.hvac_mode_method = msg.get("hvac_mode_method", "")
    ar.hvac_mode_ch0    = int(msg.get("hvac_mode_ch0", 0))
    ar.hvac_mode_map    = {str(k): int(v) for k, v in msg.get("hvac_mode_map", {}).items()}
    ar.hvac_fan_area    = int(msg.get("hvac_fan_area", 0))
    ar.hvac_fan_method  = msg.get("hvac_fan_method", "")
    ar.hvac_fan_ch0     = int(msg.get("hvac_fan_ch0", 0))
    ar.hvac_fan_map     = {str(k): int(v) for k, v in msg.get("hvac_fan_map", {}).items()}
    ar.setpt_step       = float(msg.get("setpt_step", 0.5))

    # Remove HA entities for any curtain slots that were deleted
    _remove_curtain_entities_above(hass, coord.host, area_num, len(new_curtains), old_curtain_count)

    type_changed     = old_type != ar.area_type
    curtains_added   = len(new_curtains) > old_curtain_count

    # When leaving 'light' type: remove preset/save-preset/channel entities
    if type_changed and old_type == AREA_TYPE_LIGHT:
        _remove_light_only_entities(hass, coord.host, area_num, ar.channels)

    coord.schedule_save()
    LOGGER.info("[WS] updated area %d (type: %s→%s, curtains: %d→%d)",
                area_num, old_type, ar.area_type, old_curtain_count, len(new_curtains))

    # Fire entity-creation callbacks:
    # - always when type changed (new area_type may need new entities)
    # - also when curtains were added to an existing blind area
    if type_changed or curtains_added:
        if ar.area_type == AREA_TYPE_HVAC:
            for cb in coord.on_new_climate_cbs:
                cb()
        for cb in coord.on_new_area_cbs:
            cb()

    # Always push a signal_area so existing entities (climate, sensors, …)
    # pick up any changed fields (setpt_step, name, fade, etc.) immediately
    # without requiring a restart or reload.
    from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
    from .const import signal_area  # noqa: PLC0415
    async_dispatcher_send(hass, signal_area(coord.host, area_num), ar)

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
    ar = coord.areas.get(area_num)
    if ar is not None:
        # Remove every HA entity that belongs to this area before wiping state
        _remove_all_area_entities(hass, coord.host, area_num, ar)
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

    area_num   = msg["area"]
    ch0        = msg["ch0"]
    new_type   = msg["channel_type"]
    new_name   = msg["name"]
    new_partner = msg.get("cover_partner_ch0")

    ar = coord._touch_area(area_num)  # noqa: SLF001  — creates area if new

    # ── 1. Remove any existing HA entity for this (area, ch0) slot ──────────────
    #        Scan by config_entry_id — avoids unique_id format guessing.
    #        Handles: re-adding a deleted channel, type override, manual HA delete.
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    ent_reg = er.async_get(hass)
    ch_key  = f"_a{area_num}_c{ch0}_"
    cov_key = f"_a{area_num}_cover_{ch0}_"
    for entry in list(ent_reg.entities.values()):
        if entry.config_entry_id == msg["entry_id"]:
            uid = entry.unique_id
            if ch_key in uid or cov_key in uid:
                ent_reg.async_remove(entry.entity_id)
                LOGGER.info("[WS] cleared old entity %s before re-add", entry.entity_id)

    # ── 3. Evict (area, ch0) from every platform's known set ────────────────────
    for cb in coord.on_channel_type_change_cbs:
        cb(area_num, ch0)

    # ── 4. Create / update channel in coordinator with correct type ──────────────
    ch = ar.channels.get(ch0)
    if ch is None:
        ch = ChannelState(area=area_num, ch0=ch0)
        ar.channels[ch0] = ch
    ch.channel_type = new_type
    ch.name         = new_name
    if new_partner is not None:
        ch.cover_partner_ch0 = new_partner
    coord.schedule_save()
    LOGGER.info("[WS] added channel A%d Ch%d type=%s", area_num, ch0, new_type)

    # ── 5. Fire creation callbacks — entity is now registered with correct type ──
    for cb in coord.on_new_channel_cbs:
        cb()

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
        # Remove old entity from registry before creating the new one
        _remove_channel_entity(hass, coord.host, msg["area"], msg["ch0"], old_type, old_partner)

    # When a cover is configured, the DOWN partner channel must lose its light entity
    if ch.channel_type == "cover" and ch.cover_partner_ch0 is not None:
        partner_ch = ar.channels.get(ch.cover_partner_ch0)
        if partner_ch:
            _remove_channel_entity(
                hass, coord.host, msg["area"],
                ch.cover_partner_ch0,
                partner_ch.channel_type,
                partner_ch.cover_partner_ch0,
            )
            for cb in coord.on_channel_type_change_cbs:
                cb(msg["area"], ch.cover_partner_ch0)
            LOGGER.info(
                "[WS] removed partner channel entity A%d Ch%d (DOWN relay of cover Ch%d)",
                msg["area"], ch.cover_partner_ch0, msg["ch0"],
            )

    if type_changed:
        # Evict from each platform's `known` set so the new entity type gets created
        for cb in coord.on_channel_type_change_cbs:
            cb(msg["area"], msg["ch0"])
        for cb in coord.on_new_channel_cbs:
            cb()
    else:
        # Name-only change: push a signal so the existing entity refreshes immediately
        from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
        from .const import signal_channel  # noqa: PLC0415
        async_dispatcher_send(hass, signal_channel(coord.host, msg["area"], msg["ch0"]), ch)

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

    area_num = msg["area"]
    ch0      = msg["ch0"]
    ar = coord.areas.get(area_num)
    if ar and ch0 in ar.channels:
        # 1. Remove entity from the HA entity registry by scanning all entries for
        #    this config entry — more robust than exact unique_id lookup.
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
        ent_reg  = er.async_get(hass)
        ch_key   = f"_a{area_num}_c{ch0}_"       # matches light / switch
        cov_key  = f"_a{area_num}_cover_{ch0}_"   # matches channel-cover UP channel
        for entry in list(er.async_entries_for_config_entry(ent_reg, msg["entry_id"])):
            if ch_key in entry.unique_id or cov_key in entry.unique_id:
                ent_reg.async_remove(entry.entity_id)
                LOGGER.info("[WS] removed entity %s (uid=%s)", entry.entity_id, entry.unique_id)
        # 2. Also signal live entity objects so they tear themselves down cleanly
        async_dispatcher_send(hass, signal_channel_remove(coord.host, area_num, ch0))
        # 3. Evict from each platform's known set so it won't be re-created
        for cb in coord.on_channel_type_change_cbs:
            cb(area_num, ch0)
        # 4. Remove from in-memory state and persist
        del ar.channels[ch0]
        coord.schedule_save()
        LOGGER.info("[WS] deleted channel A%d Ch%d", area_num, ch0 + 1)
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
        # Remove the motion sensor entity and its occupancy switch from HA
        ent_reg = er.async_get(hass)
        for platform, uid_suffix in (
            ("binary_sensor", f"a{area_num}_motion"),
            ("switch",        f"a{area_num}_occ_switch"),
        ):
            uid       = f"{coord.host}_{uid_suffix}"
            entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, uid)
            if entity_id:
                ent_reg.async_remove(entity_id)
                LOGGER.info("[WS] removed entity %s", entity_id)
        # Update known_pir closure so PIR can be re-enabled without a restart
        for cb in coord.on_remove_pir_cbs:
            cb(area_num)
        LOGGER.info("[WS] PIR disabled for area %d", area_num)

    connection.send_result(msg["id"], {"ok": True, "has_pir": ar.has_pir})


# ── set_temp_sensor ───────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/set_temp_sensor",
    vol.Required("entry_id"): str,
    vol.Required("area"):     vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("has_temp"): bool,
})
@websocket_api.async_response
async def ws_set_temp_sensor(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Enable or disable a temperature sensor on a logical area.

    Enabling  → sets has_temp=True, fires on_new_sensor_cbs to create the entity.
    Disabling → sets has_temp=False, removes the entity from the registry,
                fires on_remove_sensor_cbs so the area can be re-enabled later.
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

    ar.has_temp = msg["has_temp"]
    coord.schedule_save()

    if msg["has_temp"]:
        for cb in coord.on_new_sensor_cbs:
            cb()
        LOGGER.info("[WS] temperature sensor enabled for area %d", area_num)
    else:
        ent_reg   = er.async_get(hass)
        uid       = f"{coord.host}_a{area_num}_temp"
        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
        if entity_id:
            ent_reg.async_remove(entity_id)
            LOGGER.info("[WS] removed temperature sensor entity %s", entity_id)
        for cb in coord.on_remove_sensor_cbs:
            cb(area_num)
        LOGGER.info("[WS] temperature sensor disabled for area %d", area_num)

    connection.send_result(msg["id"], {"ok": True, "has_temp": ar.has_temp})


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
            "has_lux":        dev.has_lux,
            "motion_detected": dev.motion_detected,
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
        hass, signal_device(coord.host, msg["device_code"], msg["box_number"]), coord.device_online.get((msg["device_code"], msg["box_number"]), False)
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
    """Remove a physical device entry and ALL its HA entities/device from HA."""
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    device_code = msg["device_code"]
    box_number  = msg["box_number"]
    key         = (device_code, box_number)

    # ── Fire removal callbacks BEFORE popping, so callbacks can read the dev ──
    dev = coord.devices.get(key)
    if dev and dev.has_lux:
        for cb in coord.on_remove_lux_cbs:
            cb(device_code, box_number)
    for cb in coord.on_remove_device_cbs:
        cb(device_code, box_number)

    # ── Remove from coordinator state ─────────────────────────────────────────
    coord.devices.pop(key, None)
    coord.device_online.pop(key, None)
    coord._device_last_seen.pop(key, None)  # noqa: SLF001
    coord.schedule_save()

    # ── Remove the HA device (cascades: HA deletes all attached entities) ─────
    dev_reg    = dr.async_get(hass)
    identifier = (DOMAIN, f"{coord.host}_{device_code}_{box_number}")
    ha_device  = dev_reg.async_get_device(identifiers={identifier})
    if ha_device:
        dev_reg.async_remove_device(ha_device.id)
        LOGGER.info(
            "[WS] removed HA device %s (cascaded entity removal)", ha_device.id
        )

    LOGGER.info("[WS] deleted device 0x%02X box %d", device_code, box_number)
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

        # Import preset names if the XML (or manual payload) supplies them
        raw_preset_names = area_dict.get("preset_names") or {}
        if raw_preset_names:
            merged: dict[int, str] = dict(ar.preset_names)  # keep existing overrides
            for k, v in raw_preset_names.items():
                try:
                    pnum = int(k)
                except (ValueError, TypeError):
                    continue
                name_str = str(v).strip()
                if name_str:
                    merged[pnum] = name_str
            ar.preset_names = merged

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

    if type_changed:
        # Fire entity-creation callbacks (same pattern as ws_update_channel).
        # We don't know exactly which channels changed type, so fire on_new_channel_cbs
        # which will create any missing entities.  Entities for old types were not
        # removed here (import doesn't call _remove_channel_entity), so stale ones
        # may linger until next HA restart — acceptable for a bulk import.
        for cb in coord.on_new_area_cbs:
            cb()
        for cb in coord.on_new_channel_cbs:
            cb()

    connection.send_result(msg["id"], {"ok": True, "imported": imported, "skipped": skipped, "reloading": False})


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


# ── set_lux_sensor ────────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/set_lux_sensor",
    vol.Required("entry_id"):    str,
    vol.Required("device_code"): int,
    vol.Required("box_number"):  int,
    vol.Required("has_lux"):     bool,
})
@websocket_api.async_response
async def ws_set_lux_sensor(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Enable or disable an illuminance sensor on a physical device.

    Enabling  → sets has_lux=True, fires on_new_lux_cbs to create the entity.
    Disabling → sets has_lux=False, removes the entity from the registry,
                fires on_remove_lux_cbs so it can be re-enabled later.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    key = (msg["device_code"], msg["box_number"])
    dev = coord.devices.get(key)
    if not dev:
        connection.send_error(msg["id"], "not_found",
                              f"Device 0x{msg['device_code']:02X} box {msg['box_number']} not found")
        return

    dev.has_lux = msg["has_lux"]
    coord.schedule_save()

    if msg["has_lux"]:
        for cb in coord.on_new_lux_cbs:
            cb()
        LOGGER.info("[WS] lux sensor enabled for device 0x%02X box %d",
                    msg["device_code"], msg["box_number"])
    else:
        ent_reg   = er.async_get(hass)
        uid       = f"{coord.host}_lux_{msg['device_code']}_{msg['box_number']}"
        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
        if entity_id:
            ent_reg.async_remove(entity_id)
            LOGGER.info("[WS] removed lux sensor entity %s", entity_id)
        for cb in coord.on_remove_lux_cbs:
            cb(msg["device_code"], msg["box_number"])
        LOGGER.info("[WS] lux sensor disabled for device 0x%02X box %d",
                    msg["device_code"], msg["box_number"])

    connection.send_result(msg["id"], {"ok": True, "has_lux": dev.has_lux})


# ── request_motion_status ──────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/request_motion_status",
    vol.Required("entry_id"):    str,
    vol.Required("box_numbers"): [int],   # list of box numbers to poll
})
@websocket_api.async_response
async def ws_request_motion_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Send a Request Physical Status (0xB7) to one or more D5 Sensor boxes.

    The device replies with a 0xB8 / b[4]=0x0D frame which the coordinator
    handles and broadcasts as a dynalite_pdeg_device_motion HA event.
    """
    import asyncio as _asyncio  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return
    if not coord.client.connected:
        connection.send_error(msg["id"], "not_connected", "PDEG not connected")
        return

    box_numbers = msg["box_numbers"]
    for bn in box_numbers:
        await coord.client.request_motion_status(0xB3, bn)
        if len(box_numbers) > 1:
            await _asyncio.sleep(0.05)   # small gap between frames

    LOGGER.info("[WS] motion status requested for %d D5 Sensor(s): %s", len(box_numbers), box_numbers)
    connection.send_result(msg["id"], {"ok": True, "polled": box_numbers})


# ── update_preset_names ────────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"):        "dynalite_pdeg/update_preset_names",
    vol.Required("entry_id"):    str,
    vol.Required("area"):        vol.All(int, vol.Range(min=1, max=255)),
    vol.Required("preset_names"): dict,   # {"1": "Full", "2": "Dim", ...}
})
@websocket_api.async_response
async def ws_update_preset_names(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Save user-defined preset names for an area.

    ``preset_names`` is a dict with string keys (1-based preset number) and
    string values (display name).  Empty string values clear the override.
    """
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    area_num = msg["area"]
    ar = coord.areas.get(area_num)
    if not ar:
        connection.send_error(msg["id"], "not_found", f"Area {area_num} not found")
        return

    # Convert string keys → int; drop entries with empty names
    new_names: dict[int, str] = {}
    for k, v in msg["preset_names"].items():
        try:
            preset_num = int(k)
        except (ValueError, TypeError):
            continue
        name = str(v).strip()
        if name:
            new_names[preset_num] = name

    ar.preset_names = new_names
    coord.schedule_save()

    # Push signal_area so preset-selector entity labels update immediately
    from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
    from .const import signal_area  # noqa: PLC0415
    async_dispatcher_send(hass, signal_area(coord.host, area_num), ar)

    LOGGER.info("[WS] preset names updated for area %d: %s", area_num, new_names)
    connection.send_result(msg["id"], {"ok": True, "preset_names": {str(k): v for k, v in new_names.items()}})


# ── get_backup ────────────────────────────────────────────────────────────────

@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/get_backup",
    vol.Required("entry_id"): str,
    vol.Required("section"):  vol.In(["logical", "physical"]),
})
@websocket_api.async_response
async def ws_get_backup(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a serialised backup of the logical (areas/channels) or physical
    (devices) configuration so the panel can offer a JSON download."""
    import datetime  # noqa: PLC0415

    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    from .storage import DynaliteStorage  # noqa: PLC0415
    full    = DynaliteStorage._serialize(coord)
    section = msg["section"]

    result: dict = {
        "version":   1,
        "section":   section,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if section == "logical":
        result["areas"] = full["areas"]
    else:  # physical
        result["devices"]          = full["devices"]
        result["signon_interval"]  = full["signon_interval"]

    LOGGER.info("[WS] backup requested: section=%s  areas=%d  devices=%d",
                section,
                len(result.get("areas",   [])),
                len(result.get("devices", [])))
    connection.send_result(msg["id"], result)


# ── restore_backup ────────────────────────────────────────────────────────────

@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"):     "dynalite_pdeg/restore_backup",
    vol.Required("entry_id"): str,
    vol.Required("section"):  vol.In(["logical", "physical"]),
    vol.Required("data"):     dict,
})
@websocket_api.async_response
async def ws_restore_backup(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Apply a backup dict to the coordinator, persist it, then reload the entry."""
    coord = _get_coordinator(hass, msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Integration not found")
        return

    backup  = msg["data"]
    section = msg["section"]

    # ── Validate basic structure ──────────────────────────────────────────────
    if backup.get("version") != 1:
        connection.send_error(msg["id"], "invalid_data", "Unsupported backup version")
        return
    if backup.get("section") not in (section, None):
        connection.send_error(
            msg["id"], "invalid_data",
            f"Backup section mismatch: file is '{backup.get('section')}', expected '{section}'"
        )
        return

    if section == "logical":
        # ── Re-populate areas from backup ─────────────────────────────────────
        from .coordinator import (  # noqa: PLC0415
            AreaState, ChannelState, AREA_TYPE_LIGHT,
            CHANNEL_TYPE_DIMMER, CHANNEL_TYPE_ONOFF,
        )
        coord.areas.clear()
        for a in backup.get("areas", []):
            area_num = a.get("area")
            if not area_num:
                continue
            ar = AreaState(
                area=area_num,
                name=a.get("name", ""),
                preset_count=int(a.get("preset_count", 4)),
                fade_tenths=int(a.get("fade_tenths", 20)),
                area_type=a.get("area_type", AREA_TYPE_LIGHT),
                has_pir=bool(a.get("has_pir", False)),
                occ_enabled=bool(a.get("occ_enabled", True)),
                curtains=a.get("curtains", []),
                hvac_mode_area=int(a.get("hvac_mode_area", 0)),
                hvac_mode_method=a.get("hvac_mode_method", ""  ),
                hvac_mode_ch0=int(a.get("hvac_mode_ch0", 0)),
                hvac_mode_map=a.get("hvac_mode_map", {}),
                hvac_fan_area=int(a.get("hvac_fan_area", 0)),
                hvac_fan_method=a.get("hvac_fan_method", ""),
                hvac_fan_ch0=int(a.get("hvac_fan_ch0", 0)),
                hvac_fan_map=a.get("hvac_fan_map", {}),
                setpt_step=float(a.get("setpt_step", 0.5)),
                has_temp=bool(a.get("has_temp", False)),
                preset_names={int(k): v for k, v in a.get("preset_names", {}).items()},
            )
            for c in a.get("channels", []):
                ch0 = c.get("ch0")
                if ch0 is None:
                    continue
                if "channel_type" in c:
                    ch_type = c["channel_type"]
                elif c.get("is_dimmable", True):
                    ch_type = CHANNEL_TYPE_DIMMER
                else:
                    ch_type = CHANNEL_TYPE_ONOFF
                partner = c.get("cover_partner_ch0")
                ch = ChannelState(
                    area=area_num,
                    ch0=int(ch0),
                    name=c.get("name", ""),
                    channel_type=ch_type,
                    cover_partner_ch0=int(partner) if partner is not None else None,
                )
                ar.channels[ch.ch0] = ch
            coord.areas[area_num] = ar
        LOGGER.info("[WS] restore logical: %d areas loaded", len(coord.areas))

    else:  # physical
        # ── Re-populate devices from backup ───────────────────────────────────
        from .coordinator import PhysicalDevice  # noqa: PLC0415
        from .const import DEVICE_NAMES          # noqa: PLC0415
        coord.devices.clear()
        for d in backup.get("devices", []):
            code = d.get("device_code")
            box  = d.get("box_number")
            if code is None or box is None:
                continue
            model = DEVICE_NAMES.get(int(code), f"Device 0x{int(code):02X}")
            coord.devices[(int(code), int(box))] = PhysicalDevice(
                device_code=int(code),
                box_number=int(box),
                model=model,
                name=d.get("name", ""),
                has_lux=bool(d.get("has_lux", False)),
                has_motion=bool(d.get("has_motion", False)),
            )
        if "signon_interval" in backup:
            coord.signon_interval = int(backup["signon_interval"])
        LOGGER.info("[WS] restore physical: %d devices loaded", len(coord.devices))

    # ── Persist and reload ────────────────────────────────────────────────────
    if coord._storage:  # noqa: SLF001
        await coord._storage.async_save(coord)  # noqa: SLF001

    connection.send_result(msg["id"], {"ok": True, "reloading": True})

    # Reload the config entry so all entities are recreated cleanly
    hass.async_create_task(hass.config_entries.async_reload(msg["entry_id"]))
    LOGGER.info("[WS] restore_backup complete: section=%s — reloading entry", section)
