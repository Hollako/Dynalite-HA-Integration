"""Config flow for Dynalite PDEG integration."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import CONF_HOST, CONF_PORT, CONF_NAME, DEFAULT_NAME, DEFAULT_PORT, DOMAIN, LOGGER
from .coordinator import (
    CHANNEL_TYPE_COVER,
    CHANNEL_TYPE_DIMMER,
    CHANNEL_TYPE_ONOFF,
    CHANNEL_TYPE_SWITCH,
)

_CHANNEL_TYPE_OPTIONS = [
    {"value": CHANNEL_TYPE_DIMMER, "label": "Dimmer (dimmable light)"},
    {"value": CHANNEL_TYPE_ONOFF,  "label": "On/Off (relay light)"},
    {"value": CHANNEL_TYPE_SWITCH, "label": "Switch"},
    {"value": CHANNEL_TYPE_COVER,  "label": "Cover / Curtain"},
]


class DynalitePdegConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]

            # Prevent duplicate entries for the same host:port
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            # Quick connectivity check
            error = await self._test_connection(host, port)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, host),
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    async def _test_connection(host: str, port: int) -> str | None:
        """Try to open a TCP connection. Returns error key or None on success."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return None
        except asyncio.TimeoutError:
            return "timeout"
        except OSError as exc:
            LOGGER.debug("Connection test failed: %s", exc)
            return "cannot_connect"
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Unexpected error during connection test: %s", exc)
            return "unknown"

    # ── Reconfigure (change host / port / name after initial setup) ───────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to change host, port or name without deleting the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]

            error = await self._test_connection(host, port)
            if error:
                errors["base"] = error
            else:
                new_unique_id = f"{host}:{port}"
                await self.async_set_unique_id(new_unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port},
                )
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: user_input.get(CONF_NAME) or host,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Optional(CONF_NAME, default=entry.data.get(CONF_NAME, DEFAULT_NAME)): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return DynalitePdegOptionsFlow(config_entry)


