# Changelog

All notable changes to this project are documented in this file.

## v1.7.0

This release adds **multi-gateway support**, a **search bar** in the config panel, and a round of project housekeeping.

### Highlights
- **Multiple PDEG gateways now work side-by-side** — even when their System Builder configs reuse the same area/channel/device numbers.
- **Search** added to both panel tabs for quickly finding devices and areas.
- Cleaner, more compact panel toolbar.

### Multi-gateway fix
Previously, running more than one PDEG whose Dynalite area/channel/device numbers overlapped caused the gateways to collide: their areas merged into shared Home Assistant devices, and live bus updates from one gateway bled into another's entities.

All cross-gateway keys are now **namespaced per gateway (by host)**:
- Dispatcher signals (area, channel, connection, device, lux, motion) no longer cross-talk between gateways.
- Home Assistant **area devices** and the **gateway hub device** get per-gateway identifiers, so each PDEG owns its own isolated set of devices.

Each gateway now shows its own areas and hardware independently, with no overlap.

### Panel: search & toolbar
- **Search bar on both tabs** — Physical filters device cards by name, model, box, or device code; Logical filters areas by number, name, or channel name. Includes a live result count and clear button, and it persists across the panel's auto-refresh.
- **Merged toolbar** — Sign-on interval, Motion poll, and Search now share a single compact row, with uniform control heights and roomier Save/Poll buttons.

### Housekeeping
- Added an **MIT `LICENSE`** file (previously referenced in the README but missing).
- `manifest.json`: filled in `codeowners`, `documentation`, and `issue_tracker`, and **synced the version to `1.7.0`** (it had drifted at `0.1.1`).
- Fixed the default port: `DEFAULT_PORT` is now **`50000`**, matching the documentation.

### Upgrade notes
- On first start after upgrading, the integration **automatically removes the old merged area/gateway device records** and recreates per-gateway ones. **Your entity IDs are preserved** (unique IDs were already gateway-specific), so dashboards, automations, and history keep working.
- If you built any **device-based** automations targeting a *logical area* or *gateway* device, those may need re-selecting, since those device records are recreated. Entity-based automations and anything on physical devices are unaffected.
- No configuration changes are required.

**Full changelog:** https://github.com/Hollako/Dynalite-HA-Integration/compare/v1.6.1...v1.7.0
