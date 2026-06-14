import { createApiClient } from "./api.js";
import { clampChargeWeight, halfLotChargeWeight, lotTitle, readyLotCount, stateTone } from "./domain.js";
import { getAppConfig } from "./config.js";
import { readJson, writeJson } from "./storage.js";
import { buildChargePayload, buildReactorActionMarkup, defaultChargeValue, defaultReactorValue, escapeHtml, localDateTimeInputValue, parseRoute } from "./ui-helpers.js";

const config = getAppConfig();
const api = createApiClient(config);
const app = document.getElementById("app");
const UI_PREFS_KEY = "gold-drop-extraction-lab-ui-prefs-v1";

const state = {
  route: parseRoute(window.location.hash || "#/login"),
  auth: { authenticated: false, user: null, permissions: {}, site: null },
  board: null,
  lots: [],
  lot: null,
  run: null,
  charge: null,
  runEvidence: [],
  loading: false,
  toast: "",
  lastCharge: null,
  dialog: null,
  scanStatus: "",
  recentLookup: null,
  blockingError: null, // { message, blockerStageKey, blockerLabel, blockerActionId }
};

let cameraStream = null;
let barcodeDetector = null;
let scanTimer = null;
let lastScannedValue = null;

window.addEventListener("hashchange", onRouteChange);
window.addEventListener("beforeunload", stopCamera);

start().catch((error) => {
  console.error(error);
  showToast(error.message || "Unable to start extraction app");
});

async function start() {
  await bootstrapAuth();
  if (!state.auth.authenticated) {
    navigate("#/login");
    render();
    return;
  }
  if (!window.location.hash || window.location.hash === "#") navigate("#/home");
  await loadRoute();
  render();
}

async function bootstrapAuth() {
  const me = await api.me();
  if (me?.authenticated || me?.user) {
    state.auth = {
      authenticated: true,
      user: me.user || null,
      permissions: me.permissions || {},
      site: me.site || null,
    };
  }
}

async function onRouteChange() {
  const nextRoute = parseRoute(window.location.hash || "#/login");
  if (state.route.name === "scan" && nextRoute.name !== "scan") {
    stopCamera();
  }
  // Clear any run blocker when leaving a run screen
  if (state.route.name === "run" && nextRoute.name !== "run") {
    state.blockingError = null;
  }
  state.route = nextRoute;
  await loadRoute();
  render();
}

async function loadRoute() {
  if (!state.auth.authenticated) return;
  if (["home", "reactors"].includes(state.route.name)) {
    state.board = await api.getBoard(state.route.boardView || "all");
  }
  if (state.route.name === "lots") {
    state.lots = await api.listLots(state.route.query || "");
  }
  if (["lot", "charge"].includes(state.route.name)) {
    state.lot = await api.getLot(state.route.id);
    if (!state.board) state.board = await api.getBoard("all");
  }
  if (state.route.name === "run") {
    const payload = await api.getChargeRun(state.route.chargeId);
    state.run = payload.run;
    state.lot = payload.lot;
    state.charge = payload.charge || null;
    const evidencePayload = await api.getChargeRunEvidence(state.route.chargeId);
    state.runEvidence = Array.isArray(evidencePayload?.evidence) ? evidencePayload.evidence : [];
    if (!state.board) state.board = await api.getBoard("all");
  }
  if (state.route.name === "scan") {
    state.scanStatus = browserScanSupportMessage();
  }
}

function navigate(hash) {
  window.location.hash = hash;
}

function loadUiPrefs() {
  return readJson(UI_PREFS_KEY, { last_charge_weight_lbs: null, last_reactor_number: 1 });
}

function saveUiPrefs(prefs) {
  writeJson(UI_PREFS_KEY, prefs);
}

function focusScanInput() {
  if (state.route.name !== "scan") return;
  window.setTimeout(() => {
    const input = app?.querySelector("#scan-tracking-id");
    input?.focus();
    input?.select();
  }, 0);
}

function preferredChargePreset(maxWeight) {
  return defaultChargeValue(maxWeight, 100);
}

function showToast(message) {
  state.toast = message;
  render();
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    state.toast = "";
    render();
  }, 2800);
}

