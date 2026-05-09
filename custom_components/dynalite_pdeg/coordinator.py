"""Dynalite coordinator — holds all area/channel state and dispatches HA signals."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DEVICE_NAMES,
    DOMAIN,
    LOGGER,
    OP_LEVEL_REPORT,
    OP_LUX_REPORT,
    OP_MOTION_DETECT,
    OP_OCC_DISABLE,
    OP_OCC_ENABLE,
    OP_OCCUPANCY,
    OP_PRESET_REPORT,
    OP_REQUEST_PRESET,
    OP_SETPOINT_REPORT,
    OP_SIGNON_REPLY,
    OP_SIGNON_REPLY_AC,
    OP_SIGNON_REQUEST,
    OP_TEMP_REPORT,
    OP_TEMP_REPORT_ALT,
    RELAY_DEVICE_CODES,
    SENSOR_DEVICE_CODES,
    SIGNON_INTERVAL,
    SIGNON_RESPONSE_TIMEOUT,
    SIGNON_RETRIES,
    SYNC_LOGICAL,
    SYNC_PHYSICAL,
    SYNC_SIGNON,
    dynalite_to_pct,
    signal_area,
    signal_channel,
    signal_connection,
    signal_device,
    signal_lux,
)
from .dynalite_client import DynaliteClient

if TYPE_CHECKING:
    pass


# ── Data classes ──────────────────────────────────────────────────────────────

CHANNEL_TYPE_DIMMER = "dimmer"    # dimmable light
CHANNEL_TYPE_ONOFF  = "onoff"     # on/off relay light
CHANNEL_TYPE_SWITCH = "switch"    # switch entity
CHANNEL_TYPE_COVER  = "cover"     # cover / curtain


@dataclass
class ChannelState:
    area: int
    ch0: int                          # 0-based channel index
    pct: int = 0                      # 0-100 %
    is_on: bool = False
    channel_type: str = CHANNEL_TYPE_DIMMER   # dimmer | onoff | switch | cover
    name: str = ""                    # custom name; "" = default
    cover_partner_ch0: int | None = None  # cover only: the DOWN relay channel (0-based)


AREA_TYPE_LIGHT = "light"
AREA_TYPE_BLIND = "blind"
AREA_TYPE_HVAC  = "hvac"


@dataclass
class AreaState:
    area: int
    preset0: int = 0xFF          # 0xFF = unknown
    name: str = ""
    preset_count: int = 4
    fade_tenths: int = 20        # default 2 s
    area_type: str = AREA_TYPE_LIGHT   # light | blind | hvac
    has_pir: bool = False
    pir_occupied: bool = False
    occ_enabled: bool = True
    has_temp: bool = False
    temp_c: float = math.nan
    has_setpt: bool = False
    setpt_c: float = math.nan
    # Blind area — list of curtain dicts, each:
    #   {"name": str, "open_preset": int, "stop_preset": int, "close_preset": int}
    curtains: list = field(default_factory=list)
    # HVAC mode control (area_type == "hvac" only)
    #   method: "" | "preset" | "channel"
    #   area:   0  = same area as the HVAC area; non-zero = a different Dynalite area
    #   map: {ha_mode_str: preset1} for preset method
    #        {ha_mode_str: level_pct} for channel method
    hvac_mode_area:   int  = 0
    hvac_mode_method: str  = ""
    hvac_mode_ch0:    int  = 0
    hvac_mode_map:    dict = field(default_factory=dict)
    # HVAC fan speed control
    hvac_fan_area:    int  = 0
    hvac_fan_method:  str  = ""
    hvac_fan_ch0:     int  = 0
    hvac_fan_map:     dict = field(default_factory=dict)
    # Setpoint step size in °C (0.5 or 1.0)
    setpt_step: float = 0.5
    channels: dict[int, ChannelState] = field(default_factory=dict)  # keyed by ch0

    def display_name(self) -> str:
        return self.name if self.name else f"Area {self.area}"


@dataclass
class PhysicalDevice:
    device_code: int
    box_number: int
    area: int = 0
    model: str = ""
    name: str = ""          # user-defined custom name (empty = use model default)
    has_lux: bool = False
    lux_value: float | None = None


# ── Coordinator ───────────────────────────────────────────────────────────────

class DynaliteCoordinator:
    """Central state store for all discovered Dynalite areas/channels."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.connected = False
        self.areas: dict[int, AreaState] = {}          # keyed by area number
        self.devices: dict[tuple[int, int], PhysicalDevice] = {}  # (code, box)
        # Device online/offline tracking
        self.device_online: dict[tuple[int, int], bool] = {}
        self._device_last_seen: dict[tuple[int, int], float] = {}
        self._signon_task: asyncio.Task | None = None
        # Configurable sign-on poll interval (seconds); persisted via storage
        self.signon_interval: int = SIGNON_INTERVAL
        # Platform hooks — lists so multiple platforms can register
        self.on_new_channel_cbs: list[callable] = []   # type: ignore[type-arg]
        self.on_new_area_cbs:    list[callable] = []   # type: ignore[type-arg]
        self.on_new_pir_cbs:     list[callable] = []   # type: ignore[type-arg]
        self.on_remove_pir_cbs:  list[callable] = []   # type: ignore[type-arg]  called with area:int when PIR is disabled
        self.on_new_sensor_cbs:  list[callable] = []   # type: ignore[type-arg]
        self.on_remove_sensor_cbs: list[callable] = []  # type: ignore[type-arg]  called with area:int when temp sensor disabled
        self.on_new_climate_cbs:  list[callable] = []   # type: ignore[type-arg]
        self.on_new_device_cbs:   list[callable] = []   # type: ignore[type-arg]
        self.on_new_lux_cbs:      list[callable] = []   # type: ignore[type-arg]
        self.on_remove_lux_cbs:   list[callable] = []   # type: ignore[type-arg]  called with (dc, bn) when lux disabled
        # Storage — injected by __init__.py after construction
        self._storage = None
        self._save_task: asyncio.Task | None = None
        self.client = DynaliteClient(
            host, port,
            self._on_frame,
            self._on_connection,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> bool:
        """Start TCP client. Returns True (connection errors handled internally)."""
        await self.client.start()
        self._signon_task = asyncio.ensure_future(self._signon_loop())
        return True

    async def async_unload(self) -> None:
        if self._signon_task:
            self._signon_task.cancel()
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            # Flush any pending save immediately before stopping
            if self._storage:
                await self._storage.async_save(self)
        await self.client.stop()

    # ── Debounced save ────────────────────────────────────────────────────────

    def schedule_save(self) -> None:
        """Schedule a debounced save (8 s delay, coalesces rapid changes)."""
        if self._storage is None:
            return
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.ensure_future(self._delayed_save())

    async def _delayed_save(self) -> None:
        await asyncio.sleep(8)
        if self._storage:
            await self._storage.async_save(self)

    # ── Connection callback ───────────────────────────────────────────────────

    async def _on_connection(self, connected: bool) -> None:
        self.connected = connected
        LOGGER.info("[Coordinator] connection: %s", "UP" if connected else "DOWN")
        async_dispatcher_send(self.hass, signal_connection(), connected)
        if connected:
            # Poll all known devices immediately on (re)connect
            if self.devices:
                asyncio.ensure_future(self._poll_all_devices())
            if self.areas:
                # Re-poll all known areas/channels to refresh state
                for area_num in list(self.areas):
                    await self.client.request_area_preset(area_num)
                    await asyncio.sleep(0.05)
                    for ch0 in list(self.areas[area_num].channels):
                        await self.client.request_level(area_num, ch0)
                        await asyncio.sleep(0.05)
            else:
                # No stored entities — run an initial auto-scan (areas 1-20, 8 ch each)
                LOGGER.info("[Coordinator] no saved entities — running initial scan")
                asyncio.ensure_future(
                    self.async_scan(area_min=2, area_max=20, channel_count=8, delay_ms=50)
                )

    # ── Frame dispatch ────────────────────────────────────────────────────────

    async def _on_frame(self, frame: bytes) -> None:
        if frame[0] == SYNC_LOGICAL:
            await self._handle_logical(frame)
        elif frame[0] == SYNC_PHYSICAL:
            self._handle_physical(frame)
        elif frame[0] == SYNC_SIGNON:
            self._handle_signon(frame)

    async def _handle_logical(self, b: bytes) -> None:
        area_num = b[1]
        opcode   = b[3]

        if opcode <= 0x07:
            # Select Preset command seen on the bus (from any source — System Builder,
            # wall panel, HA, etc.).
            # DyNet1 layout: b[3]=opcode (preset within bank 0-7), b[5]=Preset Bank.
            # b[4] is Fade Time Hi — NOT the bank.
            preset0 = b[5] * 8 + opcode
            LOGGER.debug("[A%d] preset select detected → P%d — requesting confirmation",
                         area_num, preset0 + 1)
            # Ask the area to report its active preset; the OP_PRESET_REPORT response
            # will update ar.preset0 and trigger a channel level poll automatically.
            await self.client.request_area_preset(area_num)
            return

        if opcode == 0x71:
            # Ramp-to-Level (DyNet1 spec): b[2]=channel (0-origin), b[4]=level
            ch_raw = b[2]
            if ch_raw == 0xFF:
                LOGGER.debug("[A%d] 0x71 broadcast set-level — polling all channels", area_num)
                asyncio.ensure_future(self._poll_channels(area_num))
            else:
                LOGGER.debug("[A%d Ch%d] 0x71 set-level detected — requesting level",
                             area_num, ch_raw + 1)
                asyncio.ensure_future(self._poll_single_channel(area_num, ch_raw))
            return

        if 0x80 <= opcode <= 0x83:
            # "Set Logical Channel Level" command family (opcodes 0x80–0x83).
            # Frame layout:
            #   b[2] = level (inverted: 0xFF=0%, 0x01=100%) — not used here
            #   b[3] = opcode (0x80–0x83) encodes sub-channel within bank (0–3)
            #   b[4] = bank code:
            #            >= 0x80 → bank = 2 * (255 - b[4])   e.g. 0xFF→0, 0xFE→2, 0xFD→4
            #            <  0x80 → bank = 2 * b[4] + 1       e.g. 0x00→1, 0x01→3, 0x02→5
            #   b[5] = fade time
            # Channel (0-based): ch0 = bank * 4 + (opcode - 0x80)
            sub_ch    = opcode - 0x80
            bank_code = b[4]
            bank      = 2 * (255 - bank_code) if bank_code >= 0x80 else 2 * bank_code + 1
            ch0       = bank * 4 + sub_ch
            LOGGER.debug("[A%d Ch%d] set-level (0x8x family) detected — requesting level",
                         area_num, ch0 + 1)
            asyncio.ensure_future(self._poll_single_channel(area_num, ch0))
            return

        if opcode == OP_PRESET_REPORT:
            # DyNet1 opcode 0x62 layout:
            #   b[2] = Preset (within bank, 0-origin, 0-7)
            #   b[4] = Channel  (informational — which channel triggered the report)
            #   b[5] = Preset Offset = bank number
            preset0 = b[5] * 8 + b[2]   # absolute 0-based preset index
            ar = self._touch_area(area_num)
            ar.preset0 = preset0
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            # Also notify any HVAC area whose mode/fan is preset-controlled from this area
            self._forward_hvac_signal(area_num)
            LOGGER.debug("[A%d] preset → %d (bank %d)", area_num, preset0 + 1, b[5])
            # Preset changed from any source (HA, System Builder, panel) —
            # poll channel levels so HA reflects the new state immediately.
            asyncio.ensure_future(self._poll_channels(area_num))

        elif opcode == OP_LEVEL_REPORT:
            ch0   = b[2]                 # 0-origin per DyNet1 spec
            level = b[4]                 # target level (0x01=100%, 0xFF=0%)
            pct   = dynalite_to_pct(level)
            ar    = self._touch_area(area_num)
            ch    = self._touch_channel(ar, ch0)
            ch.pct   = pct
            ch.is_on = pct > 0
            async_dispatcher_send(self.hass, signal_channel(area_num, ch0), ch)
            LOGGER.debug("[A%d Ch%d] level %d%%", area_num, ch0 + 1, pct)
            # Refresh any HVAC climate entity whose mode/fan channel just changed.
            # Covers both same-area and cross-area control configurations.
            for hvac_ar in self.areas.values():
                eff_mode = hvac_ar.hvac_mode_area or hvac_ar.area
                eff_fan  = hvac_ar.hvac_fan_area  or hvac_ar.area
                if (
                    (hvac_ar.hvac_mode_method == "channel" and eff_mode == area_num and hvac_ar.hvac_mode_ch0 == ch0) or
                    (hvac_ar.hvac_fan_method  == "channel" and eff_fan  == area_num and hvac_ar.hvac_fan_ch0  == ch0)
                ):
                    async_dispatcher_send(self.hass, signal_area(hvac_ar.area), hvac_ar)

        elif opcode == OP_OCCUPANCY:
            occupied = b[5] == 1
            ar = self._touch_area(area_num)
            is_new_pir = not ar.has_pir
            ar.has_pir = True
            ar.pir_occupied = occupied
            if is_new_pir:
                for cb in self.on_new_pir_cbs:
                    cb()
                self.schedule_save()
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            LOGGER.debug("[A%d] PIR → %s", area_num, "occupied" if occupied else "vacant")

        elif opcode == OP_OCC_ENABLE:
            ar = self._touch_area(area_num)
            ar.occ_enabled = True
            async_dispatcher_send(self.hass, signal_area(area_num), ar)

        elif opcode == OP_OCC_DISABLE:
            ar = self._touch_area(area_num)
            ar.occ_enabled = False
            async_dispatcher_send(self.hass, signal_area(area_num), ar)

        elif opcode == OP_MOTION_DETECT:
            # Instantaneous motion trigger (0x2E).
            # b[2] = triggering channel, 0-based (0x00=ch1, 0x01=ch2, … 0xFF=all channels).
            # Always means motion IS present; vacancy comes later via OP_OCCUPANCY (0x31).
            ch_raw = b[2]
            ch_label = "all" if ch_raw == 0xFF else str(ch_raw + 1)
            ar = self._touch_area(area_num)
            is_new_pir = not ar.has_pir
            ar.has_pir      = True
            ar.pir_occupied = True
            if is_new_pir:
                for cb in self.on_new_pir_cbs:
                    cb()
                self.schedule_save()
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            LOGGER.debug("[A%d] 0x2E motion trigger  ch=%s", area_num, ch_label)

        elif opcode == OP_TEMP_REPORT:
            # 0x4A format: b[4] = integer °C (signed byte), b[5] = hundredths.
            # Always store the value so climate entities can show current_temperature,
            # but do NOT auto-enable has_temp — that is controlled only by the user
            # via the panel toggle (ws_set_temp_sensor).
            ar = self._touch_area(area_num)
            ar.temp_c = self._decode_temp_4a(b[4], b[5])
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            LOGGER.debug("[A%d] temp %.2f°C (0x4A)", area_num, ar.temp_c)

        elif opcode == OP_TEMP_REPORT_ALT:
            # 0xF6 fallback: Q2 signed int16 (°C × 4). Same policy — store but
            # do not auto-enable has_temp.
            ar = self._touch_area(area_num)
            ar.temp_c = self._decode_temp(b[4], b[5])
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            LOGGER.debug("[A%d] temp %.2f°C (0xF6/Q2)", area_num, ar.temp_c)

        elif opcode == OP_SETPOINT_REPORT:
            ar = self._touch_area(area_num)
            is_new = not ar.has_setpt
            ar.has_setpt = True
            ar.setpt_c   = self._decode_temp(b[4], b[5])
            if is_new:
                for cb in self.on_new_sensor_cbs:
                    cb()
                if ar.has_temp:
                    for cb in self.on_new_climate_cbs:
                        cb()
                self.schedule_save()
            async_dispatcher_send(self.hass, signal_area(area_num), ar)
            LOGGER.debug("[A%d] setpt %.1f°C", area_num, ar.setpt_c)

    def _handle_physical(self, b: bytes) -> None:
        device_code = b[1]
        box_number  = b[2]
        opcode      = b[3]
        key = (device_code, box_number)

        if opcode == OP_SIGNON_REPLY:  # 0x00 = Device Identify reply
            # RX: 5C [dc] [bn] 0x00 [fw_major] [fw_minor] [boot] [cs]
            self._handle_signon_reply(device_code, box_number, b)
            return

        if opcode == OP_LUX_REPORT:  # 0xB8 — ambient light level
            # RX: 5C [dc] [bn] 0xB8 [01] [00] [lux] [cs]
            # Register device if first time seen
            if key not in self.devices:
                model = DEVICE_NAMES.get(device_code, f"Device 0x{device_code:02X}")
                dev = PhysicalDevice(device_code=device_code, box_number=box_number, model=model)
                self.devices[key] = dev
                for cb in self.on_new_device_cbs:
                    cb()
                self.schedule_save()
            dev = self.devices[key]
            # b[5] = high byte (each unit = 256 lux), b[6] = low byte (1–255 lux)
            lux = b[5] * 256 + b[6]
            dev.lux_value = float(lux)
            # Auto-enable the lux sensor the first time a reading arrives,
            # but only for D5 Sensor (0xB3) — the only device that sends lux.
            if not dev.has_lux and device_code == 0xB3:
                dev.has_lux = True
                for cb in self.on_new_lux_cbs:
                    cb()
                self.schedule_save()
                LOGGER.info("[Device 0x%02X box %d] lux sensor auto-enabled (%d lx)",
                            device_code, box_number, lux)
            async_dispatcher_send(self.hass, signal_lux(device_code, box_number))
            LOGGER.debug("[Device 0x%02X box %d] lux = %d lx (hi=%d lo=%d)",
                         device_code, box_number, lux, b[5], b[6])
            return

        # Any other physical frame — register device if new, no online update
        if key not in self.devices:
            model = DEVICE_NAMES.get(device_code, f"Device 0x{device_code:02X}")
            dev = PhysicalDevice(device_code=device_code, box_number=box_number, model=model)
            self.devices[key] = dev
            LOGGER.info("[PDEG] physical device (passively detected): %s box %d", model, box_number)
            if device_code in SENSOR_DEVICE_CODES:
                area_num = b[1]  # best-effort
                ar = self._touch_area(area_num)
                ar.has_pir = True
            # Notify binary_sensor platform and persist — same as sign-on discovery
            for cb in self.on_new_device_cbs:
                cb()
            self.schedule_save()

    def _handle_signon_reply(self, device_code: int, box_number: int, b: bytes) -> None:
        """Handle a 0x5C opcode 0x00 Device Identify reply from a targeted sign-on request.

        b[4]=firmware major, b[5]=firmware minor.
        Updates device_online, _device_last_seen; creates device entry if new.
        """
        key   = (device_code, box_number)
        model = DEVICE_NAMES.get(device_code, f"Device 0x{device_code:02X}")
        fw_str = (f" fw v{b[4]:02d}.{b[5]:02d}" if len(b) >= 6 else "")

        is_new = key not in self.devices
        if is_new:
            self.devices[key] = PhysicalDevice(
                device_code=device_code, box_number=box_number, model=model
            )
            LOGGER.info("[Sign-on] discovered: %s  box %d%s", model, box_number, fw_str)
        else:
            LOGGER.debug("[Sign-on] reply:      %s  box %d%s", model, box_number, fw_str)

        was_online = self.device_online.get(key, False)
        self._device_last_seen[key] = time.monotonic()
        self.device_online[key] = True

        if is_new:
            for cb in self.on_new_device_cbs:
                cb()
            self.schedule_save()

        if not was_online:
            async_dispatcher_send(self.hass, signal_device(device_code, box_number), True)
            if not is_new:
                LOGGER.info("[Sign-on] back online: %s  box %d%s", model, box_number, fw_str)

    def _handle_signon(self, b: bytes) -> None:
        """Parse a 0xAC sign-on reply (System Builder / broadcast format).

        Frame layout:
          b[0]  = 0xAC  (SYNC_SIGNON)
          b[1]  = length indicator  (total bytes = (b[1]+1)*4)
          b[2]  = 0x81  (OP_SIGNON_REPLY_AC)
          b[3]  = device_code
          b[4]  = 0x00
          b[5]  = box_number
          b[6-11] = AA 55 55 01 00 00  (fixed marker)
          b[12] = firmware major
          b[13] = firmware minor
          ...

        Reuses _handle_signon_reply to update online state so both paths
        (our targeted 0x5C poll and System Builder's broadcast) work identically.
        """
        if len(b) < 6 or b[2] != OP_SIGNON_REPLY_AC:
            return

        device_code = b[3]
        box_number  = b[5]

        # Build a synthetic 6-byte buffer matching what _handle_signon_reply expects:
        # b[4]=fw_major, b[5]=fw_minor  (reuse b[12]/b[13] from the AC frame if present)
        fw_major = b[12] if len(b) >= 13 else 0
        fw_minor = b[13] if len(b) >= 14 else 0
        synthetic = bytes([0x5C, device_code, box_number, 0x00, fw_major, fw_minor, 0x00, 0x00])
        LOGGER.debug("[Sign-on] 0xAC reply → routing to signon_reply handler  dc=0x%02X box=%d",
                     device_code, box_number)
        self._handle_signon_reply(device_code, box_number, synthetic)

    # ── Periodic targeted sign-on polling ────────────────────────────────────

    async def _signon_loop(self) -> None:
        """Poll all known devices every signon_interval seconds.

        Sleeps in 30 s increments so that changes to self.signon_interval
        take effect within 30 s rather than waiting for the full sleep.
        """
        elapsed = 0
        while True:
            try:
                await asyncio.sleep(30)
                elapsed += 30
                if elapsed >= self.signon_interval:
                    elapsed = 0
                    if self.client.connected and self.devices:
                        LOGGER.info(
                            "[Coordinator] starting periodic sign-on poll (%d devices)",
                            len(self.devices),
                        )
                        asyncio.ensure_future(self._poll_all_devices())
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("[Coordinator] sign-on loop error: %s", exc)

    async def _poll_all_devices(self) -> None:
        """Send targeted sign-on requests to every known device; 3 retry rounds.

        Round flow:
          1. Send opcode 0x80 to each pending device (50 ms inter-frame gap).
          2. Wait SIGNON_RESPONSE_TIMEOUT seconds for their 0x5C opcode 0x00 replies.
          3. Devices that replied update _device_last_seen via _handle_signon_reply.
          4. Repeat up to SIGNON_RETRIES times for non-responders.
          5. Anything still silent after all rounds → marked offline.
        """
        if not self.devices:
            return

        pending: set[tuple[int, int]] = set(self.devices.keys())
        LOGGER.info("[Sign-on] polling %d device(s)", len(pending))

        for attempt in range(SIGNON_RETRIES):
            if not pending or not self.client.connected:
                break

            t0 = time.monotonic()
            for dc, bn in list(pending):
                if not self.client.connected:
                    return
                await self.client.request_device_signon(dc, bn)
                await asyncio.sleep(0.05)  # 50 ms gap between frames

            await asyncio.sleep(SIGNON_RESPONSE_TIMEOUT)

            # Check who replied (their _device_last_seen was updated after t0)
            pending = {
                k for k in pending
                if self._device_last_seen.get(k, 0) < t0
            }
            if pending:
                LOGGER.debug(
                    "[Sign-on] attempt %d/%d: %d device(s) no reply yet: %s",
                    attempt + 1, SIGNON_RETRIES, len(pending),
                    [f"0x{dc:02X}/box{bn}" for dc, bn in pending],
                )

        # Mark non-responders as offline
        for key in pending:
            if self.device_online.get(key, False):
                self.device_online[key] = False
                dc, bn = key
                dev   = self.devices.get(key)
                model = dev.model if dev else f"0x{dc:02X}"
                LOGGER.warning(
                    "[Sign-on] OFFLINE (no reply after %d attempts): %s  box %d",
                    SIGNON_RETRIES, model, bn,
                )
                async_dispatcher_send(self.hass, signal_device(dc, bn), False)

        online_count  = sum(1 for v in self.device_online.values() if v)
        offline_count = sum(1 for v in self.device_online.values() if not v)
        LOGGER.info("[Sign-on] poll complete — online: %d  offline: %d",
                    online_count, offline_count)

    # ── State helpers ─────────────────────────────────────────────────────────

    def _touch_area(self, area_num: int) -> AreaState:
        is_new = area_num not in self.areas
        if is_new:
            self.areas[area_num] = AreaState(area=area_num)
            LOGGER.debug("[Coordinator] new area: %d", area_num)
        ar = self.areas[area_num]
        if is_new:
            for cb in self.on_new_area_cbs:
                cb()
            self.schedule_save()
        return ar

    def _touch_channel(self, ar: AreaState, ch0: int) -> ChannelState:
        is_new = ch0 not in ar.channels
        if is_new:
            ar.channels[ch0] = ChannelState(area=ar.area, ch0=ch0)
            LOGGER.debug("[Coordinator] new channel: A%d Ch%d", ar.area, ch0 + 1)
        ch = ar.channels[ch0]
        if is_new:
            for cb in self.on_new_channel_cbs:
                cb()
            self.schedule_save()
        return ch

    @staticmethod
    def _decode_temp(hi: int, lo: int) -> float:
        """Decode Dynalite Q2 temperature (opcode 0xF6): signed int16, °C × 4."""
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 0x10000
        return raw / 4.0

    @staticmethod
    def _decode_temp_4a(integer_byte: int, hundredths_byte: int) -> float:
        """Decode Dynalite 0x4A temperature: b[4]=signed integer °C, b[5]=hundredths."""
        integer_part = integer_byte if integer_byte < 128 else integer_byte - 256
        frac = hundredths_byte / 100.0
        return integer_part + frac if integer_part >= 0 else integer_part - frac

    # ── Cross-area HVAC forwarding ────────────────────────────────────────────

    def _forward_hvac_signal(self, control_area_num: int) -> None:
        """Dispatch signal_area for any HVAC area whose mode/fan is controlled
        from a *different* area (control_area_num).  Same-area cases are
        already covered by the regular signal_area dispatch."""
        for hvac_ar in self.areas.values():
            if hvac_ar.area == control_area_num:
                continue
            eff_mode = hvac_ar.hvac_mode_area or hvac_ar.area
            eff_fan  = hvac_ar.hvac_fan_area  or hvac_ar.area
            if eff_mode == control_area_num or eff_fan == control_area_num:
                async_dispatcher_send(self.hass, signal_area(hvac_ar.area), hvac_ar)

    # ── Command passthrough (called by HA entities) ───────────────────────────

    async def cmd_select_preset(self, area: int, preset1: int) -> None:
        ar   = self.areas.get(area)
        fade = ar.fade_tenths if ar else 20
        await self.client.select_preset(area, preset1, fade)
        # Optimistic: update ar.preset0 immediately so HA shows the new
        # preset/mode before the bus round-trip comes back.
        if ar is not None:
            ar.preset0 = preset1 - 1
            async_dispatcher_send(self.hass, signal_area(area), ar)
            # Notify any HVAC area that uses this area as its mode/fan control area
            self._forward_hvac_signal(area)
        # Still request confirmation; the OP_PRESET_REPORT reply will also
        # trigger a channel-level poll via _poll_channels().
        await asyncio.sleep(0.1)
        await self.client.request_area_preset(area)

    async def _poll_single_channel(self, area: int, ch0: int) -> None:
        """Request the level of one specific channel after a short settle."""
        await asyncio.sleep(0.2)
        if self.client.connected:
            await self.client.request_level(area, ch0)

    async def _poll_channels(self, area: int) -> None:
        """Request the current level of every known channel in an area.

        Called whenever a preset report arrives (from any source).  We read the
        target level (b[4]) so results are valid even mid-fade — no need to wait
        for the fade to complete.  A short 0.2 s settle lets the bus process the
        preset command before we start asking for levels.
        """
        await asyncio.sleep(0.2)
        ar = self.areas.get(area)
        if not ar or not ar.channels:
            return
        LOGGER.debug(
            "[Coordinator] polling channels: A%d (%d channels)", area, len(ar.channels)
        )
        for ch0 in sorted(ar.channels):
            if self.client.connected:
                await self.client.request_level(area, ch0)
                await asyncio.sleep(0.05)

    async def cmd_set_level(
        self, area: int, ch0: int, pct: int, fade_tenths: int | None = None
    ) -> None:
        """Send a Recall/Fade-to-Level command.

        fade_tenths: override the fade time (0.1 s units).
                     If None, the area's configured fade is used.
                     Pass 0 explicitly for instant switching (e.g. covers).
        """
        ar = self.areas.get(area)
        if fade_tenths is None:
            fade_tenths = ar.fade_tenths if ar else 0
        LOGGER.debug("[Coordinator] cmd_set_level A%d Ch%d → %d%% fade=%.1fs",
                     area, ch0 + 1, pct, fade_tenths / 10)
        await self.client.set_level(area, ch0, pct, fade_tenths)
        # Optimistic: update channel state immediately so HA reflects the change
        # before the OP_LEVEL_REPORT confirmation arrives from the bus.
        if ar is not None:
            ch = self._touch_channel(ar, ch0)
            ch.pct   = pct
            ch.is_on = pct > 0
            async_dispatcher_send(self.hass, signal_channel(area, ch0), ch)
            # Refresh any HVAC climate entity whose mode/fan channel just changed.
            # Covers both same-area (hvac_mode_area==0) and cross-area configs.
            for hvac_ar in self.areas.values():
                eff_mode = hvac_ar.hvac_mode_area or hvac_ar.area
                eff_fan  = hvac_ar.hvac_fan_area  or hvac_ar.area
                if (
                    (hvac_ar.hvac_mode_method == "channel" and eff_mode == area and hvac_ar.hvac_mode_ch0 == ch0) or
                    (hvac_ar.hvac_fan_method  == "channel" and eff_fan  == area and hvac_ar.hvac_fan_ch0  == ch0)
                ):
                    async_dispatcher_send(self.hass, signal_area(hvac_ar.area), hvac_ar)

    async def async_scan(
        self,
        area_min: int = 2,
        area_max: int = 20,
        channel_count: int = 8,
        delay_ms: int = 50,
    ) -> None:
        """Active bus scan — poll areas and channels to trigger auto-discovery.

        Sends request_area_preset to each area, then request_level to each
        channel within that area.  Devices that exist reply; the replies are
        processed by _handle_logical() which creates entities automatically.

        Args:
            area_min:      first area to poll (1-based)
            area_max:      last area to poll  (1-based, inclusive)
            channel_count: channels to probe per area (0 to channel_count-1)
            delay_ms:      inter-frame delay in ms (avoid flooding the bus)
        """
        delay = delay_ms / 1000.0
        total_areas = area_max - area_min + 1
        LOGGER.info(
            "[Scan] starting: areas %d-%d, %d channels each, %d ms delay",
            area_min, area_max, channel_count, delay_ms,
        )
        for area_num in range(area_min, area_max + 1):
            if not self.client.connected:
                LOGGER.warning("[Scan] aborted — connection lost")
                return
            await self.client.request_area_preset(area_num)
            await asyncio.sleep(delay)
            for ch0 in range(channel_count):
                if not self.client.connected:
                    return
                await self.client.request_level(area_num, ch0)
                await asyncio.sleep(delay)

        LOGGER.info("[Scan] complete — scanned %d areas", total_areas)

    async def cmd_program_current_preset(self, area: int) -> None:
        """Save current channel levels to the active preset."""
        await self.client.program_current_preset(area)

    async def cmd_program_defined_preset(self, area: int, preset0: int) -> None:
        """Save current channel levels to a specific preset (0-origin)."""
        await self.client.program_defined_preset(area, preset0)

    async def cmd_save_current_preset(self, area: int) -> None:
        """Save the current preset number to NV memory."""
        await self.client.save_current_preset(area)

    async def cmd_restore_saved_preset(self, area: int) -> None:
        """Restore the saved preset using the area's configured fade."""
        ar = self.areas.get(area)
        fade = ar.fade_tenths if ar else 20
        await self.client.restore_saved_preset(area, fade)

    async def cmd_set_setpoint(self, area: int, temp_c: float) -> None:
        """Send a setpoint write command to the bus and update local state optimistically."""
        await self.client.set_setpoint(area, temp_c)
        ar = self.areas.get(area)
        if ar:
            ar.has_setpt = True
            ar.setpt_c   = temp_c
            from homeassistant.helpers.dispatcher import async_dispatcher_send  # noqa: PLC0415
            async_dispatcher_send(self.hass, signal_area(area), ar)

    async def cmd_occupancy_enable(self, area: int) -> None:
        await self.client.occupancy_enable(area)
        ar = self._touch_area(area)
        ar.occ_enabled = True
        async_dispatcher_send(self.hass, signal_area(area), ar)

    async def cmd_occupancy_disable(self, area: int) -> None:
        await self.client.occupancy_disable(area)
        ar = self._touch_area(area)
        ar.occ_enabled = False
        async_dispatcher_send(self.hass, signal_area(area), ar)