class DynalitePdegOptionsFlow(OptionsFlow):
    """Options flow — scan settings and area/channel management."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    # ── Step 1: Scan settings ─────────────────────────────────────────────────

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan range settings + optional immediate scan trigger."""
        if user_input is not None:
            self._options.update(
                {
                    "area_min":      user_input["area_min"],
                    "area_max":      user_input["area_max"],
                    "channel_count": user_input["channel_count"],
                    "delay_ms":      user_input["delay_ms"],
                }
            )
            # Trigger scan if requested
            if user_input.get("run_scan"):
                coordinator = self._entry.runtime_data
                if coordinator and coordinator.client.connected:
                    asyncio.ensure_future(
                        coordinator.async_scan(
                            area_min=user_input["area_min"],
                            area_max=user_input["area_max"],
                            channel_count=user_input["channel_count"],
                            delay_ms=user_input["delay_ms"],
                        )
                    )
            # Proceed to area management step
            return await self.async_step_areas()

        opts = self._options
        schema = vol.Schema(
            {
                vol.Optional("area_min",      default=opts.get("area_min", 2)):      NumberSelector(NumberSelectorConfig(min=1,  max=255, step=1, mode=NumberSelectorMode.BOX)),
                vol.Optional("area_max",      default=opts.get("area_max", 20)):     NumberSelector(NumberSelectorConfig(min=1,  max=255, step=1, mode=NumberSelectorMode.BOX)),
                vol.Optional("channel_count", default=opts.get("channel_count", 8)): NumberSelector(NumberSelectorConfig(min=1,  max=64,  step=1, mode=NumberSelectorMode.BOX)),
                vol.Optional("delay_ms",      default=opts.get("delay_ms", 50)):     NumberSelector(NumberSelectorConfig(min=10, max=500, step=10, mode=NumberSelectorMode.BOX)),
                vol.Optional("run_scan",      default=False):                         BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "area_count": str(len(getattr(self._entry, "runtime_data", None) and
                                   self._entry.runtime_data.areas or {}))
            },
        )

    # ── Step 2: Add / remove areas ────────────────────────────────────────────

    async def async_step_areas(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage which areas are tracked."""
        coordinator = getattr(self._entry, "runtime_data", None)
        errors: dict[str, str] = {}

        if user_input is not None:
            # ── Remove selected areas ────────────────────────────────────────
            for area_str in user_input.get("remove_areas", []):
                try:
                    area_num = int(area_str)
                    if coordinator and area_num in coordinator.areas:
                        del coordinator.areas[area_num]
                        coordinator.schedule_save()
                        LOGGER.info("[Options] removed area %d", area_num)
                except ValueError:
                    pass

            # ── Add manually specified areas ─────────────────────────────────
            add_raw = user_input.get("add_areas", "").strip()
            if add_raw and coordinator:
                added = []
                for part in add_raw.replace(",", " ").split():
                    try:
                        area_num = int(part)
                        if 1 <= area_num <= 255:
                            coordinator._touch_area(area_num)  # noqa: SLF001
                            added.append(area_num)
                    except ValueError:
                        errors["add_areas"] = "invalid_area"
                if added:
                    LOGGER.info("[Options] added areas: %s", added)
                    # Scan the newly added areas only
                    channel_count = self._options.get("channel_count", 8)
                    for area_num in added:
                        asyncio.ensure_future(
                            coordinator.async_scan(
                                area_min=area_num,
                                area_max=area_num,
                                channel_count=channel_count,
                                delay_ms=self._options.get("delay_ms", 50),
                            )
                        )

            if not errors:
                return await self.async_step_channels_area()

        # Build area list for the remove multi-select
        known_areas: dict[str, str] = {}
        if coordinator:
            for area_num, ar in sorted(coordinator.areas.items()):
                ch_count = len(ar.channels)
                label = f"Area {area_num}"
                if ar.name:
                    label = f"{ar.name} (Area {area_num})"
                label += f" — {ch_count} ch"
                known_areas[str(area_num)] = label

        schema_fields: dict = {
            vol.Optional("add_areas", default=""): TextSelector(),
        }
        if known_areas:
            schema_fields[vol.Optional("remove_areas", default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in known_areas.items()],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        return self.async_show_form(
            step_id="areas",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    # ── Step 3: Pick area to manage channels ──────────────────────────────────

    async def async_step_channels_area(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which area to manage channels for, or finish."""
        coordinator = getattr(self._entry, "runtime_data", None)

        if user_input is not None:
            area_str = user_input.get("area", "__done__")
            if area_str == "__done__" or not coordinator:
                return self.async_create_entry(title="", data=self._options)
            self._editing_area = int(area_str)
            return await self.async_step_channels_edit()

        if not coordinator or not coordinator.areas:
            return self.async_create_entry(title="", data=self._options)

        area_options = [{"value": "__done__", "label": "✓  Done — save and finish"}]
        for area_num, ar in sorted(coordinator.areas.items()):
            ch_count = len(ar.channels)
            label = f"{ar.display_name()}  —  {ch_count} channel(s)"
            area_options.append({"value": str(area_num), "label": label})

        return self.async_show_form(
            step_id="channels_area",
            data_schema=vol.Schema({
                vol.Required("area", default="__done__"): SelectSelector(
                    SelectSelectorConfig(options=area_options, mode=SelectSelectorMode.LIST)
                ),
            }),
        )

    # ── Step 4: Manage channels for a specific area ───────────────────────────

    async def async_step_channels_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add channels, change channel types, or remove channels."""
        coordinator = getattr(self._entry, "runtime_data", None)
        area_num: int = getattr(self, "_editing_area", 0)
        errors: dict[str, str] = {}

        if user_input is not None and coordinator:
            ar = coordinator.areas.get(area_num)

            # ── Remove channels ──────────────────────────────────────────────
            for ch_str in user_input.get("remove_channels", []):
                try:
                    ch0 = int(ch_str)
                    if ar and ch0 in ar.channels:
                        del ar.channels[ch0]
                        coordinator.schedule_save()
                except ValueError:
                    pass

            # ── Change type on existing channels ─────────────────────────────
            new_type = user_input.get("change_type", CHANNEL_TYPE_DIMMER)
            for ch_str in user_input.get("change_type_channels", []):
                try:
                    ch0 = int(ch_str)
                    if ar and ch0 in ar.channels:
                        ar.channels[ch0].channel_type = new_type
                        coordinator.schedule_save()
                except ValueError:
                    pass

            # ── Add new channels ─────────────────────────────────────────────
            add_raw = user_input.get("add_channels", "").strip()
            add_type = user_input.get("add_type", CHANNEL_TYPE_DIMMER)
            if add_raw:
                if ar is None:
                    ar = coordinator._touch_area(area_num)  # noqa: SLF001
                for part in add_raw.replace(",", " ").split():
                    try:
                        ch0 = int(part)
                        if 0 <= ch0 <= 63:
                            ch = coordinator._touch_channel(ar, ch0)  # noqa: SLF001
                            ch.channel_type = add_type
                            coordinator.schedule_save()
                        else:
                            errors["add_channels"] = "invalid_channel"
                    except ValueError:
                        errors["add_channels"] = "invalid_channel"

            if not errors:
                return await self.async_step_channels_area()

        # ── Build the form ────────────────────────────────────────────────────
        ar = coordinator.areas.get(area_num) if coordinator else None
        area_name = ar.display_name() if ar else f"Area {area_num}"

        existing: dict[str, str] = {}
        if ar:
            type_labels = {
                CHANNEL_TYPE_DIMMER: "Dimmer",
                CHANNEL_TYPE_ONOFF:  "On/Off",
                CHANNEL_TYPE_SWITCH: "Switch",
                CHANNEL_TYPE_COVER:  "Cover",
            }
            for ch0, ch in sorted(ar.channels.items()):
                type_lbl = type_labels.get(ch.channel_type, ch.channel_type)
                label = ch.name if ch.name else f"Ch {ch0 + 1}"
                existing[str(ch0)] = f"{label}  (ch{ch0}, {type_lbl})"

        schema_fields: dict = {
            vol.Optional("add_channels", default=""): TextSelector(),
            vol.Optional("add_type", default=CHANNEL_TYPE_DIMMER): SelectSelector(
                SelectSelectorConfig(options=_CHANNEL_TYPE_OPTIONS, mode=SelectSelectorMode.LIST)
            ),
        }
        if existing:
            ch_opts = [{"value": k, "label": v} for k, v in existing.items()]
            schema_fields[vol.Optional("change_type_channels", default=[])] = SelectSelector(
                SelectSelectorConfig(options=ch_opts, multiple=True, mode=SelectSelectorMode.LIST)
            )
            schema_fields[vol.Optional("change_type", default=CHANNEL_TYPE_DIMMER)] = SelectSelector(
                SelectSelectorConfig(options=_CHANNEL_TYPE_OPTIONS, mode=SelectSelectorMode.LIST)
            )
            schema_fields[vol.Optional("remove_channels", default=[])] = SelectSelector(
                SelectSelectorConfig(options=ch_opts, multiple=True, mode=SelectSelectorMode.LIST)
            )

        return self.async_show_form(
            step_id="channels_edit",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={"area_name": area_name},
        )