function shell(content) {
  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-badge">Extraction Lab App</div>
          <h1>Gold Drop</h1>
          <p>Reactor-first workflow for extractors and assistant extractors.</p>
          <p class="subtle">${escapeHtml(state.auth.site?.site_name || "Mock site")}</p>
        </div>
        ${
          state.auth.authenticated
            ? `
          <nav class="nav">
            <a href="#/home" class="${state.route.name === "home" ? "active" : ""}">Home <small>Snapshot</small></a>
            <a href="#/scan" class="${state.route.name === "scan" ? "active" : ""}">Scan / Enter Lot <small>Fast entry</small></a>
            <a href="#/reactors" class="${state.route.name === "reactors" ? "active" : ""}">Reactors <small>Control board</small></a>
            <a href="#/lots" class="${["lots", "lot", "charge"].includes(state.route.name) ? "active" : ""}">Lots <small>Charge queue</small></a>
            <a href="${isAdmin() ? "#/settings" : "javascript:void(0)"}" class="${state.route.name === "settings" ? "active" : ""}" style="${isAdmin() ? "" : "opacity:0.45;pointer-events:none;"}">Settings <small>${isAdmin() ? "Admin" : "Locked"}</small></a>
          </nav>
          <div class="user-card">
            <strong>${escapeHtml(state.auth.user?.display_name || state.auth.user?.username || "")}</strong>
            <span>${escapeHtml(state.auth.user?.role || "operator")}</span>
          </div>
          <div class="actions"><button class="btn btn-secondary" data-action="logout">Log out</button></div>
          `
            : ""
        }
      </aside>
      <main class="content">${content}</main>
    </div>
    ${state.toast ? `<div class="toast">${escapeHtml(state.toast)}</div>` : ""}
    ${state.dialog ? renderDialog() : ""}
  `;
}

function renderDialog() {
  if (state.dialog?.type !== "cancel") return "";
  return `
    <div class="modal-backdrop">
      <div class="modal-card">
        <div class="stack">
          <div class="eyebrow">Cancel charge</div>
          <h3>How should this cancellation be recorded?</h3>
          <p class="subtle">Choose whether the operator intends to abandon the charge or continue by modifying the linked run.</p>
        </div>
        <div class="grid-2">
          <button class="btn btn-danger" data-action="confirm-cancel" data-resolution="abandon">Abandon charge</button>
          <button class="btn btn-primary" data-action="confirm-cancel" data-resolution="modify">Cancel and modify run</button>
        </div>
        <div class="actions"><button class="btn btn-secondary" data-action="close-dialog">Keep current state</button></div>
      </div>
    </div>
  `;
}

function render() {
  if (!app) return;
  app.innerHTML = shell(renderContent());
  bind();
}

function renderContent() {
  if (!state.auth.authenticated) return renderLogin();
  if (state.route.name === "home") return renderHome();
  if (state.route.name === "scan") return renderScan();
  if (state.route.name === "reactors") return renderReactors();
  if (state.route.name === "lots") return renderLots();
  if (state.route.name === "lot") return renderLotDetail();
  if (state.route.name === "charge") return renderChargeForm();
  if (state.route.name === "run") return renderRunExecution();
  if (state.route.name === "settings") return renderSettings();
  return `<div class="empty">Page not found.</div>`;
}

function renderLogin() {
  return `
    <section class="panel auth-panel">
      <div class="stack">
        <div class="brand-badge">Standalone App</div>
        <h1 class="page-title">Extraction Lab Login</h1>
        <p class="subtle">Use your Gold Drop account to open reactor status, lot readiness, and charge controls.</p>
      </div>
      <form class="form" data-form="login">
        <div class="field">
          <label for="username">Username</label>
          <input id="username" name="username" autocomplete="username" required />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password" required />
        </div>
        <div class="actions"><button class="btn btn-primary" type="submit">${state.loading ? "Signing in..." : "Sign in"}</button></div>
      </form>
    </section>
  `;
}

function renderHome() {
  const summary = state.board?.summary || {};
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Extraction Home</h2>
          <div class="meta">Immediate reactor status, ready lots, and the next charge decisions.</div>
        </div>
        <div class="actions">
          <a class="btn btn-primary" href="#/scan">Scan / Enter Lot</a>
          <a class="btn btn-secondary" href="#/reactors">Open board</a>
          <a class="btn btn-secondary" href="#/lots">Browse lots</a>
        </div>
      </div>
      <section class="stat-grid">
        <div class="metric-card"><span class="label">Active reactors</span><strong>${escapeHtml(String(summary.active_reactor_count || 0))}</strong><span>${escapeHtml(String(summary.reactor_count || 0))} configured</span></div>
        <div class="metric-card"><span class="label">Pending charges</span><strong>${escapeHtml(String(summary.pending_charge_count || 0))}</strong><span>${escapeHtml(String(summary.pending_charge_weight_lbs || 0))} lbs queued</span></div>
        <div class="metric-card"><span class="label">Ready lots</span><strong>${escapeHtml(String(summary.ready_lot_count || readyLotCount(state.lots)))}</strong><span>${escapeHtml(String(summary.open_lot_count || 0))} open lots</span></div>
      </section>
      <section class="card">
        <div class="section-head">
          <div>
            <div class="eyebrow">Reactor pulse</div>
            <h3>Active Reactor Board</h3>
          </div>
          <a class="btn btn-secondary" href="#/reactors">Full board</a>
        </div>
        <div class="reactor-grid">${(state.board?.reactor_cards || []).slice(0, 3).map(renderReactorCard).join("")}</div>
      </section>
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderLastChargeCard() {
  if (!state.lastCharge) return "";
  return `
    <section class="card accent">
      <div class="section-head">
        <div>
          <div class="eyebrow">Last charge</div>
          <h3>${escapeHtml(lotTitle(state.lastCharge.lot))}</h3>
        </div>
      </div>
      <p class="subtle">${escapeHtml(String(state.lastCharge.charge?.charged_weight_lbs || 0))} lbs to Reactor ${escapeHtml(String(state.lastCharge.charge?.reactor_number || ""))}</p>
      <div class="actions">
        <a class="btn btn-primary" href="#/runs/charge/${escapeHtml(state.lastCharge.charge?.id || "")}">Open Run</a>
        <a class="btn btn-secondary" href="${escapeHtml(state.lastCharge.next_run_url || "#")}">Open Run in Main App</a>
        <a class="btn btn-secondary" href="#/reactors">Back to Reactors</a>
        <a class="btn btn-secondary" href="#/scan">Charge Another Lot</a>
      </div>
    </section>
  `;
}

function renderScan() {
  const guidance = [
    "Use the iPad in landscape and fill most of the frame with the label.",
    "Bluetooth scanners can type directly into the Tracking ID field below.",
    "Resolved lots open with the last reactor preselected to cut one more tap.",
  ];
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Scan / Enter Lot</h2>
          <div class="meta">Use the camera, a Bluetooth scanner, or manual tracking-ID entry to open a lot charge fast.</div>
        </div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/reactors">Back to Reactors</a>
        </div>
      </div>
      <section class="scan-grid">
        <article class="card scan-card">
          <div class="section-head">
            <div>
              <div class="eyebrow">Camera scan</div>
              <h3>Open the lot charge form from a barcode or QR code</h3>
            </div>
          </div>
          <div class="scan-preview" id="scan-preview">
            <video id="scan-video" playsinline muted></video>
            <div class="scan-empty" id="scan-preview-empty">Camera preview appears here</div>
          </div>
          <p class="subtle" id="scan-status-text">${escapeHtml(state.scanStatus || browserScanSupportMessage())}</p>
          <div class="scan-guidance">
            ${guidance.map((item) => `<div class="guidance-row">${escapeHtml(item)}</div>`).join("")}
          </div>
          <div class="actions">
            <button class="btn btn-primary" type="button" data-action="start-camera">Start camera</button>
            <button class="btn btn-secondary" type="button" data-action="stop-camera">Stop camera</button>
          </div>
        </article>
        <article class="card scan-card">
          <div class="section-head">
            <div>
              <div class="eyebrow">Manual fallback</div>
              <h3>Type or scan a tracking ID into the field below</h3>
            </div>
          </div>
          <form class="form" data-form="scan-lookup">
            <div class="field">
              <label for="scan-tracking-id">Tracking ID</label>
              <input id="scan-tracking-id" name="tracking_id" autocomplete="off" placeholder="LOT-..." enterkeyhint="go" />
            </div>
            <div class="actions">
              <button class="btn btn-primary" type="submit">Open Charge Form</button>
              <a class="btn btn-secondary" href="#/lots">Browse Lots Instead</a>
            </div>
          </form>
          <div class="preset-note">
            <strong>Default charge preset:</strong>
            <span>100 lbs per reactor when the lot has at least 100 lbs remaining.</span>
          </div>
        </article>
      </section>
      ${
        state.recentLookup
          ? `
        <section class="card success-banner">
          <div class="section-head compact">
            <div>
              <div class="eyebrow">Last resolved lot</div>
              <h3>${escapeHtml(state.recentLookup.tracking_id)}</h3>
            </div>
          </div>
          <p class="subtle">${escapeHtml(state.recentLookup.method_label)} opened ${escapeHtml(state.recentLookup.lot_label)}.</p>
          <div class="actions">
            <a class="btn btn-secondary" href="#/lots/${encodeURIComponent(state.recentLookup.lot_id)}/charge">Open charge form again</a>
          </div>
        </section>
      `
          : ""
      }
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderReactors() {
  const currentView = state.board?.board_view || "all";
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Active Reactor Board</h2>
          <div class="meta">Advance charges through the reactor lifecycle without opening the full admin app.</div>
        </div>
        <div class="actions">
          <a class="btn btn-primary" href="#/scan">Scan / Enter Lot</a>
          <a class="btn btn-secondary" href="#/lots">Find lot</a>
        </div>
      </div>
      <section class="card">
        <div class="section-head">
          <div>
            <div class="eyebrow">Board view</div>
            <h3>Filter reactors</h3>
          </div>
        </div>
        <div class="chip-row">
          ${(state.board?.board_view_options || []).map((option) => `<a class="chip ${option.value === currentView ? "active" : ""}" href="#/reactors?board_view=${encodeURIComponent(option.value)}">${escapeHtml(option.label)}</a>`).join("")}
        </div>
      </section>
      <section class="reactor-grid">${(state.board?.reactor_cards || []).map(renderReactorCard).join("") || `<div class="empty">No reactors match this view.</div>`}</section>
      <section class="card">
        <div class="section-head">
          <div>
            <div class="eyebrow">History</div>
            <h3>Reactor History Today</h3>
          </div>
        </div>
        <div class="history-grid">${(state.board?.reactor_history || []).map(renderHistoryCard).join("")}</div>
      </section>
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderReactorCard(card) {
  const current = card.current;
  return `
    <article class="reactor-card tone-${escapeHtml(stateTone(card.state_key))}">
      <div class="reactor-head">
        <div>
          <div class="eyebrow">Reactor ${escapeHtml(String(card.reactor_number))}</div>
          <h3>${escapeHtml(card.state_label)}</h3>
        </div>
        <span class="status-pill">${escapeHtml(card.state_label)}</span>
      </div>
      ${
        current
          ? `
        <div class="stack">
          <strong>${escapeHtml(`${current.supplier_name} - ${current.strain_name}`)}</strong>
          <div class="meta-row"><span>${escapeHtml(current.tracking_id || "No tracking id")}</span><span>${escapeHtml(String(current.charged_weight_lbs || 0))} lbs</span></div>
          <div class="meta-row"><span>${escapeHtml(current.charged_at_label || "")}</span><span>${escapeHtml(current.operator_name || "Unassigned")}</span></div>
          <div class="meta-row"><span>${escapeHtml(current.source_mode || "main app")}</span><span>${escapeHtml(current.run_id ? "Run linked" : "Run not started")}</span></div>
          ${renderActionBar(current)}
        </div>
      `
          : `
        <p class="subtle">${escapeHtml(card.next_step)}</p>
        <div class="meta-row"><span>Queue depth</span><span>${escapeHtml(String(card.pending_count || 0))}</span></div>
      `
      }
    </article>
  `;
}

function renderActionBar(current) {
  return buildReactorActionMarkup(current, escapeHtml);
}

function renderHistoryCard(card) {
  return `
    <article class="history-card">
      <div class="section-head compact">
        <div>
          <div class="eyebrow">Reactor ${escapeHtml(String(card.reactor_number))}</div>
          <strong>${escapeHtml(card.state_label)}</strong>
        </div>
      </div>
      ${card.entries?.length ? `<div class="stack tight">${card.entries.map((entry) => `<div class="history-entry"><strong>${escapeHtml(entry.label)}</strong><span>${escapeHtml(entry.timestamp_label || "")}</span>${entry.charge_id ? `<a class="inline-link" href="#/runs/charge/${escapeHtml(entry.charge_id)}">Open Run</a>` : ""}</div>`).join("")}</div>` : `<p class="subtle">No history yet today.</p>`}
    </article>
  `;
}

function renderLots() {
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Chargeable Lots</h2>
          <div class="meta">Search by tracking id, supplier, strain, or batch. Open a lot to charge it fast.</div>
        </div>
        <div class="actions">
          <a class="btn btn-primary" href="#/scan">Scan / Enter Lot</a>
        </div>
      </div>
      <section class="card">
        <form class="toolbar" data-form="lot-search">
          <input name="query" placeholder="Search lots or scan tracking id" value="${escapeHtml(state.route.query || "")}" />
          <button class="btn btn-primary" type="submit">Search</button>
          <a class="btn btn-secondary" href="#/lots">Clear</a>
        </form>
      </section>
      <section class="lot-grid">
        ${state.lots.length ? state.lots.map(renderLotCard).join("") : `<div class="empty">No lots match this search.</div>`}
      </section>
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderLotCard(lot) {
  return `
    <article class="lot-card ${lot.ready_for_charge ? "ready" : ""}">
      <div class="section-head compact">
        <div>
          <div class="eyebrow">${escapeHtml(lot.tracking_id || "Tracking pending")}</div>
          <h3>${escapeHtml(lotTitle(lot))}</h3>
        </div>
        <span class="status-pill ${lot.ready_for_charge ? "good" : ""}">${lot.ready_for_charge ? "Ready" : "Review"}</span>
      </div>
      <div class="metric-row">
        <div><span>Remaining</span><strong>${escapeHtml(String(lot.remaining_weight_lbs || 0))} lbs</strong></div>
        <div><span>Floor</span><strong>${escapeHtml(lot.floor_state || "")}</strong></div>
        <div><span>Testing</span><strong>${escapeHtml(lot.testing_status || "")}</strong></div>
      </div>
      <div class="actions">
        <a class="btn btn-secondary" href="#/lots/${encodeURIComponent(lot.id)}">Open lot</a>
        <a class="btn btn-primary" href="#/lots/${encodeURIComponent(lot.id)}/charge">Charge</a>
      </div>
    </article>
  `;
}

function renderLotDetail() {
  const lot = state.lot;
  if (!lot) return `<div class="empty">Lot not found.</div>`;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>${escapeHtml(lotTitle(lot))}</h2>
          <div class="meta">${escapeHtml(lot.tracking_id || "No tracking id")} - ${escapeHtml(lot.batch_id || "")}</div>
        </div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/lots">Back to lots</a>
          <a class="btn btn-primary" href="#/lots/${encodeURIComponent(lot.id)}/charge">Charge this lot</a>
        </div>
      </div>
      <section class="card">
        <div class="metric-row">
          <div><span>Remaining</span><strong>${escapeHtml(String(lot.remaining_weight_lbs || 0))} lbs</strong></div>
          <div><span>Potency</span><strong>${escapeHtml(lot.potency_pct == null ? "n/a" : `${lot.potency_pct}%`)}</strong></div>
          <div><span>Floor state</span><strong>${escapeHtml(lot.floor_state || "")}</strong></div>
          <div><span>Prep</span><strong>${lot.milled ? "Milled" : "Not milled"}</strong></div>
        </div>
      </section>
      ${lot.warnings?.length ? `<section class="card warning-stack">${lot.warnings.map((warning) => `<div class="warning-row">${escapeHtml(warning)}</div>`).join("")}</section>` : ""}
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderChargeForm() {
  const lot = state.lot;
  if (!lot) return `<div class="empty">Lot not found.</div>`;
  const maxWeight = Number(lot.remaining_weight_lbs || 0);
  const chargeDefaults = lot.charge_defaults || {};
  const reactorCount = Number(state.board?.summary?.reactor_count || 3);
  const prefs = loadUiPrefs();
  const presetWeight = preferredChargePreset(maxWeight);
  const lastUsedWeight = clampChargeWeight(prefs.last_charge_weight_lbs || 0, maxWeight);
  const defaultReactor = defaultReactorValue(prefs.last_reactor_number || 1, reactorCount);
  const defaultWeight = clampChargeWeight(chargeDefaults.charged_weight_lbs || presetWeight, maxWeight) || presetWeight;
  const defaultTime = chargeDefaults.charged_at || localDateTimeInputValue();
  const lookupContext = state.recentLookup && state.recentLookup.lot_id === lot.id ? state.recentLookup : null;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Start Extraction Charge</h2>
          <div class="meta">${escapeHtml(lot.tracking_id || "No tracking id")} - ${escapeHtml(lotTitle(lot))}</div>
        </div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/scan">Scan Another</a>
          <a class="btn btn-secondary" href="#/lots/${encodeURIComponent(lot.id)}">Back</a>
        </div>
      </div>
      <section class="card charge-hero">
        ${
          lookupContext
            ? `
          <div class="success-banner inline">
            <div class="eyebrow">Scan success</div>
            <strong>${escapeHtml(lookupContext.method_label)}</strong>
            <span class="subtle">${escapeHtml(lookupContext.tracking_id)} resolved and Reactor ${escapeHtml(String(defaultReactor))} is preselected from recent use.</span>
          </div>
        `
            : ""
        }
        <div class="metric-row">
          <div><span>Remaining</span><strong>${escapeHtml(String(maxWeight))} lbs</strong></div>
          <div><span>Testing</span><strong>${escapeHtml(lot.testing_status || "")}</strong></div>
          <div><span>Prep</span><strong>${lot.milled ? "Milled" : "Not milled"}</strong></div>
          <div><span>Floor</span><strong>${escapeHtml(lot.floor_state || "")}</strong></div>
        </div>
        ${lot.warnings?.length ? `<div class="warning-stack">${lot.warnings.map((warning) => `<div class="warning-row">${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
      </section>
      <form class="card charge-form" data-form="charge">
        <input type="hidden" name="lot_id" value="${escapeHtml(lot.id)}" />
        <div class="section-head">
          <div>
            <div class="eyebrow">Charge details</div>
            <h3>Default preset is 100 lbs per reactor when the lot can support it.</h3>
          </div>
        </div>
        <div class="weight-panel">
          <label for="charged_weight_lbs">Charge weight (lbs)</label>
          <div class="weight-display" data-weight-display>${escapeHtml(String(defaultWeight.toFixed(1)))} lbs</div>
          <input id="charged_weight_lbs" name="charged_weight_lbs" type="range" min="0" max="${escapeHtml(String(maxWeight))}" step="0.5" value="${escapeHtml(String(defaultWeight))}" />
          <div class="weight-actions">
            <button class="btn btn-primary" type="button" data-action="set-preset-weight" data-preset="hundred">100 lbs</button>
            <button class="btn btn-secondary" type="button" data-action="set-preset-weight" data-preset="half">Half lot</button>
            <button class="btn btn-secondary" type="button" data-action="set-preset-weight" data-preset="full">Full lot</button>
            <button class="btn btn-secondary" type="button" data-action="set-preset-weight" data-preset="last" ${lastUsedWeight <= 0 ? "disabled" : ""}>Last used</button>
          </div>
          <div class="weight-actions">
            <button class="btn btn-secondary" type="button" data-action="adjust-weight" data-delta="-5">-5</button>
            <button class="btn btn-secondary" type="button" data-action="adjust-weight" data-delta="-1">-1</button>
            <button class="btn btn-secondary" type="button" data-action="adjust-weight" data-delta="1">+1</button>
            <button class="btn btn-secondary" type="button" data-action="adjust-weight" data-delta="5">+5</button>
          </div>
        </div>
        <div class="field">
          <label>Processing reactor</label>
          <div class="reactor-picker">
            ${Array.from({ length: reactorCount }, (_, index) => {
              const reactorNumber = index + 1;
              return `<label class="reactor-option"><input type="radio" name="reactor_number" value="${reactorNumber}" ${reactorNumber === defaultReactor ? "checked" : ""} /><span>Reactor ${reactorNumber}</span></label>`;
            }).join("")}
          </div>
          <div class="subtle">Last used reactor defaults first so repeat charges take one less tap.</div>
        </div>
        <div class="field">
          <label for="charged_at">Charge time</label>
          <div class="toolbar">
            <input id="charged_at" name="charged_at" type="datetime-local" value="${escapeHtml(defaultTime)}" />
            <button class="btn btn-secondary" type="button" data-action="set-now">Now</button>
          </div>
        </div>
        <div class="field">
          <label for="notes">Charge notes</label>
          <textarea id="notes" name="notes" rows="3" placeholder="Optional note about staging, scale evidence, or lot condition"></textarea>
        </div>
        <div class="actions sticky-actions">
          <a class="btn btn-secondary" href="#/scan">Charge Another Lot</a>
          <a class="btn btn-secondary" href="#/lots/${encodeURIComponent(lot.id)}">Cancel</a>
          <button class="btn btn-primary" type="submit">${state.loading ? "Recording..." : "Record Charge"}</button>
        </div>
      </form>
      ${renderLastChargeCard()}
    </div>
  `;
}

function renderTimerField(name, label, value, durationLabel, stopField = "", stopValue = "") {
  return `
    <div class="field timer-card">
      <label for="${escapeHtml(name)}">${escapeHtml(label)}</label>
      <input id="${escapeHtml(name)}" name="${escapeHtml(name)}" type="datetime-local" value="${escapeHtml(value || "")}" />
      ${stopField ? `<input type="hidden" name="${escapeHtml(stopField)}" value="${escapeHtml(stopValue || "")}" />` : ""}
      <div class="weight-actions">
        <button class="btn btn-secondary" type="button" data-action="timer-stamp" data-field="${escapeHtml(name)}">Start / Now</button>
        <button class="btn btn-secondary" type="button" data-action="timer-stop" data-field="${escapeHtml(name)}">Stop / Now</button>
      </div>
      ${durationLabel ? `<div class="subtle">${escapeHtml(durationLabel)}</div>` : ""}
    </div>
  `;
}

function renderRunProgression(run) {
  const progression = run.progression || {};
  const actions = progression.actions || [];
  const bypassActions = progression.bypass_actions || [];
  const bypass = progression.bypass || null;
  return `
    <section class="card">
      <div class="section-head">
        <div>
          <div class="eyebrow">Run progression</div>
          <h3>${escapeHtml(progression.stage_label || "Ready to start")}</h3>
        </div>
      </div>
      <p class="subtle">${escapeHtml(progression.description || "Use the next progression action to guide the extractor through the run.")}</p>
      ${
        run.booth?.history?.length
          ? `<div class="text-sm" style="color:var(--text-muted);margin-top:8px;">Latest checkpoint: ${escapeHtml(run.booth.history[0].event_label || "")} at ${escapeHtml(run.booth.history[0].occurred_at || "")}</div>`
          : ""
      }
      ${progression.completed_at ? `<div class="text-sm" style="color:var(--text-muted);margin-top:8px;">Completed at ${escapeHtml(progression.completed_at)}</div>` : ""}
      ${
        actions.length
          ? `<div class="action-grid" style="margin-top:14px;">${actions
              .map(
                (action) =>
                  `<button class="btn btn-primary" type="button" data-action="run-progression" data-run-action="${escapeHtml(action.action_id)}">${escapeHtml(action.label)}</button>`,
              )
              .join("")}</div>`
          : `<div class="text-sm" style="color:var(--text-muted);margin-top:10px;">No standard progression action is available right now.</div>`
      }
      ${
        bypass && bypass.status === "pending"
          ? `<div class="notice warning" style="margin-top:14px;">Manager bypass requested. Continue only after approval appears here.</div>`
          : ""
      }
      ${
        bypassActions.length
          ? `<div class="bypass-box" style="margin-top:14px;">
              ${bypassActions.some((action) => action.action_id === "request_stage_bypass") ? `<div class="field"><label for="bypass_reason">Bypass Reason</label><textarea id="bypass_reason" name="bypass_reason" rows="2" placeholder="Explain what failed and why manager approval is needed"></textarea></div>` : ""}
              <div class="action-grid">${bypassActions
                .map((action) => `<button class="btn btn-secondary" type="button" data-action="run-progression" data-run-action="${escapeHtml(action.action_id)}">${escapeHtml(action.label)}</button>`)
                .join("")}</div>
            </div>`
          : ""
      }
    </section>
  `;
}

function renderPostExtractionProgression(run) {
  const post = run.post_extraction || {};
  const actions = post.actions || [];
  return `
    <section class="card">
      <div class="section-head">
        <div>
          <div class="eyebrow">Post-extraction handoff</div>
          <h3>${escapeHtml(post.stage_label || "Not started")}</h3>
        </div>
      </div>
      <p class="subtle">${escapeHtml(post.description || "Start the downstream handoff once extraction is complete.")}</p>
      ${post.pathway_label ? `<div class="text-sm" style="color:var(--text-muted);margin-top:8px;">Pathway: ${escapeHtml(post.pathway_label)}</div>` : ""}
      ${
        actions.length
          ? `<div class="action-grid" style="margin-top:14px;">${actions
              .map(
                (action) =>
                  `<button class="btn btn-primary" type="button" data-action="post-extraction-progression" data-post-action="${escapeHtml(action.action_id)}">${escapeHtml(action.label)}</button>`,
              )
              .join("")}</div>`
          : `<div class="text-sm" style="color:var(--text-muted);margin-top:10px;">No downstream handoff action is available right now.</div>`
      }
    </section>
  `;
}

function renderChoiceButtons(field, currentValue, options, accent = "primary") {
  return `
    <input type="hidden" name="${escapeHtml(field)}" value="${escapeHtml(String(currentValue || ""))}" />
    <div class="choice-grid">
      ${options
        .filter((option) => option.value)
        .map(
          (option) =>
            `<button class="btn ${String(currentValue || "") === String(option.value) ? `btn-${accent} is-active` : "btn-secondary"} workflow-choice" type="button" data-action="set-field" data-field="${escapeHtml(field)}" data-value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</button>`,
        )
        .join("")}
    </div>
  `;
}

function renderWorkflowStep(stepNumber, stateKey, eyebrow, title, description, body) {
  const labelMap = {
    done: "Done",
    current: "Current",
    ready: "Ready",
    pending: "Pending",
  };
  // Pending steps collapse to header only — body is not yet actionable.
  // Done steps also hide the body — operator doesn't need to re-read completed work.
  // Current and ready steps show the full body.
  const showBody = stateKey === "current" || stateKey === "ready";
  return `
    <article class="workflow-step state-${escapeHtml(stateKey)}">
      <div class="workflow-step-head">
        <div class="workflow-step-index">${escapeHtml(String(stepNumber))}</div>
        <div class="workflow-step-copy">
          <div class="eyebrow">${escapeHtml(eyebrow)}</div>
          <h3>${escapeHtml(title)}</h3>
          ${showBody ? `<p class="subtle">${escapeHtml(description)}</p>` : ""}
        </div>
        <div class="workflow-step-state">${escapeHtml(labelMap[stateKey] || "Pending")}</div>
      </div>
      ${showBody ? `<div class="workflow-step-body">${body}</div>` : ""}
    </article>
  `;
}

function renderReactorEmptiedAction(charge) {
  if (!charge || charge.status !== "completed" || !state.route.chargeId) return "";
  return `
    <section class="card" style="padding:20px;margin-top:14px;">
      <div class="eyebrow">Reactor availability</div>
      <h3 style="margin-top:6px;">Physical pour-out complete?</h3>
      <p class="subtle">Mark the reactor empty after pour-out so this reactor shows as available on the board and in Floor Ops.</p>
      <button class="btn btn-primary btn-operator-action" type="button"
        data-action="transition-charge"
        data-charge-id="${escapeHtml(state.route.chargeId)}"
        data-target-state="cleared">
        Reactor Emptied
      </button>
    </section>
  `;
}

function renderGuidedDownstreamWorkflow(run) {
  const post = run.post_extraction || {};
  const pathway = run.post_extraction_pathway || "";
  const startAction = (post.actions || []).find((action) => action.action_id === "start_post_extraction");
  const confirmAction = (post.actions || []).find((action) => action.action_id === "confirm_initial_outputs");
  const potPourActive = pathway === "pot_pour_100";
  const minorRunActive = pathway === "minor_run_200";
  const pathwayStep = renderWorkflowStep(
    1,
    pathway ? "done" : "current",
    "Choose the branch",
    "Downstream pathway",
    "Pick the downstream branch before the post-extraction session starts.",
    renderChoiceButtons("post_extraction_pathway", pathway, run.post_extraction_pathway_options || []),
  );

  const handoffStep = renderWorkflowStep(
    2,
    run.post_extraction_started_at ? "done" : pathway ? "current" : "pending",
    "Start the handoff",
    "Post-extraction session",
    "Start the downstream handoff once the extraction run is complete.",
    `
      <div class="field">
        <label for="post_extraction_started_at">Started At</label>
        <input id="post_extraction_started_at" name="post_extraction_started_at" type="datetime-local" value="${escapeHtml(run.post_extraction_started_at || "")}" />
      </div>
      ${run.post_extraction_started_at
          ? `<div class="subtle">Downstream handoff has already started.</div>`
          : pathway && startAction
            ? `<button class="btn btn-primary" type="button" data-action="post-extraction-progression" data-post-action="${escapeHtml(startAction.action_id)}">${escapeHtml(startAction.label)}</button>`
            : `<div class="notice">Choose a downstream pathway above before starting the session.</div>`}
    `,
  );

  const outputsStep = renderWorkflowStep(
    3,
    run.post_extraction_initial_outputs_recorded_at ? "done" : run.post_extraction_started_at ? "current" : "pending",
    "Confirm the split",
    "Initial wet outputs",
    "Record the first wet THCA and wet HTE outputs before the material moves deeper into downstream processing.",
    `
      <div class="grid-2">
        <div class="field">
          <label for="wet_hte_g">Wet HTE (g)</label>
          <input id="wet_hte_g" name="wet_hte_g" type="number" value="${escapeHtml(String(run.wet_hte_g ?? ""))}" min="0" step="0.1" placeholder="Initial wet HTE output" />
        </div>
        <div class="field">
          <label for="wet_thca_g">Wet THCA (g)</label>
          <input id="wet_thca_g" name="wet_thca_g" type="number" value="${escapeHtml(String(run.wet_thca_g ?? ""))}" min="0" step="0.1" placeholder="Initial wet THCA output" />
        </div>
      </div>
      <div class="field">
        <label for="post_extraction_initial_outputs_recorded_at">Confirmed At</label>
        <input id="post_extraction_initial_outputs_recorded_at" name="post_extraction_initial_outputs_recorded_at" type="datetime-local" value="${escapeHtml(run.post_extraction_initial_outputs_recorded_at || "")}" />
      </div>
      ${confirmAction ? `<button class="btn btn-primary" type="button" data-action="post-extraction-progression" data-post-action="${escapeHtml(confirmAction.action_id)}">${escapeHtml(confirmAction.label)}</button>` : `<div class="subtle">Initial outputs are already confirmed.</div>`}
    `,
  );

  const steps = [pathwayStep, handoffStep, outputsStep];

  if (potPourActive) {
    steps.push(
      renderWorkflowStep(
        4,
        run.pot_pour_offgas_completed_at ? "done" : run.pot_pour_offgas_started_at ? "current" : "ready",
        "Pot pour hold",
        "Warm off-gas window",
        "Track the warm off-gas hold for the 100 lb pot pour branch.",
        `
          <div class="grid-2">
            ${renderTimerField("pot_pour_offgas_started_at", "Warm Off-Gas Start", run.pot_pour_offgas_started_at, run.downstream?.pot_pour_offgas_duration_minutes != null ? `${run.downstream.pot_pour_offgas_duration_minutes} minute(s) recorded` : "", "pot_pour_offgas_completed_at", run.pot_pour_offgas_completed_at)}
            <div class="field timer-card">
              <label for="pot_pour_offgas_completed_at_display">Warm Off-Gas End</label>
              <input id="pot_pour_offgas_completed_at_display" type="datetime-local" value="${escapeHtml(run.pot_pour_offgas_completed_at || "")}" readonly />
              <div class="subtle">Stop is captured from the Warm Off-Gas timer.</div>
            </div>
          </div>
        `,
      ),
      renderWorkflowStep(
        5,
        run.pot_pour_centrifuged_at ? "done" : "ready",
        "Pot pour finish",
        "Daily stir + centrifuge handoff",
        "Capture the repeated stir count and the centrifuge handoff to finish the pot pour branch.",
        `
          <div class="grid-2">
            <div class="field counter-card">
              <label style="text-align:center;">Daily Stirs</label>
              <div class="counter-row">
                <button class="btn btn-secondary" type="button" data-action="adjust-count" data-field="pot_pour_daily_stir_count" data-delta="-1">-</button>
                <input type="number" name="pot_pour_daily_stir_count" value="${escapeHtml(String(run.pot_pour_daily_stir_count ?? ""))}" min="0" step="1" />
                <button class="btn btn-secondary" type="button" data-action="adjust-count" data-field="pot_pour_daily_stir_count" data-delta="1">+</button>
              </div>
            </div>
            <div class="field timer-card">
              <label for="pot_pour_centrifuged_at" style="text-align:center;">Centrifuged At</label>
              <input id="pot_pour_centrifuged_at" name="pot_pour_centrifuged_at" type="datetime-local" value="${escapeHtml(run.pot_pour_centrifuged_at || "")}" />
            </div>
          </div>
          ${!run.pot_pour_centrifuged_at ? "" : ""}
          <button class="btn btn-primary btn-operator-action" type="submit"
            style="margin-top:4px;">
            Complete Pot Pour
          </button>
        `,
      ),
    );
  }

  if (minorRunActive) {
    steps.push(
      renderWorkflowStep(
        4,
        run.thca_destination ? "done" : "ready",
        "THCA branch",
        "Oven, mill, and choose destination",
        "Track the THCA branch from oven through the final destination decision.",
        `
          <div class="grid-2">
            ${renderTimerField("thca_oven_started_at", "THCA Oven Start", run.thca_oven_started_at, run.downstream?.thca_oven_duration_minutes != null ? `${run.downstream.thca_oven_duration_minutes} minute(s) recorded` : "", "thca_oven_completed_at", run.thca_oven_completed_at)}
            <div class="field timer-card">
              <label for="thca_oven_completed_at_display">THCA Oven End</label>
              <input id="thca_oven_completed_at_display" type="datetime-local" value="${escapeHtml(run.thca_oven_completed_at || "")}" readonly />
              <div class="subtle">Stop is captured from the THCA Oven timer.</div>
            </div>
          </div>
          <div class="field">
            <label for="thca_milled_at">Milled At</label>
            <input id="thca_milled_at" name="thca_milled_at" type="datetime-local" value="${escapeHtml(run.thca_milled_at || "")}" />
          </div>
          <div class="field">
            <label>THCA Destination</label>
            ${renderChoiceButtons("thca_destination", run.thca_destination, run.thca_destination_options || [])}
          </div>
        `,
      ),
      renderWorkflowStep(
        5,
        run.hte_queue_destination || run.hte_potency_disposition || run.hte_clean_decision ? "current" : "ready",
        "HTE branch",
        "Off-gas, quality decisions, and final queue",
        "Track the HTE side through off-gas, clean/dirty assessment, Prescott handling, and the final queue or hold.",
        `
          <div class="grid-2">
            ${renderTimerField("hte_offgas_started_at", "HTE Off-Gas Start", run.hte_offgas_started_at, run.downstream?.hte_offgas_duration_minutes != null ? `${run.downstream.hte_offgas_duration_minutes} minute(s) recorded` : "", "hte_offgas_completed_at", run.hte_offgas_completed_at)}
            <div class="field timer-card">
              <label for="hte_offgas_completed_at_display">HTE Off-Gas End</label>
              <input id="hte_offgas_completed_at_display" type="datetime-local" value="${escapeHtml(run.hte_offgas_completed_at || "")}" readonly />
              <div class="subtle">Stop is captured from the HTE Off-Gas timer.</div>
            </div>
          </div>
          <div class="field">
            <label>Clean Decision</label>
            ${renderChoiceButtons("hte_clean_decision", run.hte_clean_decision, run.hte_clean_decision_options || [])}
          </div>
          <div class="field">
            <label>Filter Outcome</label>
            ${renderChoiceButtons("hte_filter_outcome", run.hte_filter_outcome, run.hte_filter_outcome_options || [])}
          </div>
          <div class="grid-2">
            <div class="field">
              <label for="hte_prescott_processed_at">Prescott Processed At</label>
              <input id="hte_prescott_processed_at" name="hte_prescott_processed_at" type="datetime-local" value="${escapeHtml(run.hte_prescott_processed_at || "")}" />
            </div>
            <div class="field">
              <label>Potency Disposition</label>
              ${renderChoiceButtons("hte_potency_disposition", run.hte_potency_disposition, run.hte_potency_disposition_options || [])}
            </div>
          </div>
          <div class="field">
            <label>Queue Destination</label>
            ${renderChoiceButtons("hte_queue_destination", run.hte_queue_destination, run.hte_queue_destination_options || [])}
          </div>
        `,
      ),
    );
  }

  return `
    <section class="card workflow-stack">
      <div class="section-head">
        <div>
          <div class="eyebrow">Guided downstream workflow</div>
          <h3>Work top to bottom and save as you move.</h3>
        </div>
      </div>
      <div class="workflow-grid">${steps.join("")}</div>
    </section>
  `;
}


// ---------------------------------------------------------------------------
// ROLE HELPERS
// Gate operator vs supervisor view on the role the API returns.
// "extractor" and "assistant_extractor" get the focused operator view.
// Everything else (manager, supervisor, admin) gets the full supervisor view.
// If the role is unknown we default to operator — safer to show less.
// ---------------------------------------------------------------------------

function isSupervisor() {
  const role = String(state.auth.user?.role || "").toLowerCase();
  return ["manager", "supervisor", "admin", "vp_operations"].includes(role);
}

function isAdmin() {
  const role = String(state.auth.user?.role || "").toLowerCase();
  return ["admin", "super_admin", "vp_operations"].includes(role);
}

// ---------------------------------------------------------------------------
// STAGE SEQUENCE — ordered list used to derive "what comes next"
// Mirrors the stage order in progressionForRun() in api.js.
// If the backend adds stages, add them here in order.
// ---------------------------------------------------------------------------

const STAGE_SEQUENCE = [
  { key: "ready_to_confirm_biomass",         label: "Confirm biomass loaded",        phase: "primary", timer: null },
  { key: "ready_to_check_chiller_temp",      label: "Check chiller temperature",     phase: "primary", timer: null },
  { key: "ready_to_confirm_vacuum",          label: "Confirm vacuum down",          phase: "primary", timer: null },
  { key: "ready_to_record_solvent_charge",   label: "Record solvent charge",         phase: "primary", timer: null },
  { key: "ready_to_start_primary_soak",      label: "Start primary soak",            phase: "primary", timer: null },
  { key: "ready_to_start_mixer",             label: "Start mixer",                   phase: "primary", timer: "primary_soak", targetMinutes: 30 },
  { key: "mixing",                           label: "Mixer running",                 phase: "primary", timer: "mixer",        targetMinutes: 5  },
  { key: "ready_to_confirm_filter_clear",    label: "Confirm filter clear",          phase: "primary", timer: null },
  { key: "ready_to_start_pressurization",    label: "Start pressurization",          phase: "primary", timer: null },
  { key: "ready_to_begin_recovery",          label: "Begin recovery",                phase: "primary", timer: null },
  { key: "ready_to_begin_flush_cycle",       label: "Begin flush cycle",             phase: "primary", timer: null },
  { key: "ready_to_verify_flush_temps",      label: "Verify flush temps",            phase: "flush",   timer: null },
  { key: "ready_to_record_flush_solvent_charge", label: "Record flush solvent charge", phase: "flush", timer: null },
  { key: "ready_to_flush",                   label: "Start flush soak",              phase: "flush",   timer: null },
  { key: "flushing",                         label: "Flush running",                 phase: "flush",   timer: "flush",        targetMinutes: 10 },
  { key: "ready_to_confirm_flow_resumed",    label: "Confirm flow resumed",          phase: "flush",   timer: null },
  { key: "flow_adjustment_required",         label: "Flow adjustment required",      phase: "flush",   timer: null },
  { key: "ready_to_start_final_purge",       label: "Start final purge",             phase: "purge",   timer: null },
  { key: "purging",                          label: "Final purge running",           phase: "purge",   timer: "final_purge",  targetMinutes: null },
  { key: "ready_to_confirm_clarity",         label: "Confirm final clarity",         phase: "purge",   timer: null },
  { key: "clarity_adjustment_required",      label: "More purge work required",      phase: "purge",   timer: null },
  { key: "ready_to_complete_shutdown",       label: "Complete shutdown checklist",   phase: "purge",   timer: null },
  { key: "ready_to_complete",               label: "Mark run complete",              phase: "purge",   timer: null },
];

function nextStageAfter(currentKey) {
  const idx = STAGE_SEQUENCE.findIndex((s) => s.key === currentKey);
  if (idx === -1 || idx >= STAGE_SEQUENCE.length - 1) return null;
  return STAGE_SEQUENCE[idx + 1];
}

// ---------------------------------------------------------------------------
// BLOCKER RESOLUTION
// Maps a progression error message to the stage that is blocking and its
// action so we can surface it inline instead of leaving the operator stuck.
// Each entry: error substring -> { stageKey, label, actionId }
// More specific matches first.
// ---------------------------------------------------------------------------

const BLOCKER_MAP = [
  // Each entry matches a substring of the error message (case-insensitive)
  // and maps it to the stage that needs to be completed to unblock.
  // More specific strings must come before broader ones.
  { match: "biomass",                                  stageKey: "ready_to_confirm_biomass",              label: "Confirm Biomass Loaded",        actionId: "confirm_biomass_loaded" },
  { match: "chiller temperature",                      stageKey: "ready_to_check_chiller_temp",            label: "Check Chiller Temperature",     actionId: "confirm_chiller_temp_met" },
  { match: "vacuum",                                   stageKey: "ready_to_confirm_vacuum",               label: "Confirm Vacuum Down",          actionId: "confirm_vacuum_down" },
  { match: "primary solvent charge before",            stageKey: "ready_to_record_solvent_charge",        label: "Record Solvent Charge",        actionId: "record_solvent_charge" },
  { match: "enter the primary solvent charge",         stageKey: "ready_to_record_solvent_charge",        label: "Record Solvent Charge",        actionId: "record_solvent_charge" },
  { match: "primary soak before starting the mixer",   stageKey: "ready_to_start_primary_soak",           label: "Start Primary Soak",           actionId: "start_primary_soak" },
  { match: "stop the mixer before",                    stageKey: "mixing",                                label: "Stop Mixer",                   actionId: "stop_mixer" },
  { match: "mixer before stopping",                    stageKey: "mixing",                                label: "Start Mixer",                  actionId: "start_mixer" },
  { match: "start the mixer before",                   stageKey: "ready_to_start_mixer",                  label: "Start Mixer",                  actionId: "start_mixer" },
  { match: "both flush temperatures",                  stageKey: "ready_to_verify_flush_temps",           label: "Verify Flush Temps",           actionId: "verify_flush_temps" },
  { match: "chiller temperature must be",              stageKey: "ready_to_verify_flush_temps",           label: "Verify Flush Temps",           actionId: "verify_flush_temps" },
  { match: "enter the flush solvent charge",           stageKey: "ready_to_record_flush_solvent_charge",  label: "Record Flush Solvent Charge",  actionId: "record_flush_solvent_charge" },
  { match: "flush cycle before starting the flush",    stageKey: "ready_to_flush",                        label: "Start Flush",                  actionId: "start_flush" },
  { match: "start the flush before",                   stageKey: "ready_to_flush",                        label: "Start Flush",                  actionId: "start_flush" },
  { match: "flow resumed",                             stageKey: "ready_to_confirm_flow_resumed",         label: "Confirm Flow Resumed",         actionId: "confirm_flow_resumed" },
  { match: "post-extraction pathway before starting",   stageKey: "post_extraction_pathway",               label: "Choose Downstream Pathway",    actionId: "" }, // no action — operator must pick from step 1
  { match: "start final purge before",                 stageKey: "ready_to_start_final_purge",            label: "Start Final Purge",            actionId: "start_final_purge" },
  { match: "shutdown checklist before completing",     stageKey: "ready_to_complete_shutdown",            label: "Complete Shutdown Checklist",  actionId: "complete_shutdown" },
];

function resolveBlocker(errorMessage) {
  if (!errorMessage) return null;
  const lower = errorMessage.toLowerCase();
  const match = BLOCKER_MAP.find((entry) => lower.includes(entry.match.toLowerCase()));
  if (!match) return null;
  return { message: errorMessage, stageKey: match.stageKey, label: match.label, actionId: match.actionId };
}

function renderBlockerCard(blocker) {
  if (!blocker) return "";
  return `
    <div class="blocker-card">
      <div class="blocker-icon">&#9888;</div>
      <div class="blocker-body">
        <div class="blocker-title">Step required before continuing</div>
        <p class="blocker-message">${escapeHtml(blocker.message)}</p>
        <button class="btn btn-primary btn-operator-action" type="button"
          data-action="run-progression"
          data-run-action="${escapeHtml(blocker.actionId)}">
          ${escapeHtml(blocker.label)}
        </button>
      </div>
    </div>
  `;
}


// ---------------------------------------------------------------------------
// PHASE CLASSIFICATION — unchanged from previous version
// ---------------------------------------------------------------------------

const PRIMARY_STAGES = new Set([
  "pending", "vacuum_confirmed", "solvent_charged", "soaking",
  "ready_to_start_mixer", "mixing", "filter_cleared", "pressurizing",
  "recovering", "ready_to_record_solvent_charge", "ready_to_confirm_vacuum",
  "ready_to_start_primary_soak", "ready_to_confirm_filter_clear",
  "ready_to_start_pressurization", "ready_to_begin_recovery",
  "ready_to_begin_flush_cycle",
]);

const FLUSH_STAGES = new Set([
  "flush_setup", "ready_to_verify_flush_temps",
  "ready_to_record_flush_solvent_charge", "ready_to_flush",
  "flushing", "ready_to_confirm_flow_resumed", "flow_adjustment_required",
]);

const PURGE_STAGES = new Set([
  "purging", "ready_to_confirm_clarity", "clarity_adjustment_required",
  "ready_to_complete_shutdown", "ready_to_start_final_purge",
  "ready_to_complete",
]);

function classifyPhase(run) {
  if (run.run_completed_at) return "post_extraction";
  const stageKey = resolvedStageKey(run);
  if (FLUSH_STAGES.has(stageKey)) return "flush";
  if (PURGE_STAGES.has(stageKey)) return "purge";
  return "primary";
}

function resolvedStageKey(run) {
  const progressionActions = (run.progression?.actions || []).map((a) => a.action_id);
  let stageKey = run.progression?.stage_key || "";
  if (progressionActions.includes("record_solvent_charge"))        stageKey = "ready_to_record_solvent_charge";
  if (progressionActions.includes("verify_flush_temps"))           stageKey = "ready_to_verify_flush_temps";
  if (progressionActions.includes("record_flush_solvent_charge"))  stageKey = "ready_to_record_flush_solvent_charge";
  if (progressionActions.includes("confirm_flow_resumed"))         stageKey = "ready_to_confirm_flow_resumed";
  if (progressionActions.includes("confirm_final_clarity"))        stageKey = "ready_to_confirm_clarity";
  if (progressionActions.includes("complete_shutdown"))            stageKey = "ready_to_complete_shutdown";
  return stageKey;
}

// ---------------------------------------------------------------------------
// TIMING CONTROL CARD — unchanged helper
// ---------------------------------------------------------------------------

function renderTimingControlCard(timing) {
  if (!timing) return "";
  const statusLabels = {
    not_started: "Not started", active: "Active",
    active_on_track: "Active / on track", active_target_reached: "Active / target reached",
    recorded: "Recorded", on_target: "On target", short: "Short",
  };
  const summary =
    timing.actual_minutes != null ? `${timing.actual_minutes} min recorded`
    : timing.active_minutes != null ? `${timing.active_minutes} min elapsed`
    : "Not started";
  const target = timing.target_minutes != null ? `${timing.target_minutes} min target` : "";
  const delta =
    timing.delta_minutes == null ? ""
    : timing.delta_minutes >= 0 ? `${timing.delta_minutes} min over`
    : `${Math.abs(timing.delta_minutes)} min under`;
  return `
    <div class="timing-chip">
      <span class="timing-chip-label">${escapeHtml(timing.label || "Timer")}</span>
      <strong>${escapeHtml(statusLabels[timing.status] || "Pending")}</strong>
      <span class="subtle">${escapeHtml(summary)}${target ? ` · ${target}` : ""}${delta ? ` · ${delta}` : ""}</span>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// CHECKPOINT INPUTS — same logic, now a clean helper
// ---------------------------------------------------------------------------

function renderCheckpointInputs(run) {
  const stageKey = resolvedStageKey(run);
  const booth = run.booth || {};
  const map = {
    ready_to_confirm_biomass: `
      <div class="notice" style="margin-bottom:4px;">Confirm that biomass is physically loaded in the reactor before proceeding.</div>`,
    ready_to_check_chiller_temp: `
      <div class="field">
        <label for="chiller_check_actual_temp_c">Actual Chiller Temperature (°C)</label>
        <input id="chiller_check_actual_temp_c" name="chiller_check_actual_temp_c" type="number"
          value="${escapeHtml(String(run.chiller_check_actual_temp_c ?? ""))}"
          step="0.1" placeholder="-40 or below" />
      </div>
      ${run.chiller_out_of_spec ? `
        <div class="notice warning">⚠ This run proceeded out of spec. Supervisor has been notified.</div>` : ""}`,
    ready_to_start_mixer: `
      <div class="field"><label for="primary_soak_short_reason">Reason if starting mixer early</label>
      <textarea id="primary_soak_short_reason" name="primary_soak_short_reason" rows="2"></textarea></div>`,
    mixing: `
      <div class="field"><label for="mixer_short_reason">Reason if stopping mixer early</label>
      <textarea id="mixer_short_reason" name="mixer_short_reason" rows="2"></textarea></div>`,
    flushing: `
      <div class="field"><label for="flush_short_reason">Reason if stopping flush early</label>
      <textarea id="flush_short_reason" name="flush_short_reason" rows="2"></textarea></div>`,
    purging: `
      <div class="field"><label for="final_purge_short_reason">Reason if stopping purge early</label>
      <textarea id="final_purge_short_reason" name="final_purge_short_reason" rows="2"></textarea></div>`,
    ready_to_record_solvent_charge: `
      <div class="field"><label for="primary_solvent_charge_lbs">Primary Solvent Charge (lbs)</label>
      <input id="primary_solvent_charge_lbs" name="primary_solvent_charge_lbs" type="number"
        value="${escapeHtml(String(run.primary_solvent_charge_lbs ?? ""))}" min="0" step="0.1" placeholder="500" /></div>`,
    ready_to_verify_flush_temps: `
      <div class="grid-2">
        <div class="field"><label for="flush_solvent_chiller_temp_f">Chiller Temp (°F)</label>
        <input id="flush_solvent_chiller_temp_f" name="flush_solvent_chiller_temp_f" type="number"
          value="${escapeHtml(String(booth.flush_solvent_chiller_temp_f ?? ""))}" step="0.1" placeholder="-40 or below" /></div>
        <div class="field"><label for="flush_plate_temp_f">Plate Temp (°F)</label>
        <input id="flush_plate_temp_f" name="flush_plate_temp_f" type="number"
          value="${escapeHtml(String(booth.flush_plate_temp_f ?? ""))}" step="0.1" placeholder="Plate temp" /></div>
      </div>
      <div class="field"><label><input type="checkbox" name="flush_temp_slack_post_confirmed" value="1"
        ${booth.flush_temp_slack_post_confirmed_at ? "checked" : ""}> Posted to Slack</label></div>`,
    ready_to_record_flush_solvent_charge: `
      <div class="field"><label for="flush_solvent_charge_lbs">Flush Solvent Charge (lbs)</label>
      <input id="flush_solvent_charge_lbs" name="flush_solvent_charge_lbs" type="number"
        value="${escapeHtml(String(booth.flush_solvent_charge_lbs ?? ""))}" min="0" step="0.1" placeholder="500" /></div>`,
    ready_to_confirm_flow_resumed: `
      <div class="field"><label>Flow Resumed</label>
      ${renderChoiceButtons("flow_resumed_decision", run.flow_resumed_decision || booth.flow_resumed_decision || "", [
        { value: "", label: "Not set" }, { value: "yes", label: "Yes" }, { value: "no_adjusting", label: "Still adjusting" },
      ])}</div>
      <div class="field"><label for="flow_adjustment_reason">Reason if still adjusting</label>
      <textarea id="flow_adjustment_reason" name="flow_adjustment_reason" rows="2"></textarea></div>`,
    ready_to_confirm_clarity: `
      <div class="field"><label>Final Clarity</label>
      ${renderChoiceButtons("final_clarity_decision", run.final_clarity_decision || booth.final_clarity_decision || "", [
        { value: "", label: "Not set" }, { value: "yes", label: "Clear enough" }, { value: "not_yet", label: "Not yet" },
      ])}</div>
      <div class="field"><label for="final_clarity_reason">Reason if not clear</label>
      <textarea id="final_clarity_reason" name="final_clarity_reason" rows="2"></textarea></div>`,
    ready_to_complete_shutdown: `
      <div class="shutdown-checklist">
        <label>Shutdown Checklist</label>
        <label><input type="checkbox" name="shutdown_recovery_inlets_closed" value="1"
          ${booth.final_recovery_inlets_closed_at ? "checked" : ""}> Recovery inlets closed</label>
        <label><input type="checkbox" name="shutdown_filtration_pumpdown_started" value="1"
          ${booth.filtration_pumpdown_started_at ? "checked" : ""}> Filtration pump-down started</label>
        <label><input type="checkbox" name="shutdown_nitrogen_off" value="1"
          ${booth.nitrogen_turned_off_at ? "checked" : ""}> Nitrogen off</label>
        <label><input type="checkbox" name="shutdown_dewax_inlet_closed" value="1"
          ${booth.dewax_inlet_closed_at ? "checked" : ""}> Dewax inlet closed</label>
      </div>`,
  };
  return map[stageKey] || "";
}

// ---------------------------------------------------------------------------
// RELEVANT TIMER — only show the timer that matters right now.
// One timing chip, not four. Chosen based on the current stage.
// ---------------------------------------------------------------------------

function renderRelevantTimer(run) {
  const stageKey = resolvedStageKey(run);
  const timings = run.timing_controls || {};
  const timerMap = {
    ready_to_start_mixer:          timings.primary_soak,
    mixing:                        timings.mixer,
    flushing:                      timings.flush,
    purging:                       timings.final_purge,
    ready_to_confirm_flow_resumed: timings.flush,
    ready_to_confirm_clarity:      timings.final_purge,
  };
  const timing = timerMap[stageKey];
  if (!timing) return "";
  return `<div class="current-timer">${renderTimingControlCard(timing)}</div>`;
}

// ---------------------------------------------------------------------------
// NEXT STEP HINT — one line below the action button.
// Shows what comes immediately after the current step, with timer target
// if applicable. Gives the operator just enough lookahead without clutter.
// ---------------------------------------------------------------------------

function renderNextStepHint(run) {
  const stageKey = resolvedStageKey(run);
  const next = nextStageAfter(stageKey);
  if (!next) return "";
  const timerNote = next.targetMinutes ? ` · ${next.targetMinutes} min target` : "";
  return `
    <div class="next-step-hint">
      <span class="subtle">Next: ${escapeHtml(next.label)}${escapeHtml(timerNote)}</span>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// OTHER REACTORS STRIP — ambient awareness, not navigation.
// Shows other active reactors and their current stage in a compact bar.
// Only shown when there are other active reactors.
// ---------------------------------------------------------------------------

function renderOtherReactorsStrip(currentReactorNumber) {
  const cards = (state.board?.reactor_cards || []).filter(
    (card) => card.reactor_number !== Number(currentReactorNumber) && card.current
  );
  if (!cards.length) return "";
  return `
    <div class="other-reactors-strip">
      ${cards.map((card) => `
        <a class="other-reactor-chip" href="#/runs/charge/${escapeHtml(card.current?.charge_id || "")}">
          <span class="other-reactor-number">R${escapeHtml(String(card.reactor_number))}</span>
          <span>${escapeHtml(card.current?.strain_name || "Active")}</span>
          <span class="subtle">${escapeHtml(card.state_label)}</span>
        </a>
      `).join("")}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// BOOTH EVIDENCE — unchanged, standalone helper
// ---------------------------------------------------------------------------

function renderBoothEvidence(run) {
  const booth = run.booth || {};
  const counts = booth.evidence_counts || {};
  const evidenceRows = Array.isArray(state.runEvidence) ? state.runEvidence : [];
  return `
    <div class="booth-evidence-block">
      <div class="grid-2">
        <form class="field" data-form="run-evidence" data-evidence-type="solvent_chiller_temp_photo">
          <label for="solvent_chiller_temp_photo">Solvent Chiller Temp Photo</label>
          <input id="solvent_chiller_temp_photo" name="photos" type="file" accept="image/*" multiple />
          <div class="subtle">${escapeHtml(String(counts.solvent_chiller_temp_photo || 0))} file(s) on record.</div>
          <button class="btn btn-secondary" type="submit">Upload Chiller Photo</button>
        </form>
        <form class="field" data-form="run-evidence" data-evidence-type="plate_temp_photo">
          <label for="plate_temp_photo">Plate Temp Photo</label>
          <input id="plate_temp_photo" name="photos" type="file" accept="image/*" multiple />
          <div class="subtle">${escapeHtml(String(counts.plate_temp_photo || 0))} file(s) on record.</div>
          <button class="btn btn-secondary" type="submit">Upload Plate Photo</button>
        </form>
      </div>
      ${evidenceRows.length
        ? `<div class="stack" style="margin-top:16px;">${evidenceRows.map((row) => `
            <div class="card" style="padding:12px 14px;">
              <div><strong>${escapeHtml(String(row.evidence_type || "").replaceAll("_", " "))}</strong></div>
              <div class="subtle">${escapeHtml(row.captured_at || "")}</div>
              <div class="subtle">${escapeHtml(row.file_path || row.url || "")}</div>
            </div>`).join("")}</div>`
        : `<div class="subtle" style="margin-top:12px;">No booth evidence uploaded yet.</div>`}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// SUPERVISOR FULL VIEW — everything visible, for managers reviewing runs.
// Separate render path so operator view stays clean and unspoiled.
// ---------------------------------------------------------------------------

function renderRunExecutionSupervisor(run, lot) {
  const inherited = run.inherited || {};
  const booth = run.booth || {};
  const timings = run.timing_controls || {};
  const summaryRows = [
    ["Primary solvent", booth.primary_solvent_charge_lbs != null ? `${booth.primary_solvent_charge_lbs} lbs` : "—"],
    ["Flush temps", booth.flush_temp_verified_at ? `${booth.flush_solvent_chiller_temp_f}°F / ${booth.flush_plate_temp_f}°F` : "—"],
    ["Flush solvent", booth.flush_solvent_charge_lbs != null ? `${booth.flush_solvent_charge_lbs} lbs` : "—"],
    ["Flow resumed", booth.flow_resumed_decision || "—"],
    ["Final clarity", booth.final_clarity_decision || "—"],
    ["Shutdown", booth.booth_process_completed_at ? "Done" : "—"],
  ];
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>Run Execution <span class="supervisor-badge">Supervisor</span></h2>
          <div class="meta">${escapeHtml(inherited.tracking_id || "")} — Reactor ${escapeHtml(String(run.reactor_number || ""))}</div>
        </div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/reactors">Back to Reactors</a>
          <a class="btn btn-secondary" href="${escapeHtml(run.open_main_app_url || "#")}">Open in Main App</a>
        </div>
      </div>

      <section class="card charge-hero">
        <div class="metric-row">
          <div><span>Strain</span><strong>${escapeHtml(inherited.strain_name || lotTitle(lot || {}))}</strong></div>
          <div><span>Source</span><strong>${escapeHtml(inherited.source_summary || "")}</strong></div>
          <div><span>Biomass</span><strong>${escapeHtml(String(run.bio_in_reactor_lbs || 0))} lbs</strong></div>
          <div><span>Charged</span><strong>${escapeHtml(inherited.charged_at_label || "")}</strong></div>
        </div>
        <div class="run-summary-strip">
          ${summaryRows.map(([label, value]) => `
            <div class="run-summary-item">
              <span class="subtle">${escapeHtml(label)}</span>
              <strong>${escapeHtml(String(value))}</strong>
            </div>`).join("")}
        </div>
      </section>

      <section class="card">
        <div class="section-head"><div><div class="eyebrow">All Timers</div><h3>Booth timing against SOP targets</h3></div></div>
        <div class="grid-2">
          ${renderTimingControlCard(timings.primary_soak)}
          ${renderTimingControlCard(timings.mixer)}
          ${renderTimingControlCard(timings.flush)}
          ${renderTimingControlCard(timings.final_purge)}
        </div>
      </section>

      <form class="card charge-form" data-form="run-execution">
        <input type="hidden" name="run_completed_at" value="${escapeHtml(run.run_completed_at || "")}" />
        <input type="hidden" name="post_extraction_pathway" value="${escapeHtml(run.post_extraction_pathway || "")}" />
        <div class="section-head"><div><div class="eyebrow">Current checkpoint</div>
          <h3>${escapeHtml(run.progression?.stage_label || "")}</h3></div></div>
        <p class="subtle">${escapeHtml(run.progression?.description || "")}</p>
        ${renderCheckpointInputs(run)}
        ${renderRunProgression(run)}
        ${run.run_completed_at ? renderPostExtractionProgression(run) : ""}
        ${run.run_completed_at ? renderGuidedDownstreamWorkflow(run) : ""}
        ${run.run_completed_at ? renderReactorEmptiedAction(state.charge) : ""}
        <div class="actions sticky-actions">
          <a class="btn btn-secondary" href="#/reactors">Back to Reactors</a>
          <a class="btn btn-secondary" href="${escapeHtml(run.open_main_app_url || "#")}">Open in Main App</a>
          ${run.run_completed_at ? "" : `<button class="btn btn-primary" type="submit">${state.loading ? "Saving..." : "Save Run"}</button>`}
        </div>
      </form>
      ${renderBoothEvidence(run)}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// OPERATOR FOCUSED VIEW — absolute minimum visible at any moment.
//
// Operator sees:
//   1. Minimal header: lot + reactor + strain (one line)
//   2. Other active reactors strip (ambient, compact)
//   3. Current phase label (Primary / Flush / Final Purge / Post-Extraction)
//   4. Relevant timer only (the one that matters right now)
//   5. Step instruction (one sentence from progression.description)
//   6. Checkpoint inputs if needed (e.g. solvent weight, temps)
//   7. ONE big primary action button — full width
//   8. "Next: ___" hint (one line)
//   9. Bypass section collapsed by default, only visible if needed
// ---------------------------------------------------------------------------

function renderRunExecutionOperator(run, lot) {
  const inherited = run.inherited || {};
  const progression = run.progression || {};
  const actions = progression.actions || [];
  const bypassActions = progression.bypass_actions || [];
  const bypass = progression.bypass || null;
  const activePhase = classifyPhase(run);

  const phaseLabels = {
    primary: "Primary Extraction",
    flush: "Flush Cycle",
    purge: "Final Purge",
    post_extraction: "Post-Extraction",
  };

  const checkpointInputs = renderCheckpointInputs(run);
  const relevantTimer = renderRelevantTimer(run);
  const needsEvidenceUpload = activePhase === "flush";

  return `
    <div class="layout-grid operator-layout">

      <div class="operator-topbar">
        <div class="operator-topbar-left">
          <span class="operator-lot">${escapeHtml(inherited.tracking_id || "")}</span>
          <span class="operator-sep">·</span>
          <span>Reactor ${escapeHtml(String(run.reactor_number || ""))}</span>
          <span class="operator-sep">·</span>
          <span>${escapeHtml(inherited.strain_name || lotTitle(lot || {}))}</span>
        </div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/reactors">Reactors</a>
          <a class="btn btn-secondary" href="${escapeHtml(run.open_main_app_url || "#")}">Main App</a>
        </div>
      </div>

      ${renderOtherReactorsStrip(run.reactor_number)}

      <form class="operator-focus-card" data-form="run-execution">
        <input type="hidden" name="run_completed_at" value="${escapeHtml(run.run_completed_at || "")}" />
        <input type="hidden" name="post_extraction_pathway" value="${escapeHtml(run.post_extraction_pathway || "")}" />
        <input type="hidden" name="chiller_check_actual_temp_c" value="${escapeHtml(String(run.chiller_check_actual_temp_c ?? ""))}" />

        ${renderBlockerCard(state.blockingError)}

        <div class="operator-phase-label">${escapeHtml(phaseLabels[activePhase] || "")}</div>

        <h2 class="operator-step-title">${escapeHtml(progression.stage_label || "")}</h2>

        <p class="operator-step-desc">${escapeHtml(progression.description || "")}</p>

        ${relevantTimer}

        ${checkpointInputs ? `<div class="operator-inputs">${checkpointInputs}</div>` : ""}

        ${needsEvidenceUpload ? `
          <div class="operator-evidence">
            <div class="eyebrow" style="margin-bottom:8px;">Required Evidence</div>
            ${renderBoothEvidence(run)}
          </div>` : ""}

        ${actions.length ? `
          <div class="operator-actions">
            ${actions.map((action) => `
              <button class="btn btn-primary btn-operator-action" type="button"
                data-action="run-progression"
                data-run-action="${escapeHtml(action.action_id)}">
                ${escapeHtml(action.label)}
              </button>`).join("")}
          </div>` : `<div class="subtle">No action available right now.</div>`}

        ${renderNextStepHint(run)}

        ${bypass?.status === "pending" ? `
          <div class="notice warning" style="margin-top:14px;">
            Manager bypass requested. Continue only after approval.
          </div>` : ""}

        ${bypassActions.length ? `
          <details class="bypass-details">
            <summary>Request manager bypass</summary>
            <div class="bypass-box">
              ${bypassActions.some((a) => a.action_id === "request_stage_bypass") ? `
                <div class="field">
                  <label for="bypass_reason">Bypass reason</label>
                  <textarea id="bypass_reason" name="bypass_reason" rows="2"
                    placeholder="Explain what failed and why approval is needed"></textarea>
                </div>` : ""}
              <div class="action-grid">
                ${bypassActions.map((action) => `
                  <button class="btn btn-secondary" type="button"
                    data-action="run-progression"
                    data-run-action="${escapeHtml(action.action_id)}">
                    ${escapeHtml(action.label)}
                  </button>`).join("")}
              </div>
            </div>
          </details>` : ""}

        ${run.run_completed_at ? `
          <div class="card" style="padding:20px;margin-top:14px;">
            ${renderGuidedDownstreamWorkflow(run)}
          </div>
          ${renderReactorEmptiedAction(state.charge)}` : `
          <div class="operator-save-bar">
            <button class="btn btn-secondary" type="submit">${state.loading ? "Saving..." : "Save"}</button>
          </div>`}
      </form>

    </div>
  `;
}

// ---------------------------------------------------------------------------
// SETTINGS PANEL — admin only
// ---------------------------------------------------------------------------

function renderSettings() {
  if (!isAdmin()) {
    return `
      <div class="layout-grid">
        <div class="card" style="padding:24px;text-align:center;">
          <div class="eyebrow" style="margin-bottom:8px;">Settings</div>
          <p>Settings are managed by administrators.</p>
        </div>
      </div>`;
  }
  const threshold = state.settings?.chiller_temp_threshold_c ?? -40;
  const saved = state.settings?.saved;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>Settings</h2><div class="meta">Extraction Lab — Admin</div></div>
      </div>
      ${saved ? `<div class="notice good">Settings saved.</div>` : ""}
      <form class="card" data-form="settings" style="display:grid;gap:20px;padding:24px;">
        <section style="display:grid;gap:14px;">
          <div class="eyebrow">Pre-Extraction Safety Thresholds</div>
          <div class="field">
            <label for="chiller_temp_threshold_c">Chiller Temperature Threshold (°C)</label>
            <input id="chiller_temp_threshold_c" name="chiller_temp_threshold_c"
              type="number" step="0.5" placeholder="-40"
              value="${escapeHtml(String(threshold))}" />
            <div class="subtle" style="margin-top:6px;">
              Operators must confirm the chiller is at or below this temperature before solvent charging.
              Default: −40°C. If an operator proceeds above this threshold, a critical supervisor
              notification is sent automatically via Slack.
            </div>
          </div>
        </section>
        <div class="actions">
          <button class="btn btn-primary" type="submit">${state.loading ? "Saving..." : "Save Settings"}</button>
        </div>
      </form>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// MAIN ENTRY POINT — routes to operator or supervisor view based on role
// ---------------------------------------------------------------------------

function renderRunExecution() {
  const run = state.run;
  const lot = state.lot;
  if (!run || !state.route.chargeId) return `<div class="empty">Run not found.</div>`;
  if (isSupervisor()) return renderRunExecutionSupervisor(run, lot);
  return renderRunExecutionOperator(run, lot);
}

function bind() {
  app?.querySelectorAll("[data-action='logout']").forEach((button) => button.addEventListener("click", handleLogout));
  app?.querySelector("form[data-form='login']")?.addEventListener("submit", handleLogin);
  app?.querySelector("form[data-form='lot-search']")?.addEventListener("submit", handleLotSearch);
  app?.querySelector("form[data-form='scan-lookup']")?.addEventListener("submit", handleScanLookup);
  app?.querySelector("form[data-form='charge']")?.addEventListener("submit", handleChargeSubmit);
  app?.querySelector("form[data-form='run-execution']")?.addEventListener("submit", handleRunSubmit);
  app?.querySelector("form[data-form='settings']")?.addEventListener("submit", handleSettingsSubmit);
  app?.querySelector("form[data-form='downstream-workflow']")?.addEventListener("submit", handleDownstreamSubmit);
  app?.querySelectorAll("form[data-form='run-evidence']").forEach((form) => form.addEventListener("submit", handleRunEvidenceSubmit));
  app?.querySelectorAll("[data-action='adjust-weight']").forEach((button) => button.addEventListener("click", handleWeightAdjust));
  app?.querySelectorAll("[data-action='adjust-count']").forEach((button) => button.addEventListener("click", handleCountAdjust));
  app?.querySelectorAll("[data-action='set-field']").forEach((button) => button.addEventListener("click", handleSetFieldValue));
  app?.querySelectorAll("[data-action='set-preset-weight']").forEach((button) => button.addEventListener("click", handlePresetWeight));
  app?.querySelector("[data-action='set-now']")?.addEventListener("click", handleSetNow);
  app?.querySelectorAll("[data-action='timer-stamp']").forEach((button) => button.addEventListener("click", handleTimerStamp));
  app?.querySelectorAll("[data-action='timer-stop']").forEach((button) => button.addEventListener("click", handleTimerStop));
  app?.querySelector("[data-action='start-camera']")?.addEventListener("click", startCamera);
  app?.querySelector("[data-action='stop-camera']")?.addEventListener("click", stopCamera);
  app?.querySelectorAll("[data-action='transition-charge']").forEach((button) => button.addEventListener("click", handleTransition));
  app?.querySelectorAll("[data-action='run-progression']").forEach((button) => button.addEventListener("click", handleRunProgression));
  app?.querySelectorAll("[data-action='post-extraction-progression']").forEach((button) => button.addEventListener("click", handlePostExtractionProgression));
  app?.querySelector("[data-action='close-dialog']")?.addEventListener("click", () => {
    state.dialog = null;
    render();
  });
  app?.querySelectorAll("[data-action='confirm-cancel']").forEach((button) => button.addEventListener("click", handleConfirmCancel));
  app?.querySelector("input[type='range'][name='charged_weight_lbs']")?.addEventListener("input", syncWeightDisplay);
  app?.querySelector("input[type='range'][name='biomass_blend_milled_pct']")?.addEventListener("input", syncBlendDisplay);
  focusScanInput();
  syncBlendDisplay();
}

async function handleLogin(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  state.loading = true;
  render();
  try {
    const session = await api.login(String(form.get("username") || ""), String(form.get("password") || ""));
    state.auth = {
      authenticated: true,
      user: session.user || null,
      permissions: session.permissions || {},
      site: session.site || null,
    };
    navigate("#/home");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to log in");
  } finally {
    state.loading = false;
    render();
  }
}

async function handleLogout() {
  stopCamera();
  await api.logout();
  state.auth = { authenticated: false, user: null, permissions: {}, site: null };
  state.board = null;
  state.lots = [];
  state.lot = null;
  navigate("#/login");
  render();
}

function handleLotSearch(event) {
  event.preventDefault();
  const query = String(new FormData(event.currentTarget).get("query") || "").trim();
  navigate(query ? `#/lots?q=${encodeURIComponent(query)}` : "#/lots");
}

async function handleScanLookup(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const trackingId = String(form.get("tracking_id") || "").trim();
  await openTrackingId(trackingId, "Manual entry");
}

function syncWeightDisplay() {
  const slider = app?.querySelector("input[type='range'][name='charged_weight_lbs']");
  const display = app?.querySelector("[data-weight-display]");
  if (!slider || !display) return;
  display.textContent = `${Number(slider.value || 0).toFixed(1)} lbs`;
}

function handleWeightAdjust(event) {
  const slider = app?.querySelector("input[type='range'][name='charged_weight_lbs']");
  if (!slider) return;
  const delta = Number(event.currentTarget.dataset.delta || 0);
  const next = clampChargeWeight(Number(slider.value || 0) + delta, Number(slider.max || 0));
  slider.value = String(next);
  syncWeightDisplay();
}

function handleCountAdjust(event) {
  const field = event.currentTarget.dataset.field;
  const input = app?.querySelector(`input[name='${field}']`);
  if (!input) return;
  const delta = Number(event.currentTarget.dataset.delta || 0);
  const current = Math.max(0, Number(input.value || 0) || 0);
  input.value = String(Math.max(0, current + delta));
}

function syncRunDraftFromForm() {
  const formEl = app?.querySelector("form[data-form='run-execution']");
  if (!formEl || !state.run) return;
  // Only merge form values that are actually present (not undefined).
  // buildRunPayload returns undefined for missing fields — spreading those
  // would overwrite valid state.run values (like post_extraction_pathway)
  // with undefined if the hidden input is stale or absent.
  const formPayload = buildRunPayload(new FormData(formEl));
  const safePayload = Object.fromEntries(
    Object.entries(formPayload).filter(([, v]) => v !== undefined)
  );
  state.run = { ...state.run, ...safePayload };
}

// Fields that gate UI visibility — when these change we need a full re-render
// so dependent buttons (like Start Post-Extraction) appear or disappear.
// Only fields whose value change must immediately re-render gated UI elements.
// Specifically: post_extraction_pathway gates the "Start Post-Extraction" button.
// Choice fields like flow_resumed_decision do NOT gate any button visibility —
// they only need to reach the form payload, so they stay out of this set.
// Keeping this set minimal prevents render() from clobbering live input values.
const RENDER_ON_CHANGE_FIELDS = new Set([
  "post_extraction_pathway",
]);

async function handleSetFieldValue(event) {
  const field = event.currentTarget.dataset.field;
  const value = String(event.currentTarget.dataset.value || "");
  const scope = event.currentTarget.closest("form") || app;
  const input = scope?.querySelector(`[name='${field}']`);
  if (!input) return;
  input.value = value;
  // Update state.run with the new value so render() reads it correctly.
  // Must happen before render() below, otherwise the re-render reads stale state.
  if (state.run && RENDER_ON_CHANGE_FIELDS.has(field)) {
    state.run = { ...state.run, [field]: value };
    render(); // Re-render so gated UI updates (e.g. Start Post-Extraction button)
    if (field === "post_extraction_pathway" && value && state.route.chargeId) {
      try {
        const response = await api.saveChargeRun(state.route.chargeId, { post_extraction_pathway: value });
        state.run = response.run;
        state.lot = response.lot;
        state.board = await api.getBoard("all");
      } catch (error) {
        showToast(error.payload?.error?.message || error.message || "Unable to save pathway");
      } finally {
        render();
      }
    }
    return;   // render() + bind() already re-attached all listeners; we're done
  }
  // For non-gating fields: update state.run so value survives re-renders,
  // then toggle button visuals without re-rendering the whole DOM.
  // Do NOT call render() here — it destroys live input values the user typed.
  if (state.run) {
    state.run = { ...state.run, [field]: value };
  }
  scope
    ?.querySelectorAll(`[data-action='set-field'][data-field='${field}']`)
    .forEach((button) => {
      const isSelected = String(button.dataset.value || "") === value;
      button.classList.toggle("is-active", isSelected);
      button.classList.toggle("btn-primary", isSelected);
      button.classList.toggle("btn-secondary", !isSelected);
    });
  syncRunDraftFromForm();
}

function presetWeightValue(preset, maxWeight) {
  const prefs = loadUiPrefs();
  if (preset === "full") return clampChargeWeight(maxWeight, maxWeight);
  if (preset === "half") return halfLotChargeWeight(maxWeight);
  if (preset === "last") return clampChargeWeight(prefs.last_charge_weight_lbs || 0, maxWeight);
  return preferredChargePreset(maxWeight);
}

function handlePresetWeight(event) {
  const slider = app?.querySelector("input[type='range'][name='charged_weight_lbs']");
  if (!slider) return;
  const next = presetWeightValue(event.currentTarget.dataset.preset || "hundred", Number(slider.max || 0));
  slider.value = String(next);
  syncWeightDisplay();
}

function handleSetNow() {
  const input = app?.querySelector("input[name='charged_at']");
  if (input) input.value = localDateTimeInputValue();
}

function syncBlendDisplay() {
  const slider = app?.querySelector("input[type='range'][name='biomass_blend_milled_pct']");
  if (!slider) return;
  const milled = Math.max(0, Math.min(100, Number(slider.value || 0)));
  const unmilled = 100 - milled;
  const milledNode = app?.querySelector("[data-blend-milled]");
  const unmilledNode = app?.querySelector("[data-blend-unmilled]");
  const unmilledInput = app?.querySelector("[data-blend-unmilled-input='1']");
  if (milledNode) milledNode.textContent = `${milled}%`;
  if (unmilledNode) unmilledNode.textContent = `${unmilled}%`;
  if (unmilledInput) unmilledInput.value = String(unmilled);
}

async function handleTimerStamp(event) {
  const field = event.currentTarget.dataset.field;
  const value = localDateTimeInputValue();
  if (!field || !state.run || !state.route.chargeId) return;
  // Save immediately so the server record reflects the timestamp.
  // If we only update state.run in memory, any subsequent form save
  // will return a fresh server response that overwrites our in-memory value.
  state.run = { ...state.run, [field]: value };
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, { [field]: value });
    state.run = response.run;
    state.lot = response.lot;
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to save timer");
  } finally {
    render();
  }
}

function timerStopField(field) {
  if (field === "run_fill_started_at") return "run_fill_ended_at";
  if (field === "mixer_started_at") return "mixer_ended_at";
  if (field === "flush_started_at") return "flush_ended_at";
  if (field === "pot_pour_offgas_started_at") return "pot_pour_offgas_completed_at";
  if (field === "thca_oven_started_at") return "thca_oven_completed_at";
  if (field === "hte_offgas_started_at") return "hte_offgas_completed_at";
  if (field === "final_purge_started_at") return "final_purge_completed_at";
  return field;
}

async function handleTimerStop(event) {
  const targetField = timerStopField(event.currentTarget.dataset.field || "");
  const value = localDateTimeInputValue();
  if (!targetField || !state.run || !state.route.chargeId) return;
  // Save immediately so the server record reflects the stop timestamp.
  // Without an immediate save, subsequent form submits return a server
  // response with the old empty value, reopening steps that were done.
  state.run = { ...state.run, [targetField]: value };
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, { [targetField]: value });
    state.run = response.run;
    state.lot = response.lot;
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to save timer");
  } finally {
    render();
  }
}

async function handleChargeSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = buildChargePayload(form, state.lot?.remaining_weight_lbs || 0);
  state.loading = true;
  render();
  try {
    const result = await api.createCharge(String(form.get("lot_id") || ""), payload);
    state.lastCharge = result;
    saveUiPrefs({ ...loadUiPrefs(), last_charge_weight_lbs: payload.charged_weight_lbs, last_reactor_number: payload.reactor_number });
    state.board = await api.getBoard("all");
    showToast(`Recorded ${result.charge.charged_weight_lbs} lbs into Reactor ${result.charge.reactor_number}.`);
    navigate("#/reactors");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to record charge");
  } finally {
    state.loading = false;
    render();
  }
}

async function handleSettingsSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const rawThreshold = String(form.get("chiller_temp_threshold_c") || "").trim();
  const threshold = parseFloat(rawThreshold);
  if (!Number.isFinite(threshold)) {
    showToast("Enter a valid temperature threshold.");
    return;
  }
  if (threshold > 0) {
    showToast("Threshold must be 0°C or below (chiller temperatures are negative).");
    return;
  }
  // Persist in state.settings — in production this calls an API endpoint
  // that updates SystemSetting('extraction_chiller_temp_threshold_c').
  state.settings = { ...(state.settings || {}), chiller_temp_threshold_c: threshold, saved: true };
  // Also update auth.site so the mock api.js picks it up
  if (state.auth.site) state.auth.site.chiller_temp_threshold_c = threshold;
  showToast(`Chiller threshold set to ${threshold}°C.`);
  render();
}

