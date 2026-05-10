"""Async TCP client for Philips Dynalite PDEG.

Connects to the PDEG TCP port, reads 8-byte logical (0x1C) frames from the
bus, and dispatches them to a registered callback.  Also exposes send helpers
for every command the integration needs.

Frame layout (logical / 0x1C):
  b[0] = 0x1C  sync
  b[1] = area  (1-255)
  b[2] = data1 (channel 0-based, or preset 0-based depending on opcode)
  b[3] = opcode
  b[4] = data2
  b[5] = data3
  b[6] = join  (0xFF = all devices)
  b[7] = checksum  = -(sum b[0..6]) & 0xFF
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from .const import (
    FRAME_LEN,
    LOGGER,
    OP_FADE_TO_LEVEL,
    OP_SET_SETPOINT,
    OP_PROGRAM_CURR_PRESET,
    OP_PROGRAM_DEF_PRESET,
    OP_RESTORE_SAVED_PRESET,
    OP_SAVE_CURR_PRESET,
    RECONNECT_DELAY,
    SYNC_LOGICAL,
    SYNC_PHYSICAL,
    SYNC_SIGNON,
    pct_to_dynalite,
)


class DynaliteClient:
    """Manages a persistent TCP connection to the PDEG."""

    def __init__(
        self,
        host: str,
        port: int,
        frame_callback: Callable[[bytes], Coroutine[Any, Any, None]],
        connection_callback: Callable[[bool], Coroutine[Any, Any, None]],
    ) -> None:
        self._host = host
        self._port = port
        self._frame_cb = frame_callback
        self._conn_cb = connection_callback
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._running = False
        self._task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the connection loop (call once from coordinator.async_setup)."""
        self._running = True
        self._task = asyncio.ensure_future(self._connection_loop())

    async def stop(self) -> None:
        """Disconnect and stop the loop."""
        self._running = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if self._task:
            self._task.cancel()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # ── Command helpers ───────────────────────────────────────────────────────

    async def select_preset(
        self, area: int, preset1: int, fade_tenths: int = 20
    ) -> None:
        """Select a preset (1-based) on an area with optional fade (0.1 s units).

        DyNet1 supports two preset-per-bank encodings:
          Standard  (8 per bank): opcodes 0x00-0x07 for presets 1-8 within the bank.
          Alternate (4 per half): opcodes 0x00-0x03 for presets 1-4,
                                  opcodes 0x0A-0x0D for presets 5-8 within the bank.
        We use the alternate encoding (matches observed bus traffic on 4-preset systems).

          b[0] = 0x1C  sync
          b[1] = area
          b[2] = Fade Time Low  (0.02 s units — fade_tenths × 5)
          b[3] = opcode  (see encoding above)
          b[4] = Fade Time High (MSB of 16-bit fade; 0x00 for fades ≤ 5.1 s)
          b[5] = Preset Bank    = (preset - 1) // 8  → 0x00 for P1-8, 0x01 for P9-16, …
          b[6] = 0xFF  (join = broadcast)
          b[7] = checksum
        """
        p0             = preset1 - 1
        bank           = p0 // 8               # 0x00=P1-8, 0x01=P9-16, …
        offset         = p0 % 8                # 0-7 within the bank
        # Alternate encoding: offsets 4-7 (presets 5-8) use opcodes 0x0A-0x0D
        opcode         = offset if offset <= 3 else offset + 6
        steps   = fade_tenths * 5              # 0.1 s → 0.02 s units (×5)
        fade_lo = steps & 0xFF
        fade_hi = (steps >> 8) & 0xFF
        frame   = bytes([SYNC_LOGICAL, area, fade_lo, opcode, fade_hi, bank, 0xFF, 0x00])
        LOGGER.debug(
            "[TX] select_preset A%d P%d  opcode=0x%02X bank=0x%02X fade_lo=0x%02X fade_hi=0x%02X  frame: %s",
            area, preset1, opcode, bank, fade_lo, fade_hi, frame.hex(" ").upper(),
        )
        await self._send(frame)

    async def request_level(self, area: int, ch0: int) -> None:
        """Request the current level of a channel (triggers a level report).

        DyNet1 opcode 0x61 — b[2] = channel number (0-origin).
        """
        frame = bytes([SYNC_LOGICAL, area, ch0, 0x61, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.debug("[TX] request_level A%d Ch%d", area, ch0 + 1)
        await self._send(frame)

    async def set_level(
        self, area: int, ch0: int, pct: int, fade_tenths: int = 0
    ) -> None:
        """Set a channel to a brightness percentage (0-100).

        DyNet1 opcode 0x71 "Ramp Channel to Level":
          b[0]=0x1C  b[1]=area  b[2]=ch(0-origin)  b[3]=0x71
          b[4]=level  (0x01=100% full on, 0xFF=0% off)
          b[5]=ramp_rate  (100 ms steps — fade_tenths maps directly)
          b[6]=0xFF (join = broadcast)  b[7]=checksum
        """
        level     = pct_to_dynalite(pct)
        ramp_rate = min(fade_tenths, 0xFF)   # already in 100 ms steps

        frame = bytes([SYNC_LOGICAL, area, ch0, OP_FADE_TO_LEVEL, level, ramp_rate, 0xFF, 0x00])
        LOGGER.debug("[TX] set_level A%d Ch%d → %d%% (level=0x%02X ramp_rate=0x%02X)",
                     area, ch0 + 1, pct, level, ramp_rate)
        await self._send(frame)

    async def occupancy_enable(self, area: int) -> None:
        """Resume occupancy detection for an area.

        DyNet1 opcode 0x31, b[2]=0xFF (all channels), b[5]=0x01 (resume).
        Frame: 1C [area] FF 31 00 01 FF [cs]
        """
        frame = bytes([SYNC_LOGICAL, area, 0xFF, 0x31, 0x00, 0x01, 0xFF, 0x00])
        LOGGER.debug("[TX] occupancy_enable (resume) A%d  frame: %s", area, frame.hex(" ").upper())
        await self._send(frame)

    async def occupancy_disable(self, area: int) -> None:
        """Suspend occupancy detection for an area.

        DyNet1 opcode 0x31, b[2]=0xFF (all channels), b[5]=0x00 (suspend).
        Frame: 1C [area] FF 31 00 00 FF [cs]
        """
        frame = bytes([SYNC_LOGICAL, area, 0xFF, 0x31, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.debug("[TX] occupancy_disable (suspend) A%d  frame: %s", area, frame.hex(" ").upper())
        await self._send(frame)

    async def request_area_preset(self, area: int) -> None:
        """Request the currently active preset for an area.

        DyNet1 opcode 0x63 — Request Current Preset.
        """
        frame = bytes([SYNC_LOGICAL, area, 0x00, 0x63, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.debug("[TX] request_area_preset A%d", area)
        await self._send(frame)

    async def set_setpoint(self, area: int, temp_c: float) -> None:
        """Set the HVAC temperature setpoint for an area.

        DyNet1 opcode 0x48 — Set Setpoint:
          b[0]=0x1C  b[1]=area  b[2]=0x07  b[3]=0x48
          b[4]=q_hi  b[5]=q_lo  (signed int16, °C × 4 Q2 format)
          b[6]=0xFF  b[7]=checksum
        """
        import struct  # noqa: PLC0415
        q = int(round(temp_c * 4.0))
        q_bytes = struct.pack(">h", q)   # big-endian signed int16
        frame = bytes([SYNC_LOGICAL, area, 0x07, OP_SET_SETPOINT, q_bytes[0], q_bytes[1], 0xFF, 0x00])
        LOGGER.debug("[TX] set_setpoint A%d %.2f°C  q=%d  frame: %s",
                     area, temp_c, q, frame.hex(" ").upper())
        await self._send(frame)

    async def program_current_preset(self, area: int) -> None:
        """Save current channel levels to the currently active preset (opcode 0x08)."""
        frame = bytes([SYNC_LOGICAL, area, 0x00, OP_PROGRAM_CURR_PRESET, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.info("[TX] program_current_preset A%d", area)
        await self._send(frame)

    async def program_defined_preset(self, area: int, preset0: int) -> None:
        """Save current channel levels to a specific preset (opcode 0x09).

        preset0: 0-origin preset index.
        """
        frame = bytes([SYNC_LOGICAL, area, preset0, OP_PROGRAM_DEF_PRESET, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.info("[TX] program_defined_preset A%d preset %d", area, preset0 + 1)
        await self._send(frame)

    async def save_current_preset(self, area: int) -> None:
        """Save the current preset NUMBER to NV memory (opcode 0x66)."""
        frame = bytes([SYNC_LOGICAL, area, 0x00, OP_SAVE_CURR_PRESET, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.info("[TX] save_current_preset A%d", area)
        await self._send(frame)

    async def restore_saved_preset(self, area: int, fade_tenths: int = 20) -> None:
        """Restore the saved preset with a fade time (opcode 0x67).

        Fade is a 16-bit value in 20 ms steps stored as lo/hi bytes:
          b[2] = fade_lo, b[4] = fade_hi.
        fade_tenths → convert to 20 ms steps: steps = fade_tenths * 5.
        """
        steps    = min(fade_tenths * 5, 0xFFFF)
        fade_lo  = steps & 0xFF
        fade_hi  = (steps >> 8) & 0xFF
        frame = bytes([SYNC_LOGICAL, area, fade_lo, OP_RESTORE_SAVED_PRESET, fade_hi, 0x00, 0xFF, 0x00])
        LOGGER.info("[TX] restore_saved_preset A%d fade=%ds", area, fade_tenths / 10)
        await self._send(frame)

    async def request_motion_status(self, device_code: int, box_number: int) -> None:
        """Request current motion status from a physical device (opcode 0xB7, sub 0x0D).

        DyNet1 physical frame:
          b[0]=0x5C  b[1]=device_code  b[2]=box_number  b[3]=0xB7
          b[4]=0x0D  b[5]=0x00  b[6]=0x00  b[7]=checksum

        The device replies with a 0x5C opcode 0xB8 b[4]=0x0D frame:
          b[5]/b[6]=0xFF/0xFF → motion detected, 0x00/0x00 → vacant.
        """
        frame = bytes([SYNC_PHYSICAL, device_code, box_number, 0xB7, 0x0D, 0x00, 0x00, 0x00])
        LOGGER.debug("[TX] request_motion_status  dc=0x%02X box=%d", device_code, box_number)
        await self._send(frame)

    async def request_device_signon(self, device_code: int, box_number: int) -> None:
        """Send a targeted "Request Firmware Version" (opcode 0x80) to one device.

        DyNet1 physical frame:
          b[0]=0x5C  b[1]=device_code  b[2]=box_number  b[3]=0x80
          b[4]=0x00  b[5]=0x00  b[6]=0x00  b[7]=checksum

        The device replies with a 0x5C opcode 0x00 "Device Identify" frame containing
        its firmware version.  No reply within SIGNON_RESPONSE_TIMEOUT → mark offline.
        """
        frame = bytes([SYNC_PHYSICAL, device_code, box_number, 0x80, 0x00, 0x00, 0x00, 0x00])
        LOGGER.debug("[TX] request_device_signon  dc=0x%02X box=%d", device_code, box_number)
        await self._send(frame)

    async def request_signon(self) -> None:
        """Broadcast "Request Device Status / Do D2 Signon" (0x5C opcode 0x40 sub 0x0A).

        This is the correct DyNet1 physical frame that triggers every device on
        the RS485 bus to reply with a Device Identify (0x5C opcode 0x00) frame.
        The PDEG forwards those replies to TCP clients as 0xAC sign-on frames.

        Frame layout (physical / 0x5C):
          b[0] = 0x5C  sync
          b[1] = 0xFF  device code broadcast (all models)
          b[2] = 0xFF  box number broadcast  (all boxes)
          b[3] = 0x40  opcode = Request Device Status
          b[4] = 0x00  Data 1 (unused)
          b[5] = 0x00  Data 2 (unused)
          b[6] = 0x0A  Data 3 = sub-opcode "Do D2 Signon"
          b[7] = checksum
        """
        frame = bytes([SYNC_PHYSICAL, 0xFF, 0xFF, 0x40, 0x00, 0x00, 0x0A, 0x00])
        LOGGER.info("[TX] request_signon  frame: %s", frame.hex(" ").upper())
        await self._send(frame)

    async def stop_channel(self, area: int, ch0: int) -> None:
        """Stop a running channel (used for covers/curtains).

        DyNet1 opcode 0x76 — Stop Fade. b[2] = channel (0-origin).
        """
        frame = bytes([SYNC_LOGICAL, area, ch0, 0x76, 0x00, 0x00, 0xFF, 0x00])
        LOGGER.info("[TX] stop_channel A%d Ch%d  frame: %s", area, ch0 + 1, frame.hex(" ").upper())
        await self._send(frame)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _send(self, frame: bytes) -> None:
        """Compute checksum and write frame to TCP socket."""
        if not self.connected:
            LOGGER.warning("[PDEG] send skipped — not connected  raw=%s", frame.hex(" ").upper())
            return
        # Checksum: -(sum of bytes 0-6) & 0xFF  (handles variable frame length)
        payload = frame[:-1]  # all but checksum placeholder
        cs = (-sum(payload)) & 0xFF
        frame = payload + bytes([cs])
        try:
            assert self._writer is not None
            self._writer.write(frame)
            await self._writer.drain()
            LOGGER.debug("[PDEG] TX %s", frame.hex(" ").upper())
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("[PDEG] send error: %s", exc)
            await self._handle_disconnect()

    async def _connection_loop(self) -> None:
        """Keep trying to connect; re-connect on any error."""
        while self._running:
            try:
                LOGGER.info("[PDEG] connecting to %s:%d …", self._host, self._port)
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=10,
                )
                LOGGER.info("[PDEG] connected")
                await self._conn_cb(True)
                await self._read_loop()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("[PDEG] connection failed: %s", exc)
            finally:
                self._writer = None
                self._reader = None

            await self._conn_cb(False)
            if self._running:
                LOGGER.info("[PDEG] reconnecting in %ds …", RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def _read_loop(self) -> None:
        """Read frames from the TCP stream and dispatch them."""
        assert self._reader is not None
        buf = bytearray()
        while self._running:
            try:
                chunk = await self._reader.read(256)
                if not chunk:
                    LOGGER.warning("[PDEG] connection closed by remote")
                    return
                buf.extend(chunk)

                # consume complete frames from the buffer
                while len(buf) >= 2:
                    sync = buf[0]

                    if sync in (SYNC_LOGICAL, SYNC_PHYSICAL):
                        # Fixed 8-byte logical / physical frame
                        if len(buf) < FRAME_LEN:
                            break
                        frame = bytes(buf[:FRAME_LEN])
                        buf = buf[FRAME_LEN:]
                        if self._valid_checksum(frame):
                            LOGGER.debug("[PDEG] RX %s", frame.hex(" ").upper())
                            await self._frame_cb(frame)
                        else:
                            LOGGER.warning("[PDEG] bad checksum, discarding %s",
                                           frame.hex(" ").upper())

                    elif sync == SYNC_SIGNON:
                        # Variable-length sign-on frame: total = (b[1]+1)*4 bytes
                        frame_len = (buf[1] + 1) * 4
                        if len(buf) < frame_len:
                            break
                        frame = bytes(buf[:frame_len])
                        buf = buf[frame_len:]
                        LOGGER.debug("[PDEG] RX sign-on %s", frame.hex(" ").upper())
                        await self._frame_cb(frame)

                    else:
                        # Unknown byte — skip forward to the next known sync
                        known = {SYNC_LOGICAL, SYNC_PHYSICAL, SYNC_SIGNON}
                        idx = next(
                            (i for i in range(1, len(buf)) if buf[i] in known),
                            None,
                        )
                        if idx is None:
                            buf.clear()
                        else:
                            buf = buf[idx:]

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("[PDEG] read error: %s", exc)
                return

    @staticmethod
    def _valid_checksum(frame: bytes) -> bool:
        return (-sum(frame[:7])) & 0xFF == frame[7]

    async def _handle_disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
            except Exception:  # noqa: BLE001
                pass
        self._writer = None
        self._reader = None
