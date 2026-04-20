import { createApiClient } from "./api.js";
import { clampChargeWeight, halfLotChargeWeight, lotTitle, readyLotCount, stateTone } from "./domain.js";
import { getAppConfig } from "./config.js";
import { readJson, writeJson } from "./storage.js";
import { buildChargePayload, defaultChargeValue, defaultReactorValue, escapeHtml, localDateTimeInputValue, parseRoute } from "./ui-helpers.js";

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
  loading: false,
  toast: "",
  lastCharge: null,
  dialog: null,
  scanStatus: "",
  recentLookup: null,
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
        <a class="btn btn-primary" href="${escapeHtml(state.lastCharge.next_run_url || "#")}">Open Run in Main App</a>
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
          <div class="meta-row"><span>${escapeHtml(current.source_mode || "main app")}</span>${current.run_id ? `<a class="inline-link" href="/runs/${escapeHtml(current.run_id)}/edit?return_to=/floor-ops">Open Run</a>` : `<span>Run not linked</span>`}</div>
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
  const actions = current.available_actions || [];
  if (!actions.length) return "";
  return `
    <div class="action-grid">
      ${actions
        .map((action) => `<button class="btn ${action.target_state === "cancelled" ? "btn-danger" : "btn-secondary"}" data-action="transition-charge" data-charge-id="${escapeHtml(current.charge_id)}" data-target-state="${escapeHtml(action.target_state)}">${escapeHtml(action.label)}</button>`)
        .join("")}
    </div>
  `;
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
      ${card.entries?.length ? `<div class="stack tight">${card.entries.map((entry) => `<div class="history-entry"><strong>${escapeHtml(entry.label)}</strong><span>${escapeHtml(entry.timestamp_label || "")}</span>${entry.run_id ? `<a class="inline-link" href="/runs/${escapeHtml(entry.run_id)}/edit?return_to=/floor-ops">Open Run</a>` : ""}</div>`).join("")}</div>` : `<p class="subtle">No history yet today.</p>`}
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

function bind() {
  app?.querySelectorAll("[data-action='logout']").forEach((button) => button.addEventListener("click", handleLogout));
  app?.querySelector("form[data-form='login']")?.addEventListener("submit", handleLogin);
  app?.querySelector("form[data-form='lot-search']")?.addEventListener("submit", handleLotSearch);
  app?.querySelector("form[data-form='scan-lookup']")?.addEventListener("submit", handleScanLookup);
  app?.querySelector("form[data-form='charge']")?.addEventListener("submit", handleChargeSubmit);
  app?.querySelectorAll("[data-action='adjust-weight']").forEach((button) => button.addEventListener("click", handleWeightAdjust));
  app?.querySelectorAll("[data-action='set-preset-weight']").forEach((button) => button.addEventListener("click", handlePresetWeight));
  app?.querySelector("[data-action='set-now']")?.addEventListener("click", handleSetNow);
  app?.querySelector("[data-action='start-camera']")?.addEventListener("click", startCamera);
  app?.querySelector("[data-action='stop-camera']")?.addEventListener("click", stopCamera);
  app?.querySelectorAll("[data-action='transition-charge']").forEach((button) => button.addEventListener("click", handleTransition));
  app?.querySelector("[data-action='close-dialog']")?.addEventListener("click", () => {
    state.dialog = null;
    render();
  });
  app?.querySelectorAll("[data-action='confirm-cancel']").forEach((button) => button.addEventListener("click", handleConfirmCancel));
  app?.querySelector("input[type='range'][name='charged_weight_lbs']")?.addEventListener("input", syncWeightDisplay);
  focusScanInput();
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
  try {
    await api.transitionCharge(chargeId, { target_state: targetState, cancel_resolution: cancelResolution });
    state.board = await api.getBoard(state.route.boardView || "all");
    showToast(`Charge moved to ${targetState.replaceAll("_", " ")}.`);
    render();
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to update charge state");
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