async function handleRunSubmit(event) {
  event.preventDefault();
  if (!state.route.chargeId) return;
  const form = new FormData(event.currentTarget);
  const payload = withPostExtractionFallbacks(buildRunPayload(form));
  state.loading = true;
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, payload);
    state.run = response.run;
    state.lot = response.lot;
    state.board = await api.getBoard("all");
    showToast("Run execution saved.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to save run execution");
  } finally {
    state.loading = false;
    render();
  }
}

async function handleDownstreamSubmit(event) {
  event.preventDefault();
  if (!state.route.chargeId) return;
  const formEl = app?.querySelector("form[data-form='run-execution']") || event.currentTarget;
  const payload = withPostExtractionFallbacks(buildRunPayload(new FormData(formEl)));
  state.loading = true;
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, payload);
    state.run = response.run;
    state.lot = response.lot;
    state.board = await api.getBoard("all");
    showToast("Saved.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to save");
  } finally {
    state.loading = false;
    render();
  }
}

async function handleRunEvidenceSubmit(event) {
  event.preventDefault();
  if (!state.route.chargeId) return;
  const formEl = event.currentTarget;
  const input = formEl.querySelector("input[type='file'][name='photos']");
  const files = Array.from(input?.files || []);
  if (!files.length) {
    showToast("Choose at least one photo before uploading.");
    return;
  }
  state.loading = true;
  render();
  try {
    await api.uploadChargeRunEvidence(state.route.chargeId, formEl.dataset.evidenceType || "other", files);
    const refreshedRun = await api.getChargeRun(state.route.chargeId);
    const evidencePayload = await api.getChargeRunEvidence(state.route.chargeId);
    state.run = refreshedRun.run;
    state.lot = refreshedRun.lot;
    state.runEvidence = Array.isArray(evidencePayload?.evidence) ? evidencePayload.evidence : [];
    showToast("Booth evidence uploaded.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to upload booth evidence");
  } finally {
    state.loading = false;
    render();
  }
}

