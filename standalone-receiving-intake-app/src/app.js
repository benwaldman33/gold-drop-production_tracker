import { createApiClient } from "./api.js";
import { canConfirmReceipt, receivingTitle } from "./domain.js";
import { getAppConfig } from "./config.js";
import { buildReceivePayload, parseRoute, selectedFilesFromForm, shortDate, shortDateTime } from "./ui-helpers.js";

const config = getAppConfig();
const api = createApiClient(config);
const app = document.getElementById("app");

const state = {
  route: parseRoute(window.location.hash || "#/login"),
  auth: { authenticated: false, user: null, permissions: {}, site: null },
  queue: [],
  item: null,
  pendingFiles: {
    delivery_photos: [],
  },
  loading: false,
  toast: "",
};

window.addEventListener("hashchange", onRouteChange);

start().catch((error) => {
  console.error(error);
  showToast(error.message || "Unable to start app");
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
  state.route = parseRoute(window.location.hash || "#/login");
  if (state.route.name !== "receive") {
    state.pendingFiles.delivery_photos = [];
  }
  await loadRoute();
  render();
}

async function loadRoute() {
  if (!state.auth.authenticated) return;
  if (["home", "queue"].includes(state.route.name)) {
    state.queue = await api.listReceivingQueue(state.route.status || "ready");
  }
  if (["detail", "receive"].includes(state.route.name)) {
    state.item = await api.getReceivingItem(state.route.id);
  }
}

function navigate(hash) {
  window.location.hash = hash;
}

function pendingFilesFor(fieldName) {
  return [...(state.pendingFiles[fieldName] || [])];
}

function clearPendingFiles(fieldName) {
  state.pendingFiles[fieldName] = [];
}

function fileFingerprint(file) {
  return `${file?.name || ""}:${file?.size || 0}:${file?.lastModified || 0}`;
}

function queueFiles(fieldName, files) {
  const existing = state.pendingFiles[fieldName] || [];
  const seen = new Set(existing.map(fileFingerprint));
  for (const file of files || []) {
    const fingerprint = fileFingerprint(file);
    if (!seen.has(fingerprint)) {
      existing.push(file);
      seen.add(fingerprint);
    }
  }
  state.pendingFiles[fieldName] = existing;
  return existing;
}

function showToast(message) {
  state.toast = message;
  render();
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    state.toast = "";
    render();
  }, 2600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function shell(content) {
  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-badge">Receiving Intake App</div>
          <h1>Gold Drop</h1>
          <p>Mobile-first receiving queue, dock confirmation, and delivery evidence.</p>
          <p class="subtle">${escapeHtml(state.auth.site?.site_name || "Mock site")}</p>
        </div>
        ${
          state.auth.authenticated
            ? `
          <nav class="nav">
            <a href="#/home" class="${state.route.name === "home" ? "active" : ""}">Home <small>Ready queue</small></a>
            <a href="#/queue" class="${state.route.name === "queue" || state.route.name === "detail" || state.route.name === "receive" ? "active" : ""}">Receiving Queue <small>Dock work</small></a>
          </nav>
          <div class="actions"><button class="btn btn-secondary" data-action="logout">Log out</button></div>
          `
            : ""
        }
      </aside>
      <main class="content">${content}</main>
    </div>
    ${state.toast ? `<div class="toast">${escapeHtml(state.toast)}</div>` : ""}
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
  if (state.route.name === "queue") return renderQueue();
  if (state.route.name === "detail") return renderDetail();
  if (state.route.name === "receive") return renderReceiveForm();
  return `<div class="empty">Page not found.</div>`;
}

function renderLogin() {
  return `
    <section class="panel" style="max-width: 640px; margin: 7vh auto;">
      <div class="stack">
        <div class="brand-badge">Standalone App</div>
        <h1 class="page-title">Receiving Intake Login</h1>
        <p class="subtle">Sign in with your Gold Drop user identity to view approved or committed deliveries waiting at the dock.</p>
      </div>
      <form class="form" data-form="login" style="margin-top: 18px;">
        <div class="two-col">
          <div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required /></div>
          <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required /></div>
        </div>
        <div class="actions"><button class="btn btn-primary" type="submit">${state.loading ? "Signing in..." : "Sign in"}</button></div>
      </form>
    </section>
  `;
}

function renderHome() {
  const ready = state.queue.filter((item) => canConfirmReceipt(item.status)).length;
  const delivered = state.queue.filter((item) => String(item.status || "").toLowerCase() === "delivered").length;
  const photos = state.queue.reduce((sum, item) => sum + Number(item.receiving?.photo_count || 0), 0);
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>Receiving Home</h2><div class="meta">Approved and committed material waiting to be received into the facility.</div></div>
        <div class="actions"><a class="btn btn-primary" href="#/queue">Open Queue</a></div>
      </div>
      <section class="grid-3">
        <div class="card stat"><div class="label">Ready to Receive</div><div class="value">${ready}</div><div class="hint">Approved or committed items</div></div>
        <div class="card stat"><div class="label">Recently Delivered</div><div class="value">${delivered}</div><div class="hint">Closed receiving records</div></div>
        <div class="card stat"><div class="label">Delivery Photos</div><div class="value">${photos}</div><div class="hint">Evidence attached to receipts</div></div>
      </section>
      <section class="card">
        <div class="stack" style="margin-bottom: 12px;"><h3 style="margin:0;">Next items at the dock</h3><p class="subtle">Focus the receiving team on the oldest open commitments first.</p></div>
        <div class="list">${state.queue.slice(0, 5).map(renderQueueRow).join("")}</div>
      </section>
    </div>
  `;
}

function renderQueue() {
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>Receiving Queue</h2><div class="meta">Open approved or committed purchases waiting for dock confirmation.</div></div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/queue?status=ready">Ready</a>
          <a class="btn btn-secondary" href="#/queue?status=delivered">Delivered</a>
        </div>
      </div>
      <section class="card">
        ${state.queue.length ? `<div class="list">${state.queue.map(renderQueueRow).join("")}</div>` : `<div class="empty">No receiving items for this filter.</div>`}
      </section>
    </div>
  `;
}

function renderQueueRow(item) {
  return `
    <div class="row">
      <div class="stack">
        <h3>${escapeHtml(receivingTitle(item))}</h3>
        <p>${escapeHtml(item.batch_id || item.id)} - ${escapeHtml(String(item.expected_weight_lbs || 0))} lbs - ${escapeHtml(shortDate(item.purchase_date || item.submitted_at))}</p>
        <p class="subtle">Dock: ${escapeHtml(item.receiving?.location || "Unassigned")} - Photos: ${escapeHtml(String(item.receiving?.photo_count || 0))}</p>
      </div>
      <div class="actions">
        ${statusChip(item.status)}
        <a class="btn btn-secondary" href="#/queue/${encodeURIComponent(item.id)}">Open</a>
      </div>
    </div>
  `;
}

function statusChip(status) {
  const label = String(status || "unknown");
  return `<span class="chip ${escapeHtml(label)}">${escapeHtml(label)}</span>`;
}

function renderDetail() {
  const item = state.item;
  if (!item) return `<div class="empty">Receiving item not found.</div>`;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div>
          <h2>${escapeHtml(receivingTitle(item))}</h2>
          <div class="meta">${escapeHtml(item.batch_id || item.id)} - ${statusChip(item.status)} - Approved ${escapeHtml(shortDateTime(item.approval?.approved_at))}</div>
        </div>
        <div class="actions">
          ${canConfirmReceipt(item.status) ? `<a class="btn btn-primary" href="#/queue/${encodeURIComponent(item.id)}/receive">Confirm Receipt</a>` : ""}
        </div>
      </div>
      <section class="grid-2">
        <div class="card">
          <div class="stack">
            <h3 style="margin:0;">Receiving summary</h3>
            <p class="subtle">Operational data the dock team needs before unloading and confirming the lot.</p>
          </div>
          <dl class="detail-grid" style="margin-top:12px;">
            <dt>Supplier</dt><dd>${escapeHtml(item.supplier?.name || item.supplier_name)}</dd>
            <dt>Strain</dt><dd>${escapeHtml(item.strain_name || "Unknown")}</dd>
            <dt>Expected Weight</dt><dd>${escapeHtml(String(item.expected_weight_lbs || 0))} lbs</dd>
            <dt>Expected Potency</dt><dd>${escapeHtml(item.expected_potency_pct ?? "—")}</dd>
            <dt>Queue State</dt><dd>${escapeHtml(item.receiving?.queue_state || "ready")}</dd>
            <dt>Dock Location</dt><dd>${escapeHtml(item.receiving?.location || "Unassigned")}</dd>
          </dl>
        </div>
        <div class="card">
          <div class="stack">
            <h3 style="margin:0;">Lot state</h3>
            <p class="subtle">Current lot tracking and floor placement.</p>
          </div>
          ${(item.lots || []).map((lot) => `
            <div class="row" style="margin-top:12px;">
              <div class="stack">
                <h3>${escapeHtml(lot.tracking_id || lot.id)}</h3>
                <p>${escapeHtml(String(lot.weight_lbs || 0))} lbs - ${escapeHtml(lot.floor_state || "receiving")}</p>
                <p class="subtle">${escapeHtml(lot.location || "No location set")}</p>
              </div>
            </div>`).join("") || `<div class="empty" style="margin-top:12px;">No lot records yet.</div>`}
        </div>
      </section>
      <section class="card">
        <div class="stack" style="margin-bottom:12px;">
          <h3 style="margin:0;">Delivery photos</h3>
          <p class="subtle">Photos captured from the dock or intake process.</p>
        </div>
        ${(item.photos || []).length ? `<div class="photo-grid">${item.photos.map(renderPhoto).join("")}</div>` : `<div class="empty">No delivery photos yet.</div>`}
      </section>
    </div>
  `;
}

function renderPhoto(photo) {
  return `
    <div class="photo-card">
      <img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.name || photo.photo_context || "photo")}" />
      <div class="subtle">${escapeHtml(photo.photo_context || "delivery")}</div>
    </div>
  `;
}

function renderReceiveForm() {
  const item = state.item;
  if (!item) return `<div class="empty">Receiving item not found.</div>`;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>Confirm Receipt</h2><div class="meta">${escapeHtml(receivingTitle(item))}</div></div>
      </div>
      <section class="panel" style="max-width: 960px;">
        <form class="form" data-form="receive" data-id="${escapeHtml(item.id)}">
          <div class="two-col">
            <div class="field"><label for="delivered_weight_lbs">Delivered weight (lbs)</label><input id="delivered_weight_lbs" name="delivered_weight_lbs" type="number" step="0.1" value="${escapeHtml(item.delivery?.delivered_weight_lbs || item.expected_weight_lbs || "")}" required /></div>
            <div class="field"><label for="delivery_date">Delivery date</label><input id="delivery_date" name="delivery_date" type="date" value="${escapeHtml(item.delivery?.delivery_date || new Date().toISOString().slice(0, 10))}" required /></div>
            <div class="field"><label for="testing_status">Testing status</label><select id="testing_status" name="testing_status"><option value="pending">Pending</option><option value="completed">Completed</option><option value="not_needed">Not Needed</option></select></div>
            <div class="field"><label for="actual_potency_pct">Actual potency %</label><input id="actual_potency_pct" name="actual_potency_pct" type="number" step="0.1" value="${escapeHtml(item.delivery?.actual_potency_pct || "")}" /></div>
            <div class="field"><label for="clean_or_dirty">Material state</label><select id="clean_or_dirty" name="clean_or_dirty"><option value="clean">Clean</option><option value="dirty">Dirty</option></select></div>
            <div class="field"><label for="location">Receiving location</label><input id="location" name="location" value="${escapeHtml(item.receiving?.location || "")}" placeholder="Dock A, Receiving Vault..." /></div>
            <div class="field"><label for="floor_state">Floor state</label><select id="floor_state" name="floor_state"><option value="receiving">Receiving</option><option value="inventory">Inventory</option><option value="quarantine">Quarantine</option></select></div>
            <div class="field"><label for="lot_notes">Lot notes</label><input id="lot_notes" name="lot_notes" value="" placeholder="Seal broken, staged in cage 2..." /></div>
          </div>
          <div class="field"><label for="delivery_notes">Delivery notes</label><textarea id="delivery_notes" name="delivery_notes" rows="4" placeholder="Condition, count discrepancy, paperwork notes...">${escapeHtml(item.delivery?.delivery_notes || "")}</textarea></div>
          <div class="field"><label for="delivery-photo">Delivery photos</label><input id="delivery-photo" name="delivery-photo" type="file" accept="image/*" multiple /><div class="helper">Photos are queued across multiple picks before save.</div></div>
          <div class="actions">
            <button class="btn btn-primary" type="submit">${state.loading ? "Saving..." : "Confirm Receipt"}</button>
            <a class="btn btn-secondary" href="#/queue/${encodeURIComponent(item.id)}">Cancel</a>
          </div>
        </form>
      </section>
    </div>
  `;
}

