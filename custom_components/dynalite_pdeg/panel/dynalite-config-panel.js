/**
 * Dynalite PDEG Configuration Panel
 * Two-tab admin panel:
 *   Physical — discovered boxes/modules with online/offline status and rename
 *   Logical  — areas, channels, types, scan (existing config)
 */

const TYPE_LABELS = {
  dimmer: "Dimmer Light",
  onoff:  "On/Off Light",
  switch: "Switch",
  cover:  "Cover / Blind",
};

const AREA_TYPE_LABELS = {
  light: "Lighting",
  blind: "Blinds",
  hvac:  "HVAC",
};

const TYPE_OPTIONS = Object.entries(TYPE_LABELS)
  .map(([v, l]) => `<option value="${v}">${l}</option>`)
  .join("");

const AREA_TYPE_OPTIONS = Object.entries(AREA_TYPE_LABELS)
  .map(([v, l]) => `<option value="${v}">${l}</option>`)
  .join("");

class DynaliteConfigPanel extends HTMLElement {
  constructor() {
    super();
    this._hass           = null;
    this._entryId        = null;
    this._areas          = [];
    this._devices        = [];
    this._connected      = false;
    this._ready          = false;
    this._activeTab      = "physical";  // "physical" | "logical"
    this._signonInterval      = 3600;   // local copy; loaded from backend
    this._xmlLogicalAreas     = [];     // parsed logical XML areas (for preview)
    this._xmlPhysicalDevices  = [];     // parsed devices XML entries (for preview)
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ready) { this._ready = true; this._init(); }
  }

  set panel(panel) {
    this._entryId   = (panel && panel.config && panel.config.entry_id) || null;
    this._entryName = (panel && panel.config && panel.config.name)     || "";
    const el = this.querySelector("#dp-entry-name");
    if (el) el.textContent = this._entryName;
  }

  // ── Setup ──────────────────────────────────────────────────────────────────

  _init() {
    this.style.display    = "block";
    this.style.padding    = "0";
    this.style.fontFamily = "Roboto, sans-serif";
    this.innerHTML = this._skeleton();
    this._bindTabEvents();
    this._bindLogicalStaticEvents();
    this._bindXmlImportEvents();
    this._reload();
    this._subscribeMotion();
  }

  _subscribeMotion() {
    if (!this._hass || !this._hass.connection) return;
    this._hass.connection.subscribeEvents((event) => {
      const { device_code, box_number, motion } = event.data || {};
      // Find the card for this device and update its motion badge live
      const cards = this.querySelectorAll(".dp-device-card");
      cards.forEach(card => {
        const dc  = parseInt(card.dataset.deviceCode, 10);
        const bn  = parseInt(card.dataset.boxNumber,  10);
        if (dc === device_code && bn === box_number) {
          const badge = card.querySelector(".dp-dev-motion-badge");
          if (badge) {
            badge.style.background = motion ? "#e53935" : "#9e9e9e";
            badge.textContent = `🚶 ${motion ? "Motion" : "Clear"}`;
          }
        }
      });
    }, "dynalite_pdeg_device_motion");
  }

  _skeleton() {
    return `
      <style>
        #dp-root { padding: 24px; color: var(--primary-text-color, #212121); }
        #dp-root h1 { font-size: 24px; font-weight: 400; margin: 0 0 4px; }

        /* ── Tabs ── */
        .dp-tabs {
          display: flex; gap: 0; margin-bottom: 20px;
          border-bottom: 2px solid var(--divider-color, #e0e0e0);
        }
        .dp-tab {
          padding: 10px 22px; cursor: pointer; font-size: 14px; font-weight: 500;
          border-bottom: 3px solid transparent; margin-bottom: -2px;
          color: var(--secondary-text-color, #757575);
          transition: color .15s, border-color .15s;
          user-select: none;
        }
        .dp-tab.active {
          color: var(--primary-color, #03a9f4);
          border-bottom-color: var(--primary-color, #03a9f4);
        }
        .dp-tab-content { display: none; }
        .dp-tab-content.active { display: block; }

        /* ── Toolbar ── */
        .dp-toolbar {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 16px; flex-wrap: wrap; gap: 8px;
        }
        .dp-badge { display: inline-block; padding: 3px 10px; border-radius: 12px;
                    font-size: 13px; font-weight: 500; }
        .dp-ok   { background:#e8f5e9; color:#388e3c; }
        .dp-fail { background:#ffebee; color:#c62828; }

        /* ── Tables ── */
        table {
          width: 100%; border-collapse: collapse;
          background: var(--card-background-color, #fff);
          border-radius: 8px; overflow: hidden;
          box-shadow: 0 1px 4px rgba(0,0,0,.12);
        }
        th {
          text-align: left; padding: 10px 14px;
          border-bottom: 2px solid var(--divider-color, #e0e0e0);
          color: var(--secondary-text-color, #757575);
          font-size: 13px; font-weight: 500; white-space: nowrap;
        }
        td {
          padding: 8px 14px;
          border-bottom: 1px solid var(--divider-color, #f0f0f0);
          vertical-align: middle; font-size: 14px;
        }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: var(--secondary-background-color, #fafafa); }

        /* ── Inputs ── */
        input[type=text], input[type=number], select {
          padding: 4px 8px; border-radius: 4px; font-size: 14px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          box-sizing: border-box;
        }

        /* ── Buttons ── */
        .dp-btn {
          padding: 6px 14px; border: none; border-radius: 4px;
          cursor: pointer; font-size: 13px; font-weight: 500;
          transition: opacity .15s; white-space: nowrap;
        }
        .dp-btn:hover { opacity: .85; }
        .dp-btn-primary { background: var(--primary-color, #03a9f4); color: #fff; }
        .dp-btn-danger  { background: #ef5350; color: #fff; }
        .dp-btn-neutral { background: #9e9e9e; color: #fff; }
        .dp-btn-sm      { padding: 3px 8px; font-size: 12px; }
        .dp-btn-ghost {
          background: none; color: var(--primary-color, #03a9f4);
          border: 1px solid var(--primary-color, #03a9f4);
          padding: 3px 8px; font-size: 12px;
        }

        /* ── Status dot ── */
        .dp-dot {
          display: inline-block; width: 10px; height: 10px;
          border-radius: 50%; margin-right: 6px; flex-shrink: 0;
        }
        .dp-dot-on  { background: #43a047; }
        .dp-dot-off { background: #e53935; }
        .dp-status-cell { display: flex; align-items: center; }

        /* ── Physical card grid ── */
        .dp-device-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 14px;
          margin-bottom: 20px;
        }
        .dp-device-card {
          background: var(--card-background-color, #fff);
          border-radius: 8px; padding: 14px 16px;
          box-shadow: 0 1px 4px rgba(0,0,0,.12);
          border-left: 4px solid #9e9e9e;
          transition: border-color .3s;
          min-width: 0; overflow: hidden;
          box-sizing: border-box;
        }
        .dp-device-card.online  { border-left-color: #43a047; }
        .dp-device-card.offline { border-left-color: #e53935; }
        .dp-device-card-header {
          display: flex; align-items: center; margin-bottom: 8px; gap: 8px; min-width: 0;
        }
        .dp-device-card-title {
          font-size: 15px; font-weight: 500; flex: 1;
          min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .dp-device-card-meta  {
          font-size: 12px; color: var(--secondary-text-color, #757575); margin-bottom: 8px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dp-device-rename-row {
          display: flex; gap: 6px; align-items: center; margin-top: 8px; min-width: 0;
        }
        .dp-device-rename-inp { flex: 1; min-width: 0; font-size: 13px; width: 0; }
        .dp-dev-save, .dp-dev-del { flex-shrink: 0; }

        /* ── Logical panel (unchanged) ── */
        .dp-ch-row { display: flex; gap: 6px; align-items: center; margin: 3px 0; }
        .dp-ch-num { width: 82px; flex-shrink: 0; white-space: nowrap;
                     color: var(--secondary-text-color, #9e9e9e); font-size: 11px; font-weight: 600; }
        .dp-ch-inp { width: 220px; flex-shrink: 0; font-size: 12px !important; }
        .dp-ch-sel { width: 118px; flex-shrink: 0; font-size: 12px !important; }
        .dp-ch-badge { display: inline-block; padding: 1px 0; border-radius: 10px;
                       width: 90px; text-align: center; font-size: 11px; font-weight: 600; flex-shrink: 0; }
        .dp-badge-light  { background: #e3f2fd; color: #1565c0; }
        .dp-badge-cover  { background: #fff3e0; color: #e65100; }
        .dp-add-form {
          display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap;
          padding: 8px; border-radius: 6px;
          background: var(--secondary-background-color, #f5f5f5);
        }
        .dp-add-form label { font-size: 11px; color: var(--secondary-text-color, #9e9e9e); }
        .dp-down-wrap { display: none; align-items: center; gap: 4px; }
        .dp-footer { margin-top: 20px; display: flex; justify-content: flex-end; }
.dp-empty { padding: 32px; text-align: center;
                    color: var(--secondary-text-color, #9e9e9e); font-size: 14px; }

        /* ── Floating toast ── */
        #dp-toast {
          position: fixed;
          top: 20px;
          right: 24px;
          z-index: 99999;
          max-width: 420px;
          min-width: 220px;
          padding: 11px 16px;
          border-radius: 8px;
          font-size: 13px;
          font-weight: 500;
          box-shadow: 0 4px 16px rgba(0,0,0,.22);
          pointer-events: none;
          opacity: 0;
          transform: translateY(-12px);
          transition: opacity .22s ease, transform .22s ease;
        }
        #dp-toast.dp-toast-show {
          opacity: 1;
          transform: translateY(0);
        }
        #dp-toast.dp-msg-ok  { background: #e8f5e9; color: #2e7d32; }
        #dp-toast.dp-msg-err { background: #ffebee; color: #b71c1c; }
      </style>

      <div id="dp-root">
        <!-- Header -->
        <div class="dp-toolbar">
          <div>
            <h1>Dynalite PDEG - <span id="dp-entry-name">${this._entryName || ""}</span></h1>
            <div style="display:flex;align-items:center;gap:10px;margin-top:2px;">
              <span id="dp-status" class="dp-badge dp-fail">Connecting…</span>
            </div>
          </div>
        </div>

        <!-- Tab bar -->
        <div class="dp-tabs">
          <div class="dp-tab active" data-tab="physical">🔌 Physical</div>
          <div class="dp-tab"        data-tab="logical">💡 Logical</div>
        </div>

        <!-- Floating toast (shared) -->
        <div id="dp-toast"></div>

        <!-- Physical tab -->
        <div id="dp-tab-physical" class="dp-tab-content active">
          <div class="dp-toolbar" style="margin-bottom:8px;">
            <span style="font-size:13px;color:var(--secondary-text-color);">
              Discovered modules — rename by typing a new name and clicking Save.
            </span>
            <div style="display:flex;gap:8px;align-items:center;">
              <button class="dp-btn dp-btn-primary" id="dp-add-device-btn">＋ Add Device</button>
              <button class="dp-btn dp-btn-neutral" id="dp-xml-btn-physical">📂 Import XML</button>
              <button class="dp-btn dp-btn-neutral" id="dp-signon-btn">📡 Send Sign-on</button>
              <button class="dp-btn dp-btn-neutral" id="dp-refresh-devices">↻ Refresh</button>
            </div>
          </div>
          <!-- Sign-on interval setting -->
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;
                      padding:10px 14px;border-radius:6px;
                      background:var(--secondary-background-color,#f5f5f5);flex-wrap:wrap;">
            <span style="font-size:13px;font-weight:500;">Sign-on poll interval:</span>
            <input type="number" id="dp-signon-interval" min="60" max="86400" step="60"
                   style="width:90px;font-size:13px;" value="3600">
            <span style="font-size:12px;color:var(--secondary-text-color);">seconds
              &nbsp;(min 60 · max 86400 · recommended ≥ 1800)</span>
            <button class="dp-btn dp-btn-ghost dp-btn-sm" id="dp-signon-interval-save">Save</button>
            <span id="dp-interval-saved"
                  style="font-size:12px;color:#2e7d32;display:none;">✓ Saved</span>
          </div>
          <!-- Add device form (hidden by default) -->
          <div id="dp-add-device-form" style="display:none; margin-bottom:16px;">
            <div class="dp-add-form" style="padding:14px;border-radius:8px;
                 background:var(--secondary-background-color,#f5f5f5);gap:10px;">
              <div>
                <label style="font-size:11px;color:var(--secondary-text-color);">Device Code (hex)</label><br>
                <input type="text" id="dp-new-dev-code" placeholder="e.g. DC" maxlength="2"
                       style="width:80px;font-size:13px;text-transform:uppercase;">
              </div>
              <div>
                <label style="font-size:11px;color:var(--secondary-text-color);">Box Number</label><br>
                <input type="number" id="dp-new-dev-box" min="0" max="255" placeholder="1"
                       style="width:70px;font-size:13px;">
              </div>
              <div>
                <label style="font-size:11px;color:var(--secondary-text-color);">Name (optional)</label><br>
                <input type="text" id="dp-new-dev-name" placeholder="Custom name"
                       style="width:160px;font-size:13px;">
              </div>
              <div style="display:flex;gap:6px;align-items:flex-end;">
                <button class="dp-btn dp-btn-primary dp-btn-sm" id="dp-new-dev-ok">Add</button>
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-new-dev-cancel">Cancel</button>
              </div>
            </div>
          </div>
          <!-- Physical XML import (hidden until a file is parsed) -->
          <input type="file" id="dp-xml-file-physical" accept=".xml" style="display:none;">
          <div id="dp-xml-import-physical" style="display:none;margin-bottom:16px;">
            <div style="background:var(--secondary-background-color,#f5f5f5);border-radius:8px;padding:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <strong id="dp-xml-physical-title">Devices XML Preview</strong>
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-physical-cancel">✕ Cancel</button>
              </div>
              <div style="margin-bottom:8px;font-size:13px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                  <input type="checkbox" id="dp-xml-physical-overwrite">
                  Overwrite existing devices (if unchecked, existing are skipped)
                </label>
              </div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-physical-sel-all">✓ Select All</button>
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-physical-desel-all">✗ Deselect All</button>
              </div>
              <div id="dp-xml-physical-list" style="max-height:280px;overflow-y:auto;
                   background:var(--card-background-color,#fff);border-radius:6px;
                   border:1px solid var(--divider-color,#e0e0e0);"></div>
              <div style="margin-top:12px;">
                <button class="dp-btn dp-btn-primary" id="dp-xml-physical-import">📥 Import Selected</button>
              </div>
            </div>
          </div>
          <!-- D5 Sensor Motion Status Poll -->
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;
                      padding:10px 14px;border-radius:6px;flex-wrap:wrap;
                      background:var(--secondary-background-color,#f5f5f5);">
            <span style="font-size:13px;font-weight:500;">🚶 Poll Motion Status:</span>
            <input type="text" id="dp-motion-poll-boxes"
                   placeholder="Box numbers e.g. 20, 21, 22  (blank = all D5 Sensors)"
                   style="flex:1;min-width:220px;font-size:13px;">
            <button class="dp-btn dp-btn-ghost dp-btn-sm" id="dp-motion-poll-btn">Poll</button>
          </div>
          <div id="dp-device-grid" class="dp-device-grid"></div>
        </div>

        <!-- Logical tab -->
        <div id="dp-tab-logical" class="dp-tab-content">
          <div class="dp-toolbar" style="margin-bottom:12px;">
            <div></div>
            <div style="display:flex;gap:8px;">
              <button class="dp-btn dp-btn-neutral" id="dp-xml-btn-logical">📂 Import XML</button>
              <button class="dp-btn dp-btn-primary" id="dp-scan-btn">⟳ Run Scan</button>
              <button class="dp-btn dp-btn-primary" id="dp-add-area-btn">＋ Define New Area</button>
            </div>
          </div>
          <!-- Logical XML import (hidden until a file is parsed) -->
          <input type="file" id="dp-xml-file-logical" accept=".xml" style="display:none;">
          <div id="dp-xml-import-logical" style="display:none;margin-bottom:16px;">
            <div style="background:var(--secondary-background-color,#f5f5f5);border-radius:8px;padding:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <strong id="dp-xml-logical-title">Logical XML Preview</strong>
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-logical-cancel">✕ Cancel</button>
              </div>
              <div style="margin-bottom:8px;font-size:13px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                  <input type="checkbox" id="dp-xml-logical-overwrite">
                  Overwrite existing areas (if unchecked, existing are skipped)
                </label>
              </div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-logical-sel-all">✓ Select All</button>
                <button class="dp-btn dp-btn-neutral dp-btn-sm" id="dp-xml-logical-desel-all">✗ Deselect All</button>
              </div>
              <div id="dp-xml-logical-list" style="max-height:280px;overflow-y:auto;
                   background:var(--card-background-color,#fff);border-radius:6px;
                   border:1px solid var(--divider-color,#e0e0e0);"></div>
              <div style="margin-top:12px;">
                <button class="dp-btn dp-btn-primary" id="dp-xml-logical-import">📥 Import Selected</button>
              </div>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th style="width:4%">Area #</th>
                <th style="width:14%">Name</th>
                <th style="width:7%">Fade (s)</th>
                <th style="width:5%">Presets</th>
                <th style="width:9%">Area Type</th>
                <th style="width:49%">Channels</th>
                <th style="width:12%">Actions</th>
              </tr>
            </thead>
            <tbody id="dp-tbody"></tbody>
          </table>
          <div class="dp-footer">
            <small style="color:var(--secondary-text-color)">
              Edit fields inline → <b>Save Area</b>.
              Changing a channel type reloads the integration automatically.
            </small>
          </div>
        </div>
      </div>`;
  }

  // ── Tab switching ──────────────────────────────────────────────────────────

  _bindTabEvents() {
    this.querySelectorAll(".dp-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        this._activeTab = tab.dataset.tab;
        this.querySelectorAll(".dp-tab").forEach(t => t.classList.toggle("active", t === tab));
        this.querySelectorAll(".dp-tab-content").forEach(c => {
          c.classList.toggle("active", c.id === `dp-tab-${this._activeTab}`);
        });
      });
    });

    this.querySelector("#dp-refresh-devices").addEventListener("click", () => this._reloadDevices());

    this.querySelector("#dp-signon-btn").addEventListener("click", () => {
      const btn = this.querySelector("#dp-signon-btn");
      btn.disabled = true;
      btn.textContent = "Polling…";
      this._ws("dynalite_pdeg/request_signon")
        .then(r => {
          const n = r.device_count || 0;
          this._showMsg(
            `Sign-on poll started for ${n} device(s). Check HA logs, then Refresh in ~${15 + n}s.`
          );
          setTimeout(() => this._reloadDevices(), (15 + n) * 1000);
        })
        .catch(e => this._showMsg("Sign-on failed: " + e.message, true))
        .finally(() => { btn.disabled = false; btn.textContent = "📡 Send Sign-on"; });
    });

    this.querySelector("#dp-motion-poll-btn").addEventListener("click", () => {
      const inp = this.querySelector("#dp-motion-poll-boxes");
      const raw = inp.value.trim();
      let boxNumbers;
      if (raw === "") {
        // Blank → poll all known D5 Sensors (0xB3)
        boxNumbers = this._devices
          .filter(d => d.device_code === 0xB3)
          .map(d => d.box_number);
        if (boxNumbers.length === 0) {
          this._showMsg("No D5 Sensors found in device list.", true);
          return;
        }
      } else {
        boxNumbers = raw.split(",").map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
        if (boxNumbers.length === 0) {
          this._showMsg("Enter valid box numbers (comma-separated).", true);
          return;
        }
      }
      const btn = this.querySelector("#dp-motion-poll-btn");
      btn.disabled = true;
      btn.textContent = "Polling…";
      this._ws("dynalite_pdeg/request_motion_status", { box_numbers: boxNumbers })
        .then(() => this._showMsg(`Motion status requested for box(es): ${boxNumbers.join(", ")}`))
        .catch(e => this._showMsg("Poll failed: " + e.message, true))
        .finally(() => { btn.disabled = false; btn.textContent = "Poll"; });
    });

    this.querySelector("#dp-signon-interval-save").addEventListener("click", () => {
      const val = parseInt(this.querySelector("#dp-signon-interval").value);
      if (isNaN(val) || val < 60 || val > 86400) {
        this._showMsg("Interval must be between 60 and 86400 seconds.", true);
        return;
      }
      this._ws("dynalite_pdeg/set_settings", { signon_interval: val })
        .then(() => {
          this._signonInterval = val;
          const ok = this.querySelector("#dp-interval-saved");
          ok.style.display = "inline";
          setTimeout(() => { ok.style.display = "none"; }, 3000);
        })
        .catch(e => this._showMsg("Failed to save interval: " + e.message, true));
    });

    // ── Add Device form ───────────────────────────────────────────────────────
    const addForm   = this.querySelector("#dp-add-device-form");
    this.querySelector("#dp-add-device-btn").addEventListener("click", () => {
      addForm.style.display = addForm.style.display === "none" ? "block" : "none";
    });
    this.querySelector("#dp-new-dev-cancel").addEventListener("click", () => {
      addForm.style.display = "none";
      this.querySelector("#dp-new-dev-code").value = "";
      this.querySelector("#dp-new-dev-box").value  = "";
      this.querySelector("#dp-new-dev-name").value = "";
    });
    this.querySelector("#dp-new-dev-ok").addEventListener("click", () => {
      const codeStr = this.querySelector("#dp-new-dev-code").value.trim();
      const boxVal  = parseInt(this.querySelector("#dp-new-dev-box").value);
      const name    = this.querySelector("#dp-new-dev-name").value.trim();

      const code = parseInt(codeStr, 16);
      if (isNaN(code) || code < 0 || code > 255) {
        this._showMsg("Device code must be a 2-digit hex value (00–FF).", true); return;
      }
      if (isNaN(boxVal) || boxVal < 0 || boxVal > 255) {
        this._showMsg("Box number must be between 0 and 255.", true); return;
      }

      this._ws("dynalite_pdeg/add_device", { device_code: code, box_number: boxVal, name })
        .then(() => {
          addForm.style.display = "none";
          this.querySelector("#dp-new-dev-code").value = "";
          this.querySelector("#dp-new-dev-box").value  = "";
          this.querySelector("#dp-new-dev-name").value = "";
          this._showMsg(`Device 0x${codeStr.toUpperCase().padStart(2,"0")} Box ${boxVal} added.`);
          return this._reloadDevices();
        })
        .catch(e => this._showMsg(e.message, true));
    });
  }

  // ── Load & Render (both tabs) ──────────────────────────────────────────────

  async _reload() {
    await Promise.all([this._reloadDevices(), this._reloadAreas(), this._reloadSettings()]);
  }

  async _reloadSettings() {
    try {
      const r = await this._ws("dynalite_pdeg/get_settings");
      this._signonInterval = r.signon_interval || 3600;
      const inp = this.querySelector("#dp-signon-interval");
      if (inp) inp.value = this._signonInterval;
    } catch (_) { /* non-fatal */ }
  }

  async _reloadDevices() {
    try {
      const r = await this._ws("dynalite_pdeg/list_devices");
      this._devices   = r.devices || [];
      this._connected = r.connected;
      this._updateStatusBadge();
      this._renderDevices();
    } catch (e) {
      this._showMsg("Failed to load devices: " + e.message, true);
    }
  }

  async _reloadAreas() {
    try {
      const r = await this._ws("dynalite_pdeg/list_areas");
      this._areas     = r.areas || [];
      this._connected = r.connected;
      this._updateStatusBadge();
      this._renderTable();
    } catch (e) {
      this._showMsg("Failed to load areas: " + e.message, true);
    }
  }

  _updateStatusBadge() {
    const badge = this.querySelector("#dp-status");
    badge.textContent = this._connected ? "Connected" : "Disconnected";
    badge.className   = "dp-badge " + (this._connected ? "dp-ok" : "dp-fail");
  }

  // ── Physical tab — device cards ────────────────────────────────────────────

  _renderDevices() {
    const grid = this.querySelector("#dp-device-grid");
    grid.innerHTML = "";

    if (this._devices.length === 0) {
      grid.innerHTML = `<div class="dp-empty">
        No physical devices discovered yet.<br>
        They appear automatically when the gateway sends sign-on frames.
      </div>`;
      return;
    }

    const byBox   = (a, b) => a.box_number - b.box_number;
    const offline = [...this._devices].filter(d => !d.online).sort(byBox);
    const online  = [...this._devices].filter(d =>  d.online).sort(byBox);

    const addSection = (label, color, devices) => {
      if (devices.length === 0) return;
      const hdr = document.createElement("div");
      hdr.style.cssText = "grid-column:1/-1;display:flex;align-items:center;gap:10px;" +
        "margin-bottom:4px;margin-top:8px;";
      hdr.innerHTML = `
        <span style="width:10px;height:10px;border-radius:50%;background:${color};
                     flex-shrink:0;display:inline-block;"></span>
        <span style="font-size:13px;font-weight:600;color:var(--secondary-text-color,#757575);
                     text-transform:uppercase;letter-spacing:.05em;">
          ${label} (${devices.length})
        </span>
        <span style="flex:1;height:1px;background:var(--divider-color,#e0e0e0);"></span>`;
      grid.appendChild(hdr);
      for (const dev of devices) grid.appendChild(this._deviceCard(dev));
    };

    addSection("Offline", "#e53935", offline);
    addSection("Online",  "#43a047", online);
  }

  _deviceCard(dev) {
    const card = document.createElement("div");
    card.className = `dp-device-card ${dev.online ? "online" : "offline"}`;

    const displayName = dev.name || `${dev.model} (Box ${dev.box_number})`;
    const lastSeenTxt = dev.last_seen_s != null
      ? `Last seen: ${this._fmtAge(dev.last_seen_s)} ago`
      : "Never seen";
    const statusTxt = dev.online ? "Online" : "Offline";
    const dotClass  = dev.online ? "dp-dot-on" : "dp-dot-off";

    card.style.position = "relative";
    card.dataset.deviceCode = dev.device_code;
    card.dataset.boxNumber  = dev.box_number;
    card.innerHTML = `
      <button class="dp-btn dp-btn-danger dp-btn-sm dp-dev-del" title="Delete this device"
              style="position:absolute;top:14px;right:16px;">✕</button>
      <div class="dp-device-card-header" style="padding-right:28px;">
        <span class="dp-dot ${dotClass}"></span>
        <span class="dp-device-card-title">${this._esc(displayName)}</span>
        <span class="dp-badge ${dev.online ? "dp-ok" : "dp-fail"}" style="font-size:11px;">${statusTxt}</span>
      </div>
      <div class="dp-device-card-meta" style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">
        <div>
          Model: ${this._esc(dev.model)} &nbsp;·&nbsp;
          Box: ${dev.box_number} &nbsp;·&nbsp;
          Code: 0x${dev.device_code.toString(16).toUpperCase().padStart(2,"0")}
          <br>${lastSeenTxt}
        </div>
        ${dev.device_code === 0xB3 ? `
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0;">
          <button class="dp-btn dp-btn-sm dp-dev-lux" style="
                  background:${dev.has_lux ? "#43a047" : "#9e9e9e"};color:#fff;"
                  title="${dev.has_lux ? "Lux sensor enabled — click to disable" : "Click to enable illuminance sensor"}">
            💡 Lux${dev.has_lux ? " ✓" : ""}
          </button>
          <span class="dp-dev-motion-badge" style="
                font-size:11px;font-weight:600;padding:2px 7px;border-radius:10px;
                background:${dev.motion_detected === true ? "#e53935" : dev.motion_detected === false ? "#9e9e9e" : "#bdbdbd"};
                color:#fff;">
            🚶 ${dev.motion_detected === true ? "Motion" : dev.motion_detected === false ? "Clear" : "—"}
          </span>
        </div>` : ""}
      </div>
      <div class="dp-device-rename-row">
        <input type="text" class="dp-device-rename-inp"
               placeholder="${this._esc(dev.model)} (Box ${dev.box_number})"
               value="${this._esc(dev.name)}">
        <button class="dp-btn dp-btn-ghost dp-btn-sm dp-dev-save">Save name</button>
        <button class="dp-btn dp-btn-ghost dp-btn-sm dp-dev-ping" title="Send sign-on to this device">📡</button>
      </div>`;

    card.querySelector(".dp-dev-ping").addEventListener("click", () => {
      const btn = card.querySelector(".dp-dev-ping");
      btn.disabled = true;
      this._ws("dynalite_pdeg/request_signon_device", {
        device_code: dev.device_code,
        box_number:  dev.box_number,
      })
        .then(() => {
          btn.textContent = "⏳";
          setTimeout(() => {
            btn.textContent = "📡";
            btn.disabled = false;
            this._reloadDevices();
          }, 6000);
        })
        .catch(e => {
          this._showMsg(e.message, true);
          btn.textContent = "📡";
          btn.disabled = false;
        });
    });

    card.querySelector(".dp-dev-save").addEventListener("click", () => {
      const newName = card.querySelector(".dp-device-rename-inp").value.trim();
      this._ws("dynalite_pdeg/update_device", {
        device_code: dev.device_code,
        box_number:  dev.box_number,
        name:        newName,
      })
        .then(() => {
          dev.name = newName;
          this._showMsg(`Box ${dev.box_number} renamed.`);
          this._renderDevices();
        })
        .catch(e => this._showMsg(e.message, true));
    });

    const luxBtn = card.querySelector(".dp-dev-lux");
    if (luxBtn) luxBtn.addEventListener("click", () => this._toggleLux(dev, card));

    card.querySelector(".dp-dev-del").addEventListener("click", () => {
      const label = dev.name || `${dev.model} (Box ${dev.box_number})`;
      if (!confirm(`Delete "${label}"?\nThis removes the device and its binary sensor from HA.`)) return;
      this._ws("dynalite_pdeg/delete_device", {
        device_code: dev.device_code,
        box_number:  dev.box_number,
      })
        .then(() => {
          this._showMsg(`Box ${dev.box_number} deleted.`);
          return this._reloadDevices();
        })
        .catch(e => this._showMsg(e.message, true));
    });

    return card;
  }

  _fmtAge(seconds) {
    if (seconds < 60)   return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    return `${Math.floor(seconds / 3600)}h`;
  }

  // ── Logical tab — area table ───────────────────────────────────────────────

  _bindLogicalStaticEvents() {
    this.querySelector("#dp-add-area-btn").addEventListener("click", () => this._addAreaPrompt());
    this.querySelector("#dp-scan-btn").addEventListener("click",     () => this._runScan());
  }

  _renderTable() {
    const tbody = this.querySelector("#dp-tbody");
    tbody.innerHTML = "";
    const sorted = [...this._areas].sort((a, b) => a.area - b.area);
    for (const ar of sorted) tbody.appendChild(this._areaRow(ar));
  }

  _areaRow(ar) {
    const tr = document.createElement("tr");
    const areaType = ar.area_type || "light";

    const areaTypeOpts = Object.entries(AREA_TYPE_LABELS)
      .map(([v, l]) => `<option value="${v}"${v === areaType ? " selected" : ""}>${l}</option>`)
      .join("");

    let chHTML = "";
    if (!ar.channels || ar.channels.length === 0) {
      chHTML = '<span style="color:#9e9e9e;font-size:12px;">(no channels)</span>';
    } else {
      chHTML = ar.channels
        .slice()
        .sort((a, b) => a.ch0 - b.ch0)
        .map(ch => {
          if (ch.channel_type === "cover") {
            const upNum   = ch.ch0 + 1;
            const downNum = ch.cover_partner_ch0 != null ? ch.cover_partner_ch0 + 1 : "?";
            return `
              <div class="dp-ch-row" data-chrow="${ch.ch0}">
                <span class="dp-ch-num">↑ Ch ${upNum} · ↓ Ch ${downNum}</span>
                <input type="text" class="dp-ch-name dp-ch-inp" data-ch="${ch.ch0}"
                       value="${this._esc(ch.name)}" placeholder="Cover name">
                <span class="dp-ch-badge dp-badge-cover">Cover / Blind</span>
                <span class="dp-ch-sel" style="border:none;background:none;"></span>
                <button class="dp-btn dp-btn-ghost dp-btn-sm dp-ch-save"
                        data-ch="${ch.ch0}" data-partner="${ch.cover_partner_ch0 ?? ""}">Save</button>
                <button class="dp-btn dp-btn-danger dp-btn-sm dp-ch-del"
                        data-ch="${ch.ch0}" data-partner="${ch.cover_partner_ch0 ?? ""}">✕</button>
              </div>`;
          } else {
            const dispNum  = ch.ch0 + 1;
            const typeOpts = Object.entries(TYPE_LABELS)
              .map(([v, l]) => `<option value="${v}"${v === ch.channel_type ? " selected" : ""}>${l}</option>`)
              .join("");
            return `
              <div class="dp-ch-row" data-chrow="${ch.ch0}">
                <span class="dp-ch-num">Ch ${dispNum}</span>
                <input type="text" class="dp-ch-name dp-ch-inp" data-ch="${ch.ch0}"
                       value="${this._esc(ch.name)}" placeholder="Channel ${dispNum}">
                <span class="dp-ch-badge dp-badge-light">${TYPE_LABELS[ch.channel_type] || ch.channel_type}</span>
                <select class="dp-ch-type-sel dp-ch-sel" data-ch="${ch.ch0}">${typeOpts}</select>
                <button class="dp-btn dp-btn-ghost dp-btn-sm dp-ch-save"
                        data-ch="${ch.ch0}" data-partner="">Save</button>
                <button class="dp-btn dp-btn-danger dp-btn-sm dp-ch-del"
                        data-ch="${ch.ch0}" data-partner="">✕</button>
              </div>`;
          }
        })
        .join("");
    }

    tr.innerHTML = `
      <td style="vertical-align:middle;">${ar.area}</td>
      <td><input type="text" class="dp-name" value="${this._esc(ar.name)}"
                 placeholder="Area ${ar.area}" style="width:100%;"></td>
      <td><input type="number" class="dp-fade" value="${(ar.fade_tenths / 10).toFixed(1)}"
                 min="0.1" max="600" step="0.1" style="width:65px;"></td>
      <td><input type="number" class="dp-presets" value="${ar.preset_count}"
                 min="1" max="255" style="width:52px;"></td>
      <td><select class="dp-area-type">${areaTypeOpts}</select></td>
      <td>
        <!-- Blind area: curtain manager -->
        <div class="dp-curtain-wrap" style="display:${areaType === 'blind' ? 'block' : 'none'};">
          <div class="dp-curtain-list"></div>
          <button class="dp-btn dp-btn-ghost dp-btn-sm dp-curtain-add" style="margin-top:8px;">＋ Add Curtain</button>
        </div>
        <!-- HVAC area: mode + fan config -->
        <div class="dp-hvac-config" style="display:${areaType === 'hvac' ? 'block' : 'none'};font-size:12px;">
        </div>
        <!-- Light area: channel list -->
        <div class="dp-ch-content" style="display:${areaType === 'light' ? 'block' : 'none'};">
          <div class="dp-ch-list">${chHTML}</div>
          <button class="dp-btn dp-btn-ghost dp-btn-sm dp-ch-add" style="margin-top:8px;">＋ Add Channel</button>
          <div class="dp-preset-names-wrap"></div>
        </div>
      </td>
      <td style="height:1px;padding:6px 14px;vertical-align:top;">
        <div style="display:flex;flex-direction:column;align-items:flex-end;
                    justify-content:space-between;height:100%;min-height:90px;">
          <!-- top: delete -->
          <button class="dp-btn dp-btn-danger dp-btn-sm dp-area-del" title="Delete area">✕</button>
          <!-- middle: sensor toggles -->
          <div style="display:flex;gap:6px;align-items:center;">
            <button class="dp-btn dp-btn-sm dp-area-pir"
                    style="background:${ar.has_pir ? "#43a047" : "#9e9e9e"};color:#fff;"
                    title="${ar.has_pir ? "Motion enabled — click to disable" : "Click to enable motion sensor"}">
              🚶 Motion${ar.has_pir ? " ✓" : ""}
            </button>
            <button class="dp-btn dp-btn-sm dp-area-temp"
                    style="background:${ar.has_temp ? "#43a047" : "#9e9e9e"};color:#fff;"
                    title="${ar.has_temp ? "Temp sensor enabled — click to disable" : "Click to enable temperature sensor"}">
              🌡 Temp${ar.has_temp ? " ✓" : ""}
            </button>
          </div>
          <!-- bottom: save (aligns with + Add Channel) -->
          <button class="dp-btn dp-btn-primary dp-btn-sm dp-area-save">Save Area</button>
        </div>
      </td>`;

    tr.querySelector(".dp-area-save").addEventListener("click", () => this._saveArea(ar.area, tr));
    tr.querySelector(".dp-area-del").addEventListener("click",  () => this._deleteArea(ar.area));
    tr.querySelector(".dp-area-pir").addEventListener("click",  () => this._togglePir(ar.area, ar.has_pir, tr));
    tr.querySelector(".dp-area-temp").addEventListener("click", () => this._toggleTemp(ar.area, ar.has_temp, tr));
    tr.querySelector(".dp-ch-add").addEventListener("click",    () => this._showAddChannelForm(ar.area, tr));

    // Populate curtain rows from loaded data
    const curtainList = tr.querySelector(".dp-curtain-list");
    for (const c of (ar.curtains || [])) {
      curtainList.appendChild(this._curtainRow(c));
    }
    tr.querySelector(".dp-curtain-add").addEventListener("click", () => {
      curtainList.appendChild(this._curtainRow({name: "", open_preset: 1, stop_preset: 3, close_preset: 2}));
    });

    // Populate HVAC config
    this._buildHvacConfig(tr.querySelector(".dp-hvac-config"), ar);

    // Populate preset names editor (light areas)
    this._buildPresetNamesEditor(tr.querySelector(".dp-preset-names-wrap"), ar);

    tr.querySelector(".dp-area-type").addEventListener("change", () => {
      const newType = tr.querySelector(".dp-area-type").value;
      tr.querySelector(".dp-curtain-wrap").style.display  = newType === "blind" ? "block" : "none";
      tr.querySelector(".dp-hvac-config").style.display   = newType === "hvac"  ? "block" : "none";
      tr.querySelector(".dp-ch-content").style.display    = newType === "light" ? "block" : "none";
    });

    tr.querySelectorAll(".dp-ch-type-sel").forEach(sel => {
      sel.addEventListener("change", () => {
        const ch0 = sel.dataset.ch;
        const row = tr.querySelector(`[data-chrow="${ch0}"]`);
        let downWrap = row.querySelector(".dp-down-wrap");
        if (sel.value === "cover") {
          if (!downWrap) {
            downWrap = document.createElement("span");
            downWrap.className = "dp-down-wrap";
            downWrap.style.display = "flex";
            downWrap.innerHTML = `
              <span style="font-size:11px;color:var(--secondary-text-color);">↓ Down Ch</span>
              <input type="number" min="1" max="64" class="dp-ch-down"
                     style="width:52px;font-size:12px;" placeholder="1–64">`;
            sel.after(downWrap);
          }
        } else {
          if (downWrap) downWrap.remove();
        }
      });
    });

    tr.querySelectorAll(".dp-ch-save").forEach(btn => {
      btn.addEventListener("click", () => {
        const ch0     = parseInt(btn.dataset.ch);
        const typeSel = tr.querySelector(`.dp-ch-type-sel[data-ch="${ch0}"]`);
        const nameInp = tr.querySelector(`.dp-ch-name[data-ch="${ch0}"]`);
        const name    = nameInp ? nameInp.value.trim() : "";
        const channelType = typeSel ? typeSel.value : "cover";

        let partnerCh0 = null;
        const pStr = btn.dataset.partner;
        if (pStr !== "") {
          const pv = parseInt(pStr);
          if (!isNaN(pv)) partnerCh0 = pv;
        }
        if (channelType === "cover" && partnerCh0 === null) {
          const row     = tr.querySelector(`[data-chrow="${ch0}"]`);
          const downInp = row ? row.querySelector(".dp-ch-down") : null;
          if (!downInp || !downInp.value) {
            alert("Enter the ↓ Down channel number (1–64) for this cover.");
            return;
          }
          const dv = parseInt(downInp.value);
          if (isNaN(dv) || dv < 1 || dv > 64 || (dv - 1) === ch0) {
            alert("Invalid down channel number.");
            return;
          }
          partnerCh0 = dv - 1;
        }
        this._saveChannel(ar.area, ch0, channelType, name, partnerCh0);
      });
    });

    tr.querySelectorAll(".dp-ch-del").forEach(btn => {
      const ch0  = parseInt(btn.dataset.ch);
      const pStr = btn.dataset.partner;
      btn.addEventListener("click", () => {
        let msg;
        if (pStr !== "" && !isNaN(parseInt(pStr))) {
          const dn = parseInt(pStr) + 1;
          msg = `Delete cover (↑ Ch ${ch0 + 1} / ↓ Ch ${dn}) from Area ${ar.area}?\nThis removes the cover entity.`;
        } else {
          msg = `Delete channel ${ch0 + 1} from Area ${ar.area}?`;
        }
        this._deleteChannel(ar.area, ch0, msg);
      });
    });

    return tr;
  }

  // ── Add channel inline form ────────────────────────────────────────────────

  _showAddChannelForm(areaNum, tr) {
    const addBtn = tr.querySelector(".dp-ch-add");
    if (tr.querySelector(".dp-add-form")) return;
    addBtn.style.display = "none";

    const form = document.createElement("div");
    form.className = "dp-add-form";
    form.innerHTML = `
      <label>↑ Ch #</label>
      <input type="number" min="1" max="64" placeholder="1–64"
             style="width:58px;font-size:12px;" class="dp-new-ch-num">
      <div class="dp-down-wrap">
        <label>↓ Down Ch #</label>
        <input type="number" min="1" max="64" placeholder="1–64"
               style="width:58px;font-size:12px;" class="dp-new-ch-down">
      </div>
      <input type="text" placeholder="Name (optional)"
             style="width:130px;font-size:12px;" class="dp-new-ch-name">
      <select class="dp-new-ch-type" style="font-size:12px;">${TYPE_OPTIONS}</select>
      <button class="dp-btn dp-btn-primary dp-btn-sm dp-new-ch-ok">Add</button>
      <button class="dp-btn dp-btn-neutral dp-btn-sm dp-new-ch-cancel">✕ Cancel</button>`;

    tr.querySelector(".dp-ch-list").after(form);
    form.querySelector(".dp-new-ch-num").focus();

    const typeSelect = form.querySelector(".dp-new-ch-type");
    const downWrap   = form.querySelector(".dp-down-wrap");

    typeSelect.addEventListener("change", () => {
      downWrap.style.display = typeSelect.value === "cover" ? "flex" : "none";
    });

    form.querySelector(".dp-new-ch-ok").addEventListener("click", () => {
      const numVal = parseInt(form.querySelector(".dp-new-ch-num").value);
      if (isNaN(numVal) || numVal < 1 || numVal > 64) {
        alert("Channel number must be between 1 and 64."); return;
      }
      const ch0  = numVal - 1;
      const name = form.querySelector(".dp-new-ch-name").value.trim();
      const type = typeSelect.value;
      const payload = { area: areaNum, ch0, channel_type: type, name };

      if (type === "cover") {
        const downVal = parseInt(form.querySelector(".dp-new-ch-down").value);
        if (isNaN(downVal) || downVal < 1 || downVal > 64) {
          alert("Down channel number must be between 1 and 64."); return;
        }
        if (downVal === numVal) {
          alert("Up and down channels must be different."); return;
        }
        payload.cover_partner_ch0 = downVal - 1;
      }

      this._ws("dynalite_pdeg/add_channel", payload)
        .then(() => { this._showMsg(`Channel added to Area ${areaNum}.`); return this._reloadAreas(); })
        .catch(e => this._showMsg(e.message, true));
    });

    form.querySelector(".dp-new-ch-cancel").addEventListener("click", () => {
      form.remove();
      addBtn.style.display = "";
    });
  }

  // ── Logical actions ────────────────────────────────────────────────────────

  async _saveArea(areaNum, tr) {
    const name     = tr.querySelector(".dp-name").value.trim();
    const fadeSecs = Math.max(0.1, parseFloat(tr.querySelector(".dp-fade").value) || 2);
    const presets  = parseInt(tr.querySelector(".dp-presets").value) || 4;
    const areaType = tr.querySelector(".dp-area-type").value;

    // Collect curtains from DOM rows (only relevant for blind areas, but always sent)
    const curtains = [];
    tr.querySelectorAll(".dp-curtain-row").forEach(row => {
      curtains.push({
        name:         row.querySelector(".dp-curtain-name").value.trim(),
        open_preset:  parseInt(row.querySelector(".dp-curtain-open").value)  || 1,
        stop_preset:  parseInt(row.querySelector(".dp-curtain-stop").value)  || 3,
        close_preset: parseInt(row.querySelector(".dp-curtain-close").value) || 2,
      });
    });

    // Collect HVAC config
    const hvacModeMethod = tr.querySelector(".dp-hvac-mode-method")?.value || "";
    const _hvacModeAreaRaw = parseInt(tr.querySelector(".dp-hvac-mode-area")?.value) || areaNum;
    const hvacModeArea   = _hvacModeAreaRaw === areaNum ? 0 : _hvacModeAreaRaw;
    const hvacModeCh0    = Math.max(0, (parseInt(tr.querySelector(".dp-hvac-mode-ch")?.value) || 1) - 1);
    const hvacModeMap    = {};
    tr.querySelectorAll(".dp-hvac-mode-map-row").forEach(row => {
      const k = row.querySelector(".dp-hvac-map-key").value;
      const v = parseInt(row.querySelector(".dp-hvac-map-val").value) || 0;
      if (k) hvacModeMap[k] = v;
    });
    const hvacFanMethod = tr.querySelector(".dp-hvac-fan-method")?.value || "";
    const _hvacFanAreaRaw = parseInt(tr.querySelector(".dp-hvac-fan-area")?.value) || areaNum;
    const hvacFanArea   = _hvacFanAreaRaw === areaNum ? 0 : _hvacFanAreaRaw;
    const hvacFanCh0    = Math.max(0, (parseInt(tr.querySelector(".dp-hvac-fan-ch")?.value) || 1) - 1);
    const hvacFanMap    = {};
    tr.querySelectorAll(".dp-hvac-fan-map-row").forEach(row => {
      const k = row.querySelector(".dp-hvac-map-key").value;
      const v = parseInt(row.querySelector(".dp-hvac-map-val").value) || 0;
      if (k) hvacFanMap[k] = v;
    });

    // Setpoint step (0.5 or 1.0)
    const stepEl = tr.querySelector(".dp-setpt-step:checked");
    const setptStep = stepEl ? parseFloat(stepEl.value) : 0.5;

    const payload = {
      area: areaNum, name,
      fade_tenths:      Math.round(fadeSecs * 10),
      preset_count:     presets,
      area_type:        areaType,
      curtains,
      hvac_mode_area:   hvacModeArea,
      hvac_mode_method: hvacModeMethod,
      hvac_mode_ch0:    hvacModeCh0,
      hvac_mode_map:    hvacModeMap,
      hvac_fan_area:    hvacFanArea,
      hvac_fan_method:  hvacFanMethod,
      hvac_fan_ch0:     hvacFanCh0,
      hvac_fan_map:     hvacFanMap,
      setpt_step:       setptStep,
    };

    try {
      await this._ws("dynalite_pdeg/update_area", payload);
      this._showMsg(`Area ${areaNum} saved.`);
      await this._reloadAreas();
    } catch (e) { this._showMsg(e.message, true); }
  }

  // ── HVAC config builder ────────────────────────────────────────────────────

  _buildHvacConfig(container, ar) {
    container.innerHTML = "";

    const HVAC_MODES = {off:"Off", cool:"Cool", heat:"Heat", fan_only:"Fan Only", auto:"Auto", dry:"Dry"};
    const FAN_MODES  = {off:"Off", low:"Low", medium:"Medium", high:"High", auto:"Auto"};

    const modeSection = this._hvacSection(
      "HVAC Mode",
      "dp-hvac-mode-method",
      "dp-hvac-mode-area",
      "dp-hvac-mode-ch",
      "dp-hvac-mode-map-row",
      "dp-hvac-mode-add",
      ar.hvac_mode_method || "",
      ar.hvac_mode_area   || 0,
      ar.hvac_mode_ch0    || 0,
      ar.hvac_mode_map    || {},
      HVAC_MODES,
      ar.area,
    );
    const fanSection = this._hvacSection(
      "Fan Speed",
      "dp-hvac-fan-method",
      "dp-hvac-fan-area",
      "dp-hvac-fan-ch",
      "dp-hvac-fan-map-row",
      "dp-hvac-fan-add",
      ar.hvac_fan_method || "",
      ar.hvac_fan_area   || 0,
      ar.hvac_fan_ch0    || 0,
      ar.hvac_fan_map    || {},
      FAN_MODES,
      ar.area,
    );

    // ── Setpoint step ──
    const step = ar.setpt_step || 0.5;
    const stepWrap = document.createElement("div");
    stepWrap.style.cssText = "margin-bottom:10px;border:1px solid var(--divider-color,#e0e0e0);border-radius:6px;padding:8px;";
    stepWrap.innerHTML = `
      <div style="font-weight:500;margin-bottom:6px;">Setpoint Step</div>
      <label style="margin-right:16px;cursor:pointer;">
        <input type="radio" class="dp-setpt-step" name="dp-setpt-step-${ar.area}" value="0.5"
          ${step === 0.5 ? "checked" : ""}> 0.5 °C
      </label>
      <label style="cursor:pointer;">
        <input type="radio" class="dp-setpt-step" name="dp-setpt-step-${ar.area}" value="1"
          ${step === 1.0 ? "checked" : ""}> 1 °C
      </label>`;

    container.appendChild(modeSection);
    container.appendChild(fanSection);
    container.appendChild(stepWrap);
  }

  _hvacSection(title, methodCls, areaCls, chCls, rowCls, addCls, method, areaNum, ch0, map, labelMap, defaultArea) {
    const wrap = document.createElement("div");
    wrap.style.cssText = "margin-bottom:10px;border:1px solid var(--divider-color,#e0e0e0);border-radius:6px;padding:8px;";

    const isPreset  = method === "preset";
    const isChannel = method === "channel";
    const unitLabel = isChannel ? "%" : "#";

    const methodOpts = [
      `<option value=""${method === "" ? " selected" : ""}>Not configured</option>`,
      `<option value="preset"${isPreset ? " selected" : ""}>Preset</option>`,
      `<option value="channel"${isChannel ? " selected" : ""}>Channel Level</option>`,
    ].join("");

    const keyOpts = Object.entries(labelMap)
      .map(([v, l]) => `<option value="${v}">${l}</option>`)
      .join("");

    const displayArea = areaNum || defaultArea || 0;
    wrap.innerHTML = `
      <div style="font-weight:500;margin-bottom:6px;font-size:13px;">${title}</div>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:6px;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="font-size:12px;">Method:</span>
          <select class="${methodCls}" style="font-size:12px;">${methodOpts}</select>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="font-size:12px;">Area:</span>
          <input type="number" class="${areaCls}" min="1" max="255" value="${displayArea}"
                 style="width:52px;font-size:12px;">
        </div>
        <div class="${chCls}-wrap" style="display:${isChannel ? "flex" : "none"};align-items:center;gap:6px;">
          <span style="font-size:12px;">Channel:</span>
          <input type="number" class="${chCls}" min="1" max="64" value="${ch0 + 1}"
                 style="width:52px;font-size:12px;">
        </div>
      </div>
      <div class="${rowCls}-list" style="display:${method ? "block" : "none"};">
      </div>
      <button class="dp-btn dp-btn-ghost dp-btn-sm ${addCls}"
              style="margin-top:4px;display:${method ? "block" : "none"};">＋ Add Row</button>`;

    // Populate existing map rows
    const rowList  = wrap.querySelector(`.${rowCls}-list`);
    const addBtn   = wrap.querySelector(`.${addCls}`);
    const methodSel = wrap.querySelector(`.${methodCls}`);
    const chWrap   = wrap.querySelector(`.${chCls}-wrap`);

    const makeRow = (key, val, unitLbl) => {
      const div = document.createElement("div");
      div.className = `${rowCls} dp-hvac-map-row`;
      div.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap;";
      const selOpts = Object.entries(labelMap)
        .map(([v, l]) => `<option value="${v}"${v === key ? " selected" : ""}>${l}</option>`)
        .join("");
      div.innerHTML = `
        <select class="dp-hvac-map-key" style="font-size:12px;">${selOpts}</select>
        <span style="font-size:11px;color:var(--secondary-text-color);">→ <span class="dp-hvac-unit-lbl">${unitLbl === "%" ? "Level" : "Preset"}</span></span>
        <input type="number" class="dp-hvac-map-val" min="0" max="255" value="${val}"
               style="width:52px;font-size:12px;">
        <span class="dp-hvac-unit-sym" style="font-size:11px;">${unitLbl}</span>
        <button class="dp-btn dp-btn-danger dp-btn-sm dp-hvac-map-del">✕</button>`;
      div.querySelector(".dp-hvac-map-del").addEventListener("click", () => div.remove());
      return div;
    };

    for (const [k, v] of Object.entries(map)) {
      rowList.appendChild(makeRow(k, v, unitLabel));
    }

    addBtn.addEventListener("click", () => {
      const curMethod = methodSel.value;
      const lbl = curMethod === "channel" ? "%" : "#";
      rowList.appendChild(makeRow("", 1, lbl));
    });

    methodSel.addEventListener("change", () => {
      const m = methodSel.value;
      chWrap.style.display   = m === "channel" ? "flex"  : "none";
      rowList.style.display  = m ? "block" : "none";
      addBtn.style.display   = m ? "block" : "none";
      // Update unit labels on existing rows
      const isC = m === "channel";
      wrap.querySelectorAll(".dp-hvac-unit-lbl").forEach(el => el.textContent = isC ? "Level" : "Preset");
      wrap.querySelectorAll(".dp-hvac-unit-sym").forEach(el => el.textContent  = isC ? "%" : "#");
    });

    return wrap;
  }

  // ── Preset names editor ───────────────────────────────────────────────────

  _buildPresetNamesEditor(container, ar) {
    if (!container) return;
    container.innerHTML = "";

    const DEFAULT_NAMES = {1: "High", 2: "Medium", 3: "Low", 4: "Off"};
    const presetNames = ar.preset_names || {};
    const count = ar.preset_count || 4;

    // ── toggle header ─────────────────────────────────────────────────────────
    const header = document.createElement("div");
    header.style.cssText = "display:flex;align-items:center;gap:6px;cursor:pointer;margin-top:10px;user-select:none;";
    header.innerHTML = `
      <span style="font-size:12px;font-weight:500;color:var(--primary-color,#03a9f4);">🏷 Preset Names</span>
      <span class="dp-pn-arrow" style="font-size:10px;color:var(--secondary-text-color);">▶</span>`;

    // ── collapsible body ──────────────────────────────────────────────────────
    const body = document.createElement("div");
    body.style.cssText = "display:none;margin-top:6px;padding:8px;border-radius:6px;" +
      "background:var(--secondary-background-color,#f5f5f5);";

    const buildRows = (n) => {
      body.innerHTML = "";
      for (let i = 1; i <= n; i++) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:4px;";
        const placeholder = DEFAULT_NAMES[i] || `Preset ${i}`;
        const current = presetNames[String(i)] || presetNames[i] || "";
        row.innerHTML = `
          <span style="font-size:12px;min-width:60px;color:var(--secondary-text-color);">Preset ${i}:</span>
          <input type="text" class="dp-preset-name-inp" data-preset="${i}"
                 value="${this._esc(current)}" placeholder="${this._esc(placeholder)}"
                 style="width:150px;font-size:12px;">`;
        body.appendChild(row);
      }
      // save button
      const foot = document.createElement("div");
      foot.style.cssText = "display:flex;justify-content:flex-end;margin-top:6px;";
      foot.innerHTML = `<button class="dp-btn dp-btn-ghost dp-btn-sm dp-preset-names-save">💾 Save Names</button>`;
      foot.querySelector(".dp-preset-names-save").addEventListener("click", () => {
        this._savePresetNames(ar.area, body);
      });
      body.appendChild(foot);
    };

    buildRows(count);

    // ── toggle click ──────────────────────────────────────────────────────────
    let open = false;
    header.addEventListener("click", () => {
      open = !open;
      body.style.display = open ? "block" : "none";
      header.querySelector(".dp-pn-arrow").textContent = open ? "▼" : "▶";
    });

    container.appendChild(header);
    container.appendChild(body);
  }

  async _savePresetNames(areaNum, body) {
    const names = {};
    body.querySelectorAll(".dp-preset-name-inp").forEach(inp => {
      const preset = inp.dataset.preset;
      const val    = inp.value.trim();
      if (val) names[preset] = val;
    });
    try {
      await this._ws("dynalite_pdeg/update_preset_names", {
        area:         areaNum,
        preset_names: names,
      });
      this._showMsg(`Preset names for Area ${areaNum} saved.`);
      // Refresh local area state
      const r = await this._ws("dynalite_pdeg/list_areas");
      const updated = (r.areas || []).find(a => a.area === areaNum);
      if (updated) {
        const idx = this._areas.findIndex(a => a.area === areaNum);
        if (idx >= 0) this._areas[idx] = updated;
      }
    } catch (e) { this._showMsg(e.message, true); }
  }

  // ── Curtain row builder ────────────────────────────────────────────────────

  _curtainRow(c) {
    const div = document.createElement("div");
    div.className = "dp-curtain-row";
    div.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;";
    div.innerHTML = `
      <input type="text" class="dp-curtain-name dp-ch-inp"
             placeholder="Curtain name" value="${this._esc(c.name || "")}"
             style="width:130px;">
      <label style="font-size:12px;display:flex;align-items:center;gap:3px;">
        Open&nbsp;<input type="number" class="dp-curtain-open"
                         min="1" max="255" value="${c.open_preset || 1}"
                         style="width:46px;font-size:12px;">
      </label>
      <label style="font-size:12px;display:flex;align-items:center;gap:3px;">
        Stop&nbsp;<input type="number" class="dp-curtain-stop"
                         min="1" max="255" value="${c.stop_preset || 3}"
                         style="width:46px;font-size:12px;">
      </label>
      <label style="font-size:12px;display:flex;align-items:center;gap:3px;">
        Close&nbsp;<input type="number" class="dp-curtain-close"
                          min="1" max="255" value="${c.close_preset || 2}"
                          style="width:46px;font-size:12px;">
      </label>
      <button class="dp-btn dp-btn-danger dp-btn-sm dp-curtain-del" title="Remove curtain">✕</button>`;
    div.querySelector(".dp-curtain-del").addEventListener("click", () => div.remove());
    return div;
  }

  async _deleteArea(areaNum) {
    if (!confirm(`Delete Area ${areaNum} and all its channels?\nThis cannot be undone.`)) return;
    try {
      await this._ws("dynalite_pdeg/delete_area", { area: areaNum });
      this._showMsg(`Area ${areaNum} deleted.`);
      await this._reloadAreas();
    } catch (e) { this._showMsg(e.message, true); }
  }

  _addAreaPrompt() {
    const num = prompt("Area number to add (1–255):");
    if (num === null) return;
    const area = parseInt(num);
    if (!area || area < 1 || area > 255) { alert("Invalid area number."); return; }
    this._ws("dynalite_pdeg/add_area", { area })
      .then(() => { this._showMsg(`Area ${area} added.`); return this._reloadAreas(); })
      .catch(e => this._showMsg(e.message, true));
  }

  async _saveChannel(areaNum, ch0, channelType, name, partnerCh0 = null) {
    const payload = { area: areaNum, ch0, channel_type: channelType, name };
    if (channelType === "cover" && partnerCh0 !== null) payload.cover_partner_ch0 = partnerCh0;
    try {
      const res = await this._ws("dynalite_pdeg/update_channel", payload);
      if (res && res.reloading) {
        this._showMsg(`Ch ${ch0 + 1} type changed — reloading integration, please wait…`);
        setTimeout(() => this._reloadAreas(), 5000);
      } else {
        this._showMsg(`Channel ${ch0 + 1} saved.`);
        await this._reloadAreas();
      }
    } catch (e) { this._showMsg(e.message, true); }
  }

  async _deleteChannel(areaNum, ch0, confirmMsg = null) {
    const msg = confirmMsg || `Delete channel ${ch0 + 1} from Area ${areaNum}?`;
    if (!confirm(msg)) return;
    try {
      await this._ws("dynalite_pdeg/delete_channel", { area: areaNum, ch0 });
      this._showMsg("Channel deleted.");
      await this._reloadAreas();
    } catch (e) { this._showMsg(e.message, true); }
  }

  async _runScan() {
    try {
      await this._ws("dynalite_pdeg/run_scan", {});
      this._showMsg("Scan started — results will appear within 30 seconds.");
      setTimeout(() => this._reloadAreas(), 10000);
    } catch (e) { this._showMsg(e.message, true); }
  }

  async _togglePir(areaNum, currentlyEnabled, tr) {
    const enable = !currentlyEnabled;
    const action = enable ? "enable" : "disable";
    if (!enable && !confirm(`Disable motion sensor for Area ${areaNum}?\nThe motion sensor entity will be removed from HA.`)) return;
    try {
      await this._ws("dynalite_pdeg/set_pir", { area: areaNum, has_pir: enable });
      this._showMsg(`Motion sensor ${enable ? "enabled" : "disabled"} for Area ${areaNum}.${enable ? " Motion entity created." : ""}`);
      await this._reloadAreas();
    } catch (e) { this._showMsg(`Failed to ${action} motion sensor: ` + e.message, true); }
  }

  async _toggleTemp(areaNum, currentlyEnabled, tr) {
    const enable = !currentlyEnabled;
    const action = enable ? "enable" : "disable";
    if (!enable && !confirm(`Disable temperature sensor for Area ${areaNum}?\nThe temperature sensor entity will be removed from HA.`)) return;
    try {
      await this._ws("dynalite_pdeg/set_temp_sensor", { area: areaNum, has_temp: enable });
      this._showMsg(`Temperature sensor ${enable ? "enabled" : "disabled"} for Area ${areaNum}.${enable ? " Temperature entity created." : ""}`);
      await this._reloadAreas();
    } catch (e) { this._showMsg(`Failed to ${action} temperature sensor: ` + e.message, true); }
  }

  async _toggleLux(dev, card) {
    const enable = !dev.has_lux;
    const label  = dev.name || `${dev.model} (Box ${dev.box_number})`;
    if (!enable && !confirm(`Disable lux sensor for ${label}?\nThe illuminance entity will be removed from HA.`)) return;
    try {
      await this._ws("dynalite_pdeg/set_lux_sensor", {
        device_code: dev.device_code,
        box_number:  dev.box_number,
        has_lux:     enable,
      });
      dev.has_lux = enable;
      const btn = card.querySelector(".dp-dev-lux");
      btn.style.background = enable ? "#43a047" : "#9e9e9e";
      btn.title            = enable ? "Lux sensor enabled — click to disable" : "Click to enable illuminance sensor";
      btn.textContent      = `💡 Lux${enable ? " ✓" : ""}`;
      this._showMsg(`Lux sensor ${enable ? "enabled" : "disabled"} for ${label}.${enable ? " Illuminance entity created." : ""}`);
    } catch (e) { this._showMsg("Failed to toggle lux sensor: " + e.message, true); }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  _ws(type, extra = {}) {
    return this._hass.callWS({ type, entry_id: this._entryId, ...extra });
  }

  _showMsg(text, isError = false) {
    const el = this.querySelector("#dp-toast");
    // Reset animation by removing the show class first
    el.classList.remove("dp-toast-show");
    el.className = "dp-msg-" + (isError ? "err" : "ok");   // colour class only
    el.textContent = text;
    // Force a reflow so the transition re-fires even for rapid consecutive calls
    void el.offsetWidth;
    el.classList.add("dp-toast-show");
    clearTimeout(this._msgTimer);
    this._msgTimer = setTimeout(() => {
      el.classList.remove("dp-toast-show");
    }, 5000);
  }

  _esc(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  // ── XML Import ─────────────────────────────────────────────────────────────

  _bindXmlImportEvents() {
    // ── Physical (Devices XML) ──────────────────────────────────────────────
    const physFileInp = this.querySelector("#dp-xml-file-physical");
    const physDiv     = this.querySelector("#dp-xml-import-physical");

    this.querySelector("#dp-xml-btn-physical").addEventListener("click", () => {
      physFileInp.value = "";  // allow re-selecting the same file
      physFileInp.click();
    });

    physFileInp.addEventListener("change", async () => {
      const file = physFileInp.files[0];
      if (!file) return;
      let text;
      try { text = await file.text(); } catch (e) { this._showMsg("Cannot read file: " + e.message, true); return; }
      this._showMsg("Parsing XML…");
      try {
        const r = await this._ws("dynalite_pdeg/parse_xml", { xml_content: text });
        if (r.xml_type !== "devices") {
          this._showMsg(
            `This is a '${r.xml_type}' XML — use "📂 Import XML" in the Logical tab instead.`, true
          );
          return;
        }
        this._xmlPhysicalDevices = r.devices || [];
        this._renderXmlPhysicalPreview();
        physDiv.style.display = "block";
        this._showMsg(`Parsed ${this._xmlPhysicalDevices.length} device(s). Select which to import.`);
      } catch (e) { this._showMsg("Failed to parse XML: " + e.message, true); }
    });

    this.querySelector("#dp-xml-physical-cancel").addEventListener("click", () => {
      physDiv.style.display = "none";
      this._xmlPhysicalDevices = [];
    });
    this.querySelector("#dp-xml-physical-sel-all").addEventListener("click", () => {
      physDiv.querySelectorAll(".dp-xml-chk").forEach(cb => { cb.checked = true; });
    });
    this.querySelector("#dp-xml-physical-desel-all").addEventListener("click", () => {
      physDiv.querySelectorAll(".dp-xml-chk").forEach(cb => { cb.checked = false; });
    });
    this.querySelector("#dp-xml-physical-import").addEventListener("click", () => this._importPhysical());

    // ── Logical (Logical XML) ───────────────────────────────────────────────
    const logFileInp = this.querySelector("#dp-xml-file-logical");
    const logDiv     = this.querySelector("#dp-xml-import-logical");

    this.querySelector("#dp-xml-btn-logical").addEventListener("click", () => {
      logFileInp.value = "";
      logFileInp.click();
    });

    logFileInp.addEventListener("change", async () => {
      const file = logFileInp.files[0];
      if (!file) return;
      let text;
      try { text = await file.text(); } catch (e) { this._showMsg("Cannot read file: " + e.message, true); return; }
      this._showMsg("Parsing XML…");
      try {
        const r = await this._ws("dynalite_pdeg/parse_xml", { xml_content: text });
        if (r.xml_type !== "logical") {
          this._showMsg(
            `This is a '${r.xml_type}' XML — use "📂 Import XML" in the Physical tab instead.`, true
          );
          return;
        }
        this._xmlLogicalAreas = r.areas || [];
        this._renderXmlLogicalPreview();
        logDiv.style.display = "block";
        this._showMsg(`Parsed ${this._xmlLogicalAreas.length} area(s). Select which to import.`);
      } catch (e) { this._showMsg("Failed to parse XML: " + e.message, true); }
    });

    this.querySelector("#dp-xml-logical-cancel").addEventListener("click", () => {
      logDiv.style.display = "none";
      this._xmlLogicalAreas = [];
    });
    this.querySelector("#dp-xml-logical-sel-all").addEventListener("click", () => {
      logDiv.querySelectorAll(".dp-xml-chk").forEach(cb => { cb.checked = true; });
    });
    this.querySelector("#dp-xml-logical-desel-all").addEventListener("click", () => {
      logDiv.querySelectorAll(".dp-xml-chk").forEach(cb => { cb.checked = false; });
    });
    this.querySelector("#dp-xml-logical-import").addEventListener("click", () => this._importLogical());
  }

  _renderXmlLogicalPreview() {
    const list = this.querySelector("#dp-xml-logical-list");
    list.innerHTML = "";
    if (this._xmlLogicalAreas.length === 0) {
      list.innerHTML = '<div class="dp-empty">No areas found in XML.</div>';
      return;
    }
    const existingAreas = new Set(this._areas.map(a => a.area));
    this._xmlLogicalAreas.forEach((ar, idx) => {
      const exists = existingAreas.has(ar.area);
      const item   = document.createElement("div");
      item.style.cssText = "display:flex;align-items:center;gap:10px;padding:8px 12px;" +
        "border-bottom:1px solid var(--divider-color,#f0f0f0);";
      item.innerHTML = `
        <input type="checkbox" class="dp-xml-chk" data-idx="${idx}"${exists ? "" : " checked"}>
        <div style="flex:1;min-width:0;">
          <div style="font-size:14px;font-weight:500;">
            Area ${ar.area}: ${this._esc(ar.name)}
            ${exists
              ? '<span style="font-size:11px;color:#e65100;font-weight:600;margin-left:6px;">EXISTS</span>'
              : ""}
          </div>
          <div style="font-size:12px;color:var(--secondary-text-color,#757575);">
            ${AREA_TYPE_LABELS[ar.area_type] || ar.area_type} &nbsp;·&nbsp;
            ${ar.channels.length} channel(s) &nbsp;·&nbsp; ${ar.preset_count} presets
            ${Object.keys(ar.preset_names || {}).length > 0
              ? `&nbsp;·&nbsp; <span style="color:#43a047;font-weight:500;">🏷 ${Object.keys(ar.preset_names).length} preset name(s)</span>`
              : ""}
          </div>
        </div>`;
      list.appendChild(item);
    });
  }

  _renderXmlPhysicalPreview() {
    const list = this.querySelector("#dp-xml-physical-list");
    list.innerHTML = "";
    if (this._xmlPhysicalDevices.length === 0) {
      list.innerHTML = '<div class="dp-empty">No devices found in XML.</div>';
      return;
    }
    const existingKeys = new Set(this._devices.map(d => `${d.device_code}_${d.box_number}`));
    this._xmlPhysicalDevices.forEach((dev, idx) => {
      const key    = `${dev.device_code}_${dev.box_number}`;
      const exists = existingKeys.has(key);
      const codeHex = dev.device_code.toString(16).toUpperCase().padStart(2, "0");
      const label   = dev.name || dev.model || `Device 0x${codeHex}`;
      const item    = document.createElement("div");
      item.style.cssText = "display:flex;align-items:center;gap:10px;padding:8px 12px;" +
        "border-bottom:1px solid var(--divider-color,#f0f0f0);";
      item.innerHTML = `
        <input type="checkbox" class="dp-xml-chk" data-idx="${idx}"${exists ? "" : " checked"}>
        <div style="flex:1;min-width:0;">
          <div style="font-size:14px;font-weight:500;">
            ${this._esc(label)}
            ${exists
              ? '<span style="font-size:11px;color:#e65100;font-weight:600;margin-left:6px;">EXISTS</span>'
              : ""}
          </div>
          <div style="font-size:12px;color:var(--secondary-text-color,#757575);">
            ${this._esc(dev.model)} &nbsp;·&nbsp;
            Box ${dev.box_number} &nbsp;·&nbsp; Code 0x${codeHex}
            ${dev.is_sensor ? " &nbsp;·&nbsp; Sensor" : ""}
          </div>
        </div>`;
      list.appendChild(item);
    });
  }

  async _importLogical() {
    const overwrite  = this.querySelector("#dp-xml-logical-overwrite").checked;
    const checkboxes = this.querySelectorAll("#dp-xml-logical-list .dp-xml-chk");
    const selected   = [];
    checkboxes.forEach(cb => {
      if (cb.checked) selected.push(this._xmlLogicalAreas[parseInt(cb.dataset.idx)]);
    });
    if (selected.length === 0) { this._showMsg("No areas selected.", true); return; }
    try {
      const r = await this._ws("dynalite_pdeg/import_logical", { areas: selected, overwrite });
      this.querySelector("#dp-xml-import-logical").style.display = "none";
      this._xmlLogicalAreas = [];
      let msg = `Imported ${r.imported} area(s)`;
      if (r.skipped) msg += `, skipped ${r.skipped} (already exist — enable Overwrite to update)`;
      msg += ".";
      if (r.reloading) msg += " Integration reloading…";
      this._showMsg(msg);
      if (r.reloading) {
        setTimeout(() => this._reloadAreas(), 6000);
      } else {
        await this._reloadAreas();
      }
    } catch (e) { this._showMsg("Import failed: " + e.message, true); }
  }

  async _importPhysical() {
    const overwrite  = this.querySelector("#dp-xml-physical-overwrite").checked;
    const checkboxes = this.querySelectorAll("#dp-xml-physical-list .dp-xml-chk");
    const selected   = [];
    checkboxes.forEach(cb => {
      if (cb.checked) selected.push(this._xmlPhysicalDevices[parseInt(cb.dataset.idx)]);
    });
    if (selected.length === 0) { this._showMsg("No devices selected.", true); return; }
    try {
      const r = await this._ws("dynalite_pdeg/import_devices", { devices: selected, overwrite });
      this.querySelector("#dp-xml-import-physical").style.display = "none";
      this._xmlPhysicalDevices = [];
      let msg = `Imported ${r.imported} device(s)`;
      if (r.skipped) msg += `, skipped ${r.skipped} (already exist — enable Overwrite to update)`;
      msg += ".";
      this._showMsg(msg);
      await this._reloadDevices();
    } catch (e) { this._showMsg("Import failed: " + e.message, true); }
  }
}

customElements.define("dynalite-config-panel", DynaliteConfigPanel);