function buildRunPayload(form, progressionAction = "") {
  // WHY or undefined: the mock (and live API) use Object.assign(run, payload)
  // to merge form fields into the run record. If we send empty strings for
  // fields not present in the current form, they overwrite real timestamps
  // that were set by earlier progression steps — causing state corruption.
  // Sending undefined means Object.assign skips the key entirely, preserving
  // whatever value the server already has for that field.
  function field(name) {
    const val = String(form.get(name) || "").trim();
    return val || undefined;
  }
  function checkboxField(name) {
    return form.get(name) ? "1" : undefined;
  }
  return {
    run_fill_started_at: field("run_fill_started_at"),
    run_fill_ended_at: field("run_fill_ended_at"),
    biomass_blend_milled_pct: field("biomass_blend_milled_pct"),
    biomass_blend_unmilled_pct: field("biomass_blend_unmilled_pct"),
    flush_count: field("flush_count"),
    flush_total_weight_lbs: field("flush_total_weight_lbs"),
    fill_count: field("fill_count"),
    fill_total_weight_lbs: field("fill_total_weight_lbs"),
    stringer_basket_count: field("stringer_basket_count"),
    crc_blend: field("crc_blend"),
    mixer_started_at: field("mixer_started_at"),
    mixer_ended_at: field("mixer_ended_at"),
    flush_started_at: field("flush_started_at"),
    flush_ended_at: field("flush_ended_at"),
    run_completed_at: field("run_completed_at"),
    chiller_check_actual_temp_c: field("chiller_check_actual_temp_c"),
    primary_solvent_charge_lbs: field("primary_solvent_charge_lbs"),
    flush_solvent_chiller_temp_f: field("flush_solvent_chiller_temp_f"),
    flush_plate_temp_f: field("flush_plate_temp_f"),
    flush_temp_slack_post_confirmed: checkboxField("flush_temp_slack_post_confirmed"),
    flush_solvent_charge_lbs: field("flush_solvent_charge_lbs"),
    wet_hte_g: field("wet_hte_g"),
    wet_thca_g: field("wet_thca_g"),
    post_extraction_pathway: field("post_extraction_pathway"),
    post_extraction_started_at: field("post_extraction_started_at"),
    post_extraction_initial_outputs_recorded_at: field("post_extraction_initial_outputs_recorded_at"),
    pot_pour_offgas_started_at: field("pot_pour_offgas_started_at"),
    pot_pour_offgas_completed_at: field("pot_pour_offgas_completed_at"),
    pot_pour_daily_stir_count: field("pot_pour_daily_stir_count"),
    pot_pour_centrifuged_at: field("pot_pour_centrifuged_at"),
    thca_oven_started_at: field("thca_oven_started_at"),
    thca_oven_completed_at: field("thca_oven_completed_at"),
    thca_milled_at: field("thca_milled_at"),
    thca_destination: field("thca_destination"),
    hte_offgas_started_at: field("hte_offgas_started_at"),
    hte_offgas_completed_at: field("hte_offgas_completed_at"),
    hte_clean_decision: field("hte_clean_decision"),
    hte_filter_outcome: field("hte_filter_outcome"),
    hte_prescott_processed_at: field("hte_prescott_processed_at"),
    hte_potency_disposition: field("hte_potency_disposition"),
    hte_queue_destination: field("hte_queue_destination"),
    flow_resumed_decision: field("flow_resumed_decision"),
    flow_adjustment_reason: field("flow_adjustment_reason"),
    final_clarity_decision: field("final_clarity_decision"),
    final_clarity_reason: field("final_clarity_reason"),
    primary_soak_short_reason: field("primary_soak_short_reason"),
    mixer_short_reason: field("mixer_short_reason"),
    flush_short_reason: field("flush_short_reason"),
    final_purge_short_reason: field("final_purge_short_reason"),
    final_purge_started_at: field("final_purge_started_at"),
    final_purge_completed_at: field("final_purge_completed_at"),
    shutdown_recovery_inlets_closed: checkboxField("shutdown_recovery_inlets_closed"),
    shutdown_filtration_pumpdown_started: checkboxField("shutdown_filtration_pumpdown_started"),
    shutdown_nitrogen_off: checkboxField("shutdown_nitrogen_off"),
    shutdown_dewax_inlet_closed: checkboxField("shutdown_dewax_inlet_closed"),
    progression_action: progressionAction || undefined,
    bypass_reason: field("bypass_reason"),
    notes: field("notes"),
  };
}

