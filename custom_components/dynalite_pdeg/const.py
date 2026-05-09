"""Constants for Dynalite PDEG integration."""
import logging

DOMAIN = "dynalite_pdeg"
LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 12345
DEFAULT_NAME = "Dynalite"
RECONNECT_DELAY          = 5      # seconds between reconnect attempts
SIGNON_INTERVAL          = 3600   # default seconds between targeted sign-on polls (configurable)
SIGNON_RESPONSE_TIMEOUT  = 5      # seconds to wait per attempt for a device reply
SIGNON_RETRIES           = 3      # number of attempts before marking a device offline
FRAME_LEN = 8

# ── Sync bytes ────────────────────────────────────────────────────────────────
SYNC_LOGICAL  = 0x1C
SYNC_PHYSICAL = 0x5C
SYNC_SIGNON   = 0xAC   # Variable-length sign-on / device discovery frames

# ── Sign-on opcodes ───────────────────────────────────────────────────────────
# TX (targeted):  5C [dc] [bn] 0x80 00 00 00 [cs]         → Request Firmware Version
# RX (0x5C):      5C [dc] [bn] 0x00 [fw_maj] [fw_min] [boot] [cs]  → Device Identify reply
# RX (0xAC):      AC [len] 0x81 [dc] 00 [bn] AA 55 …      → Reply Device Signon (System Builder format)
OP_SIGNON_REQUEST  = 0x80   # b[3] of TX 0x5C frame — Request Firmware Version
OP_SIGNON_REPLY    = 0x00   # b[3] of RX 0x5C frame — Device Identify reply (our targeted poll)
OP_SIGNON_REPLY_AC = 0x81   # b[2] of RX 0xAC frame — Reply Device Signon (System Builder / broadcast)

# ── Incoming opcodes (bus → integration) ─────────────────────────────────────
OP_LEVEL_REPORT    = 0x60   # Report Channel Level;  b[2]=ch(0-origin), b[4]=target level, b[5]=current level
OP_REQUEST_LEVEL   = 0x61   # Request Channel Level  (outgoing, but echo may arrive as 0x61)
OP_PRESET_REPORT   = 0x62   # Report Current Preset; b[2]=preset(0-origin)
OP_LEVEL_RESPONSE  = 0x61   # alias — same opcode as request (echo back) kept for compat
OP_OCCUPANCY       = 0x31   # PIR occupancy;         b[5]=1 occupied/0 vacant
OP_MOTION_DETECT   = 0x2E   # Motion trigger (instantaneous); b[2]=channel (0xFF=all)
OP_OCC_DISABLE     = 0x3A   # occupancy detection disabled for area
OP_OCC_ENABLE      = 0x3B   # occupancy detection enabled  for area
OP_TEMP_REPORT     = 0x4A   # actual temperature;    b[4]=integer °C (signed), b[5]=hundredths
OP_TEMP_REPORT_ALT = 0xF6   # alternate temp opcode (Q2 format); kept for compat
OP_SETPOINT_REPORT = 0x76   # setpoint temperature;  b[4]=hi, b[5]=lo (Q2)
OP_LUX_REPORT      = 0xB8   # ambient light level;   b[6]=lux (physical frame, 0x5C sync)

# ── Outgoing opcodes (integration → bus) ─────────────────────────────────────
# Select preset: opcode = (preset1 - 1) for presets 1-8 (bank 0)
#                opcode = 0x08 + (preset1 - 9) for presets 9-16 (bank 1)
OP_REQUEST_PRESET       = 0x63   # Request Current Preset
OP_SET_SETPOINT         = 0x48   # Set HVAC setpoint: b[4]=hi, b[5]=lo (°C × 4 / Q2, signed int16)
OP_FADE_TO_LEVEL        = 0x71   # Ramp Channel to Level: b[2]=ch(0-origin), b[4]=level(0x01=100%,0xFF=0%), b[5]=ramp_rate(100ms steps)
OP_PROGRAM_CURR_PRESET  = 0x08   # Program Current Preset: save channel levels to active preset
OP_PROGRAM_DEF_PRESET   = 0x09   # Program Defined Preset: save channel levels to b[2] preset (0-origin)
OP_SAVE_CURR_PRESET     = 0x66   # Save Current Preset number to NV memory
OP_RESTORE_SAVED_PRESET = 0x67   # Restore Saved Preset: b[2]=fade_lo, b[4]=fade_hi (16-bit, 20ms steps)

