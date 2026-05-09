# Dynalite - Home Assistant Integration

A custom Home Assistant integration for **Philips Dynalite** lighting control systems, connecting through the **PDEG (Ethernet Gateway)** via the DyNet1 protocol over TCP.

---

## Overview

This integration bridges your Dynalite system directly into Home Assistant without any middleware. It connects to the PDEG gateway over a raw TCP socket, speaks DyNet1 natively, and exposes all your Dynalite areas and channels as standard HA entities - lights, switches, covers, climate, and more.

Configuration and device management are handled entirely through a **custom sidebar panel** built into the integration, so you rarely need to touch YAML or restart HA.

---

## Features

- **Full DyNet1 protocol** - frame parsing and generation for logical and physical bus messages
- **Live TCP connection** with automatic reconnect on drop
- **Multiple entity types** - dimmable lights, on/off lights, switches, covers/blinds, HVAC climate, preset selectors, scene buttons
- **PIR motion sensors** - enable per-area motion detection from Dynalite occupancy opcodes
- **Physical device discovery** - auto-discovers boxes/modules on the bus via sign-on frames
- **Per-device online/offline status** - devices go unavailable when they stop responding to sign-on polls
- **Custom sidebar panel** - full configuration UI without YAML, including XML import
- **System Builder XML import** - import areas/channels and physical devices directly from System Builder exports
- **Area scan** - interrogates the bus to discover channels automatically
- **Persistent storage** - all areas, channels, and devices survive HA restarts
- **Developer services** - raw frame injection, preset selection, level control

---

## Requirements

| Component | Details |
|---|---|
| Home Assistant | 2024.1 or later |
| Dynalite gateway | PDEG (Ethernet Gateway, device code `0xDC`) |
| Network | HA must be able to reach the PDEG on TCP port 50000 (default) |
| System Builder | Optional - used only for XML export/import |

---

## Installation

### HACS (recommended)