async function handleRunProgression(event) {
  if (!state.route.chargeId) return;
  const formEl = app?.querySelector("form[data-form='run-execution']");
  if (!formEl) return;
  const payload = buildRunPayload(new FormData(formEl), event.currentTarget.dataset.runAction || "");
  state.loading = true;
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, payload);
    state.run = response.run;
    state.lot = response.lot;
    state.board = await api.getBoard("all");
    state.blockingError = null; // clear any prior blocker on success
    showToast("Run progression updated.");
  } catch (error) {
    const message = error.payload?.error?.message || error.message || "Unable to update run progression";
    const blocker = resolveBlocker(message);
    if (blocker) {
      // A prerequisite step is missing — surface it inline, skip the toast
      state.blockingError = blocker;
    } else {
      // Generic error — show toast as before
      state.blockingError = null;
      showToast(message);
    }
  } finally {
    state.loading = false;
    render();
  }
}

function withPostExtractionFallbacks(payload) {
  const next = { ...payload };
  if (!next.post_extraction_pathway && state.run?.post_extraction_pathway) {
    next.post_extraction_pathway = state.run.post_extraction_pathway;
  }
  return next;
}

async function handlePostExtractionProgression(event) {
  if (!state.route.chargeId) return;
  const formEl = app?.querySelector("form[data-form='run-execution']");
  if (!formEl) return;
  const payload = withPostExtractionFallbacks({
    ...buildRunPayload(new FormData(formEl)),
    post_extraction_action: event.currentTarget.dataset.postAction || "",
  });
  state.loading = true;
  render();
  try {
    const response = await api.saveChargeRun(state.route.chargeId, payload);
    state.run = response.run;
    state.lot = response.lot;
    state.board = await api.getBoard("all");
    showToast("Post-extraction handoff updated.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to update post-extraction handoff");
  } finally {
    state.loading = false;
    render();
  }
}

