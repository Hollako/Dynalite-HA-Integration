# Dynalite PDEG - Home Assistant Integration

A custom Home Assistant integration for **Philips Dynalite** lighting control systems, connecting through the **PDEG Ethernet Gateway**.

---

## Requirements

- Home Assistant 2024.1 or later
- Philips Dynalite PDEG (Ethernet Gateway) on your network
- HA must be able to reach the PDEG on TCP port 50000

---

## Installation

### HACS (recommended)

1. In HACS - **Integrations** - menu - **Custom repositories**
2. Add `https://github.com/hollako/Dynalite-HA-Integration` as type **Integration**
3. Search for **Dynalite PDEG** and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/dynalite_pdeg` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings - Devices & Services - Add Integration**
2. Search for **Dynalite PDEG**
3. Fill in:
   - **Host** - IP address of your PDEG (e.g. `192.168.1.100`)
   - **Port** - TCP port (default `50000`)
   - **Name** - a display name for this gateway (e.g. `Ground Floor PDEG`)
4. Click **Submit** - the integration will test the connection before saving
5. Once added, a new sidebar panel appears automatically

> To change the host, port, or name later: go to the integration card - **... - Reconfigure**.

---

## Sidebar Panel

After setup, a dedicated panel appears in the HA sidebar. It has two tabs.

### Physical Tab

Shows all the Dynalite hardware modules (boxes) discovered on the bus.

- **Offline devices** appear at the top in red, **Online** devices below in green
- Each device card shows the model, box number, device code, and last-seen time
- **📡 button** on a card - sends a sign-on poll to that specific device and refreshes its status
- **Save name** - give the device a custom name (updates the HA device registry too)
- **X button** - removes the device from the integration
- **+ Add Device** - manually add a device by its hex code and box number
- **📂 Import XML** - import devices from a System Builder Devices XML export
- **📡 Send Sign-on** - polls all known devices at once
- **Sign-on interval** - how often (in seconds) the integration automatically polls all devices

### Logical Tab

This is where you configure the areas and channels that become HA entities (lights, covers, climate, etc.).

| Column | Description |
|---|---|
| **Area #** | Dynalite area number (1-255) |
| **Name** | Friendly name shown in HA |
| **Fade (s)** | Default fade time in seconds |
| **Presets** | Number of presets for this area |
| **Area Type** | Lighting / Blinds / HVAC |
| **Channels** | Channels in this area with name and type |
| **Actions** | Save, PIR toggle, Delete |

#### Area Types

| Type | What gets created in HA |
|---|---|
| **Lighting** | Light entities (dimmable or on/off) |
| **Blinds** | Cover entities |
| **HVAC** | Climate entity with temperature sensors |

#### Channel Types

| Type | HA Entity |
|---|---|
| `dimmer` | Dimmable light |
| `onoff` | On/Off light (relay) |
| `switch` | Switch |
| `cover` | Cover / blind (requires pairing an Up and a Down channel) |

#### PIR Motion Sensors

Each area has a **PIR** button in the Actions column:
- **Grey** - PIR disabled
- **Green** - PIR enabled - a motion `binary_sensor` exists for this area

Enabling PIR automatically creates a motion sensor that responds to Dynalite occupancy messages from that area. Disabling it removes the entity.

#### Area Scan

The **Run Scan** button sends level requests across a range of area/channel combinations to discover which ones are active on the bus. Scan settings (area range, channel count, delay) can be adjusted via **Settings - Integrations - Dynalite PDEG - Configure**.

---

## XML Import

You can import your Dynalite configuration directly from **System Builder** exports - no need to enter areas and devices manually.

### Importing Areas (Logical Tab)

1. In System Builder: right-click your project - **Export - Logical** - save the `.xml` file
2. In the panel - **Logical tab** - click **📂 Import XML** and select the file
3. A preview appears with all areas listed and checkboxes
   - Areas already configured in HA are flagged **EXISTS** and pre-unchecked
   - New areas are pre-checked
4. Tick **Overwrite existing** if you want to update already-configured areas
5. Click **📥 Import Selected**

### Importing Devices (Physical Tab)

1. In System Builder: export your devices XML
2. In the panel - **Physical tab** - click **📂 Import XML** and select the file
3. Same preview and checkbox workflow as above

> Make sure to upload each file to the correct tab - the panel will warn you if you use the wrong one.

---

## Entities Created

Once areas and channels are configured, HA entities are created automatically:

- **Lights** - one per dimmer or on/off channel
- **Switches** - one per switch channel
- **Covers** - one per cover channel pair
- **Preset selector** - select the active preset per area
- **Scene buttons** - one button per preset per area
- **Motion sensor** - per area (when PIR is enabled)
- **Temperature / Setpoint sensors** - for HVAC areas
- **Climate entity** - for HVAC areas

Each physical device also gets its own entry under **Settings - Devices & Services**, showing online/offline status.

---

## Troubleshooting

**Integration shows "Disconnected"**
- Check the PDEG IP address and port are correct
- Make sure no firewall is blocking TCP port 50000
- The integration reconnects automatically every 5 seconds

**Devices not appearing in the Physical tab**
- Click **📡 Send Sign-on** to trigger discovery
- Devices also announce themselves when you click Sign-on in System Builder

**Entities not created after adding an area**
- Make sure at least one channel is added to the area with the correct type

**Motion sensor not updating**
- Check that PIR is enabled for the area (green button in the Logical tab)
- Verify the sensor is sending occupancy messages on the correct area number

**XML import fails**
- Use **Logical XML** in the Logical tab and **Devices XML** in the Physical tab
- The panel will warn you if you load the wrong file in the wrong tab

---

## License

MIT License - see [LICENSE](LICENSE) for details.