function bind() {
  document.querySelector('[data-action="logout"]')?.addEventListener("click", async () => {
    await api.logout();
    state.auth = { authenticated: false, user: null, permissions: {}, site: null };
    navigate("#/login");
    render();
  });

  document.querySelector('[data-form="login"]')?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    state.loading = true;
    render();
    try {
      const payload = await api.login(form.get("username"), form.get("password"));
      state.auth = {
        authenticated: true,
        user: payload.user || null,
        permissions: payload.permissions || {},
        site: payload.site || null,
      };
      state.queue = await api.listReceivingQueue("ready");
      navigate("#/home");
    } catch (error) {
      showToast(error.payload?.error?.message || error.message || "Unable to sign in.");
    } finally {
      state.loading = false;
      render();
    }
  });

  document.querySelector('[data-form="receive"]')?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formEl = event.currentTarget;
    const payload = buildReceivePayload(new FormData(formEl));
    const id = formEl.getAttribute("data-id");
    const photos = pendingFilesFor("delivery-photo").length
      ? pendingFilesFor("delivery-photo")
      : selectedFilesFromForm(formEl, "delivery-photo");
    state.loading = true;
    render();
    try {
      const item = await api.receive(id, payload);
      for (const file of photos) {
        await api.uploadPhoto(id, { file, photo_context: "delivery" });
      }
      clearPendingFiles("delivery-photo");
      state.item = await api.getReceivingItem(item.id);
      state.queue = await api.listReceivingQueue("ready");
      navigate(`#/queue/${encodeURIComponent(item.id)}`);
      showToast("Receipt confirmed.");
    } catch (error) {
      showToast(error.payload?.error?.message || error.message || "Unable to confirm receipt.");
    } finally {
      state.loading = false;
      render();
    }
  });

  document.querySelectorAll('input[type="file"]').forEach((input) => {
    input.addEventListener("change", () => {
      const files = queueFiles(input.name, [...(input.files || [])]);
      const helper = input.closest(".field")?.querySelector(".helper");
      if (helper) helper.textContent = `${files.length} file(s) selected. Additional picks will be added, not replaced.`;
      input.value = "";
    });
  });
}

render();