async function handleTransition(event) {
  const chargeId = event.currentTarget.dataset.chargeId;
  const targetState = event.currentTarget.dataset.targetState;
  if (targetState === "cancelled") {
    state.dialog = { type: "cancel", chargeId };
    render();
    return;
  }
  await submitTransition(chargeId, targetState);
}

async function handleConfirmCancel(event) {
  const resolution = event.currentTarget.dataset.resolution;
  const chargeId = state.dialog?.chargeId;
  state.dialog = null;
  render();
  await submitTransition(chargeId, "cancelled", resolution);
}

async function submitTransition(chargeId, targetState, cancelResolution = undefined) {
  state.loading = true;
  render();
  try {
    await api.transitionCharge(chargeId, { target_state: targetState, cancel_resolution: cancelResolution });
    state.board = await api.getBoard(state.route.boardView || "all");
    if (state.route.name === "run" && state.route.chargeId) {
      const payload = await api.getChargeRun(state.route.chargeId);
      state.run = payload.run;
      state.lot = payload.lot;
      state.charge = payload.charge || null;
    }
    if (targetState === "cleared") {
      showToast("Reactor marked empty and available.");
      navigate("#/reactors");
      return;
    }
    showToast(`Charge moved to ${targetState.replaceAll("_", " ")}.`);
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to update charge state");
  } finally {
    state.loading = false;
    render();
  }
}