1. In HACS → **Integrations** → ⋮ menu → **Custom repositories**
2. Add `https://github.com/hollako/Dynalite-HA-Integration` as type **Integration**
3. Search for **Dynalite PDEG** and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/dynalite_pdeg` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Dynalite PDEG**
3. Fill in:
   - **Host** - IP address of the PDEG gateway (e.g. `192.168.1.100`)
   - **Port** - TCP port (default `50000`)
   - **Name** - display name shown in the sidebar (e.g. `PDEG GF`)
4. The integration tests the TCP connection before saving
5. On success the sidebar panel appears automatically

> To change the host, port, or name later: go to the integration card → **⋮ → Reconfigure**.

---

## Sidebar Panel

The integration registers a full-page sidebar panel with two tabs.

### Physical Tab

Manages the physical Dynalite hardware (boxes/modules) discovered on the bus.

| Element | Description |
|---|---|
| **Offline / Online sections** | Devices are split into two sections - offline devices appear at the top so problems are immediately visible |
| **Device card** | Shows model name, box number, device code, and last-seen time |
| **Online/Offline status** | Green left border = online, red = offline. The HA device card also reflects this |
| **📡 button** | Sends a targeted sign-on poll to that one device and refreshes its status after 6 s |
| **Save name** | Renames the device - updates both the coordinator and the HA device registry |
| **✕ button** | Deletes the device and removes its HA entity |
| **＋ Add Device** | Manually add a device by hex code and box number |
| **📂 Import XML** | Import physical devices from a System Builder Devices XML export |
| **📡 Send Sign-on** | Polls all known devices at once |
| **Sign-on interval** | Configures how often (in seconds) the integration auto-polls all devices. Range: 60 – 86400 s. Recommended ≥ 1800 s |

#### Sign-on / Device Discovery

The integration uses a **targeted sign-on protocol**:

- TX: `5C [device_code] [box_number] 0x80 00 00 00 [cs]` - Request Firmware Version
- RX: `5C [device_code] [box_number] 0x00 [fw_major] [fw_minor] [boot] [cs]` - Device Identify reply

Devices that do not reply after **3 attempts × 5 second timeout** are marked **offline**. The poll repeats automatically every `signon_interval` seconds (default 1 hour).

System Builder sign-on frames (`0xAC … 0x81 …`) are also accepted, so devices announce themselves when you click Sign-on in System Builder.

### Logical Tab

Manages the logical configuration - areas and channels that become HA entities.

| Column | Description |
|---|---|
| **Area #** | Dynalite area number (1 – 255) |
| **Name** | Friendly name shown in HA |
| **Fade (s)** | Default fade time in seconds |
| **Presets** | Number of presets for this area |
| **Area Type** | Lighting / Blinds / HVAC - determines which entities are created |
| **Channels** | Inline list of channels with name and type editors |
| **Actions** | Save, PIR toggle, Delete |

#### Area Types

| Type | Entities created |
|---|---|
| **Lighting** | `light` entities (dimmer or on/off depending on channel type) |
| **Blinds** | `cover` entities |
| **HVAC** | `climate` entities with temperature and setpoint sensors |

#### Channel Types

| Type | HA Entity | Description |
|---|---|---|
| `dimmer` | `light` | Dimmable light with brightness control |
| `onoff` | `light` | Non-dimmable on/off light (relay) |
| `switch` | `switch` | Generic switch entity |
| `cover` | `cover` | Cover / curtain - requires pairing an Up channel with a Down channel |

#### PIR Motion Sensors

Each area can have a **🔍 PIR** button in the Actions column:

- **Grey** - PIR disabled for this area
- **Green ✓** - PIR enabled; a `binary_sensor` motion entity exists for this area

When enabled, the motion sensor responds to Dynalite occupancy opcodes (`0x31`) automatically. Disabling removes the entity from HA.

#### Area Scan

The **⟳ Run Scan** button sends `Request Channel Level` frames across a configurable range of area/channel combinations and discovers which ones respond. Scan parameters (area min/max, channel count, delay) are adjustable via **Settings → Integrations → Dynalite PDEG → Configure**.

---

## XML Import (System Builder)

System Builder can export two types of XML files. The panel accepts both.

### Logical XML (`LogicalExport`)

Contains area names, IDs, categories, preset counts, and channel details.

**How to export from System Builder:**
1. Right-click your project → **Export → Logical**
2. Save the `.xml` file

**How to import:**
1. Open the integration panel → **Logical tab**
2. Click **📂 Import XML** → select the file
3. A preview table appears showing all areas with checkboxes
   - Areas that already exist are flagged **EXISTS** and pre-unchecked
   - New areas are pre-checked
4. Tick **Overwrite existing** if you want to update already-configured areas
5. Click **📥 Import Selected**

Category mapping from System Builder to HA area type:

| System Builder category | HA area type |
|---|---|
| Lighting | light |
| HVAC | hvac |
| Custom | blind (curtains) |

### Devices XML (`DeviceExport`)

Contains physical device codes (decimal), box numbers, names, and models.

**How to import:**
1. Open the integration panel → **Physical tab**
2. Click **📂 Import XML** → select the file
3. Same preview + checkbox workflow as Logical import
4. Existing devices (same code + box) are flagged **EXISTS**

> **Note:** Device codes in the XML are decimal (e.g. `220` = `0xDC`). The parser handles the conversion automatically.

---

## Entities Created

### Per channel (Logical areas)

| Channel type | Platform | Entity ID pattern |
|---|---|---|
| dimmer | `light` | `light.{area_name}_{channel_name}` |
| onoff | `light` | `light.{area_name}_{channel_name}` |
| switch | `switch` | `switch.{area_name}_{channel_name}` |
| cover | `cover` | `cover.{area_name}_{channel_name}` |

### Per area

| Feature | Platform | Entity |
|---|---|---|
| Preset selector | `select` | Active preset (1 – N) |
| Scene buttons | `button` | One button per preset |
| PIR motion | `binary_sensor` | Occupied / Clear |
| Temperature | `sensor` | Actual temperature (HVAC areas) |
| Setpoint | `sensor` | Target temperature (HVAC areas) |
| Climate control | `climate` | Full HVAC entity |

### Per physical device

Each discovered physical box gets its own **HA device** entry (linked to the gateway via `via_device`), containing a hidden diagnostic connectivity entity. The device card shows **Unavailable** in HA when the device stops responding to sign-on polls.

### Gateway device

A single **Dynalite Gateway** device is registered, representing the PDEG itself. All physical box devices appear as sub-devices under it.

---

## Services

Available under **Developer Tools → Actions**.

### `dynalite_pdeg.scan`

Scan a range of areas and channels on the bus to discover active channels.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `area_min` | int | 2 | First area to scan |
| `area_max` | int | 20 | Last area to scan |
| `channel_count` | int | 8 | Channels per area to probe |
| `delay_ms` | int | 50 | Delay between frames (ms) |

### `dynalite_pdeg.select_preset`

Activate a preset on any area.

| Parameter | Type | Description |
|---|---|---|
| `area` | int | Area number (1 – 255) |
| `preset` | int | Preset number (1 – 255) |

### `dynalite_pdeg.set_level`

Set a specific channel to a brightness level.

| Parameter | Type | Description |
|---|---|---|
| `area` | int | Area number (1 – 255) |
| `channel` | int | Channel number 0-based (0 – 63) |
| `level` | int | Brightness 0 – 100 % |

### `dynalite_pdeg.send_raw_frame`

Send a raw DyNet1 frame directly to the bus. Useful for testing and protocol development.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `frame` | string | - | Hex bytes, space-separated or compact (e.g. `5C DC 01 80 00 00 00 00`) |
| `compute_checksum` | bool | `true` | Replace the last byte with the correct checksum |

Example - send a targeted sign-on request to device `0xDC` box `1`:
```yaml
service: dynalite_pdeg.send_raw_frame
data:
  frame: "5C DC 01 80 00 00 00 00"
  compute_checksum: true