# ── Dynalite level encoding ───────────────────────────────────────────────────
# On the bus: 0x01 = full brightness (100%), 0xFF = off (0%)  — NOT 0x00!
# In HA / this integration: 0 = off, 100 = full  (normal percentage scale)
def pct_to_dynalite(pct: int) -> int:
    """Convert 0-100 % to Dynalite wire level (0x01=100%, 0xFF=0%)."""
    if pct <= 0:
        return 0xFF
    if pct >= 100:
        return 0x01
    return max(1, round(255 - pct * 254 / 100))

def dynalite_to_pct(level: int) -> int:
    """Convert Dynalite wire level (0x01=100%, 0xFF=0%) to 0-100 %."""
    if level <= 0x01:
        return 100
    if level >= 0xFF:
        return 0
    return round((255 - level) * 100 / 254)

def ha_brightness_to_pct(brightness: int) -> int:
    """Convert HA 0-255 brightness to 0-100 %."""
    return int(round(brightness * 100 / 255))

def pct_to_ha_brightness(pct: int) -> int:
    """Convert 0-100 % to HA 0-255 brightness."""
    return int(round(pct * 255 / 100))

# ── Dispatcher signal helpers ────────────────────────────────────────────────
def signal_channel(area: int, ch0: int) -> str:
    return f"{DOMAIN}_ch_{area}_{ch0}"

def signal_area(area: int) -> str:
    return f"{DOMAIN}_area_{area}"

def signal_connection() -> str:
    return f"{DOMAIN}_connected"

def signal_device(device_code: int, box_number: int) -> str:
    return f"{DOMAIN}_device_{device_code}_{box_number}"

def signal_lux(device_code: int, box_number: int) -> str:
    return f"{DOMAIN}_lux_{device_code}_{box_number}"

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_HOST       = "host"
CONF_PORT       = "port"
CONF_NAME       = "name"

# ── Platform list ────────────────────────────────────────────────────────────
from homeassistant.const import Platform  # noqa: E402
PLATFORMS = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.COVER,
    Platform.CLIMATE,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]

# ── Device type table (physical frame device codes) ──────────────────────────
DEVICE_NAMES: dict[int, str] = {
    0x08: "DALI Combo Controller",
    0x48: "D4 Dimmer",
    0x49: "D6 Dimmer",
    0x4C: "Relay Controller",
    0x4E: "Ethernet Load Controller",
    0x50: "D2 Dimmer",
    0x58: "Fan Coil Unit Controller",
    0x59: "Fan Coil Unit Controller v2",
    0x60: "D3 Dimmer",
    0x64: "DALI Multi-Master E",
    0x65: "DALI Multi-Master v2",
    0x66: "DMC Modular Controller",
    0x67: "DALI3 Multi-Master",
    0x68: "DALI2 Controller",
    0x69: "DALI Multi-Master",
    0x6A: "Avatar Device",
    0x6B: "Captivation",
    0x78: "OLED Panel",
    0x79: "Dynalite Touch Screen",
    0x80: "Universal Panel 9",
    0x91: "Slim Dim PWM Controller",
    0x92: "LED Controller",
    0x95: "Power over Ethernet Sensor",
    0xAD: "Wireless Area Controller",
    0xB1: "D3 Sensor",
    0xB2: "D4 Sensor",
    0xB3: "D5 Sensor",
    0xB8: "Temperature Sensor",
    0xBA: "System Manager",
    0xBD: "Wireless Gateway Pro",
    0xBE: "Ethernet Gateway Supervisor",
    0xBF: "DLLI Low Level Interface",
    0xC2: "DALI Controller",
    0xC3: "Ethernet Gateway Supervisor v2",
    0xC4: "DDNGV3",
    0xC9: "Time Clock",
    0xCF: "Touch Panel H8",
    0xD9: "BACnet Gateway",
    0xDA: "System Builder",
    0xDB: "Power over Ethernet Luminaire",
    0xDC: "Ethernet Gateway",
    0xDD: "D5 Dimmer",
    0xE3: "LMM Lon Gateway",
    0xE4: "KNX Gateway",
    0xF3: "Bridge H8",
    0xF4: "Bridge M16",
    0xF5: "Bridge 3 Port",
    0xF6: "Current Sensor",
    0xF9: "Multi-function Input Panel",
    0xFA: "Multi-function Input",
    0xFB: "Antumbra",
    0xFD: "Antumbra 2",
}

SENSOR_DEVICE_CODES = {0xB1, 0xB2, 0xB3}   # D3/D4/D5 sensors → auto-PIR
RELAY_DEVICE_CODES  = {0x4C, 0x4E}          # Relay controllers → on/off only
DIMMER_DEVICE_CODES = {0x48, 0x49, 0x50, 0x60, 0x64, 0x65, 0x66,
                        0x67, 0x68, 0x69, 0x91, 0x92, 0xDD}