function cameraAllowedWithoutHttps() {
  const hostname = window.location.hostname || "";
  return window.isSecureContext || hostname === "localhost" || hostname === "127.0.0.1";
}

function browserScanSupportMessage() {
  if (!("mediaDevices" in navigator) || !navigator.mediaDevices.getUserMedia) {
    return "This browser does not expose camera access. Manual and Bluetooth-scanner entry are still ready.";
  }
  if (!cameraAllowedWithoutHttps()) {
    return "Camera access requires HTTPS on this device. Manual and Bluetooth-scanner entry are still ready.";
  }
  if (!("BarcodeDetector" in window)) {
    return "Camera barcode detection is not supported in this browser yet. Manual and Bluetooth-scanner entry are ready.";
  }
  return "Camera scan is idle.";
}

function setScanStatus(message) {
  state.scanStatus = message;
  const label = app?.querySelector("#scan-status-text");
  if (label) label.textContent = message;
}

function scanVideoElements() {
  return {
    video: app?.querySelector("#scan-video"),
    emptyState: app?.querySelector("#scan-preview-empty"),
  };
}

function stopCamera() {
  if (scanTimer) {
    window.clearTimeout(scanTimer);
    scanTimer = null;
  }
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  const { video, emptyState } = scanVideoElements();
  if (video) video.srcObject = null;
  if (emptyState) emptyState.hidden = false;
  lastScannedValue = null;
  if (state.route.name === "scan") {
    setScanStatus(browserScanSupportMessage());
  }
}