```

---

## DyNet1 Protocol Reference

### Frame structure (standard 8-byte)

```
[SYNC] [AREA] [DATA1] [OPCODE] [DATA2] [DATA3] [JOIN] [CHECKSUM]
```

- **Logical frame** - SYNC = `0x1C`
- **Physical frame** - SYNC = `0x5C`
- **Sign-on frame** - SYNC = `0xAC` (variable length)
- **Checksum** = `(-sum(bytes[0..6])) & 0xFF`

### Key opcodes

| Opcode | Direction | Description |
|---|---|---|
| `0x80` | TX | Request Firmware Version (targeted sign-on) |
| `0x00` | RX | Device Identify reply |
| `0x81` (AC frame) | RX | Reply Device Signon (System Builder) |
| `0x60` | RX | Report Channel Level |
| `0x62` | RX | Report Current Preset |
| `0x31` | RX | PIR Occupancy (b[5]: 1=occupied, 0=vacant) |
| `0x71` | TX | Fade to Level |
| `0x63` | TX | Request Current Preset |
| `0xF6` | RX | Temperature Report |
| `0x76` | RX | Setpoint Report |

### Level encoding

Dynalite uses an **inverted** level scale on the wire:

| Wire value | Brightness |
|---|---|
| `0x01` | 100% (full on) |
| `0xFF` | 0% (off) |

The integration converts transparently - HA always sees 0 – 100 %.

---

## Project Structure

```
custom_components/dynalite_pdeg/
├── __init__.py          - Integration setup, panel registration, device registry
├── const.py             - Constants, opcodes, device code table, encoding helpers
├── coordinator.py       - Core state machine: frame parsing, area/channel/device state
├── dynalite_client.py   - Async TCP client with auto-reconnect
├── config_flow.py       - UI setup flow + options flow (scan settings, area/channel management)
├── storage.py           - Persistent JSON storage (survives HA restarts)
├── websocket.py         - WebSocket API commands used by the panel
├── services.py          - HA service registrations (scan, preset, level, raw frame)
├── xml_parser.py        - System Builder XML parser (Logical + Devices export formats)
├── entity.py            - Base entity classes
├── binary_sensor.py     - Motion sensors (PIR) + device connectivity
├── light.py             - Dimmable and on/off light entities
├── switch.py            - Switch entities
├── cover.py             - Cover/curtain entities
├── climate.py           - HVAC climate entities
├── sensor.py            - Temperature and setpoint sensors
├── select.py            - Preset selector entities
├── button.py            - Scene/preset button entities
└── panel/
    └── dynalite-config-panel.js  - Custom sidebar panel (vanilla JS web component)
```

---

## Troubleshooting

**Integration shows "Disconnected"**
- Check that the PDEG IP and port are correct and reachable from HA
- Verify no firewall is blocking TCP port 12345
- The integration reconnects automatically every 5 seconds

**Devices not appearing**
- Click **📡 Send Sign-on** in the Physical tab to trigger discovery
- Or click the 📡 button on individual device cards to ping them
- Devices also announce themselves when you click Sign-on in System Builder

**Entities not created after adding an area**
- Make sure channels are added to the area with the correct type
- Changing a channel type triggers an automatic integration reload

**Motion sensor not updating**
- Ensure PIR is enabled for the area (green ✓ button in the Logical tab Actions column)
- Verify the physical sensor is sending occupancy frames on the correct area number

**XML import fails**
- Make sure you upload the correct file to the correct tab:
  - `LogicalExport` XML → Logical tab
  - `DeviceExport` XML → Physical tab
- The panel will warn you if you upload the wrong type

---

## License

MIT License - see [LICENSE](LICENSE) for details.