async function scanFrame() {
  const { video } = scanVideoElements();
  if (!barcodeDetector || !video?.srcObject) return;
  try {
    const barcodes = await barcodeDetector.detect(video);
    if (Array.isArray(barcodes) && barcodes.length > 0) {
      const rawValue = String(barcodes[0].rawValue || "").trim();
      if (rawValue && rawValue !== lastScannedValue) {
        lastScannedValue = rawValue;
        setScanStatus(`Scanned ${rawValue}. Opening charge form...`);
        await openTrackingId(rawValue, "Camera scan");
        return;
      }
    }
  } catch (error) {
    setScanStatus(`Camera scan error: ${error.message || "unknown error"}`);
    stopCamera();
    return;
  }
  scanTimer = window.setTimeout(scanFrame, 250);
}

async function startCamera() {
  if (!("mediaDevices" in navigator) || !navigator.mediaDevices.getUserMedia) {
    setScanStatus("This browser does not expose camera access. Use the manual field instead.");
    return;
  }
  if (!cameraAllowedWithoutHttps()) {
    setScanStatus("Camera access requires HTTPS on this device. Use the manual field or a Bluetooth scanner.");
    return;
  }
  if (!("BarcodeDetector" in window)) {
    setScanStatus("Barcode scanning is not supported in this browser. Use the manual field or a Bluetooth scanner.");
    return;
  }
  try {
    barcodeDetector = new window.BarcodeDetector({ formats: ["code_39", "code_128", "qr_code"] });
  } catch {
    setScanStatus("This browser cannot initialize barcode detection. Use the manual field instead.");
    return;
  }
  try {
    const { video, emptyState } = scanVideoElements();
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    if (!video) return;
    video.srcObject = cameraStream;
    await video.play();
    if (emptyState) emptyState.hidden = true;
    setScanStatus("Camera live. Point it at a lot barcode or QR code.");
    scanFrame();
  } catch (error) {
    setScanStatus(`Unable to start camera: ${error.message || "permission denied"}`);
    stopCamera();
  }
}

async function openTrackingId(trackingId, method = "Manual entry") {
  const value = String(trackingId || "").trim();
  if (!value) {
    showToast("Enter a tracking ID before opening the lot.");
    return;
  }
  try {
    const lot = await api.lookupLot(value);
    state.recentLookup = {
      tracking_id: value,
      lot_id: lot.id,
      lot_label: lotTitle(lot),
      method_label: method,
    };
    setScanStatus(`${method} resolved ${value}. Opening charge form...`);
    stopCamera();
    navigate(`#/lots/${encodeURIComponent(lot.id)}/charge`);
  } catch (error) {
    setScanStatus(error.payload?.error?.message || error.message || "Unable to find that lot.");
    showToast(error.payload?.error?.message || error.message || "Unable to find that lot.");
  }
}
