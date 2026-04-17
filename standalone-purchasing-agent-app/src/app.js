import { createApiClient } from "./api.js";
import { canRecordDelivery, isOpportunityEditable, opportunityTitle } from "./domain.js";
import { getAppConfig } from "./config.js";
import { buildOpportunityPayload, buildSupplierPayload, parseRoute, selectedFilesFromForm, shortDate, shortDateTime } from "./ui-helpers.js";
import { readJson, removeValue, writeJson } from "./storage.js";

const config = getAppConfig();
const api = createApiClient(config);
const app = document.getElementById("app");

const state = {
  route: parseRoute(window.location.hash || "#/login"),
  auth: { authenticated: false, user: null, permissions: {}, capabilities: null, site: null },
  loading: false,
  toast: "",
  suppliers: [],
  supplier: null,
  opportunities: [],
  opportunity: null,
  duplicateContext: null,
  supplierQuery: "",
  opportunityPrefillSupplier: null,
  pendingFiles: {
    photo_upload: [],
    delivery_photos: [],
  },
};

const OPPORTUNITY_DRAFT_KEY = "gold-drop-purchasing-agent-opportunity-draft-v1";
const SUPPLIER_DRAFT_KEY = "gold-drop-purchasing-agent-supplier-draft-v1";

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
    const capabilities = me.capabilities || (config.mode === "live" ? await api.capabilities() : null);
    state.auth = {
      authenticated: true,
      user: me.user || null,
      permissions: me.permissions || {},
      capabilities,
      site: me.site || null,
    };
  }
}

function buyingWorkflowState() {
  const workflow = state.auth.capabilities?.write_workflows?.buying;
  return {
    enabled: workflow?.enabled ?? true,
    allowed: workflow?.allowed ?? Boolean(state.auth.permissions?.can_create_opportunity),
  };
}

function buyingWorkflowMessage() {
  const workflow = buyingWorkflowState();
  if (!workflow.enabled) {
    return "The site has the standalone purchasing workflow disabled. A Super Admin can re-enable it in Settings.";
  }
  if (!workflow.allowed) {
    return "Your account does not currently have access to the standalone purchasing workflow. Ask an administrator to review your purchase-edit permissions.";
  }
  return "";
}

async function onRouteChange() {
  state.route = parseRoute(window.location.hash || "#/login");
  if (!["opportunity-new", "edit", "delivery"].includes(state.route.name)) {
    state.pendingFiles.photo_upload = [];
    state.pendingFiles.delivery_photos = [];
  }
  await loadRoute();
  render();
}

async function loadRoute() {
  if (!state.auth.authenticated) return;
  if (!buyingWorkflowState().enabled || !buyingWorkflowState().allowed) return;
  if (["home", "opportunities", "suppliers", "opportunity-new", "supplier-new"].includes(state.route.name)) {
    await Promise.all([loadSuppliers(state.route.query || state.supplierQuery || ""), loadOpportunities(state.route.status || "")]);
  }
  if (["opportunity", "edit", "delivery"].includes(state.route.name)) {
    state.opportunity = await api.getOpportunity(state.route.id);
  } else {
    state.opportunity = null;
  }
  if (state.route.name === "supplier") {
    state.supplier = await api.getSupplier(state.route.id);
  } else {
    state.supplier = null;
  }
  if (state.route.name === "opportunity-new" && state.route.supplier_id) {
    const supplierId = String(state.route.supplier_id);
    state.opportunityPrefillSupplier =
      state.supplier?.id === supplierId
        ? state.supplier
        : state.suppliers.find((supplier) => supplier.id === supplierId) || await api.getSupplier(supplierId);
  } else {
    state.opportunityPrefillSupplier = null;
  }
}

async function loadSuppliers(query = "") {
  state.supplierQuery = query;
  state.suppliers = await api.listSuppliers(query);
}

async function loadOpportunities(status = "") {
  state.opportunities = await api.listOpportunitiesMine(status);
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

function opportunityDraftDefaults() {
  return {
    supplier_id: "",
    new_supplier_name: "",
    new_supplier_contact_name: "",
    new_supplier_phone: "",
    new_supplier_email: "",
    new_supplier_location: "",
    strain_name: "",
    expected_weight_lbs: "",
    expected_potency_pct: "",
    offered_price_per_lb: "",
    availability_date: "",
    clean_or_dirty: "clean",
    testing_notes: "",
    notes: "",
    confirm_new_supplier: false,
  };
}

function supplierDraftDefaults() {
  return {
    name: "",
    location: "",
    contact_name: "",
    phone: "",
    email: "",
    notes: "",
    confirm_new_supplier: false,
  };
}

function currentOpportunityDraft() {
  const stored = readJson(OPPORTUNITY_DRAFT_KEY, opportunityDraftDefaults()) || {};
  const draft = { ...opportunityDraftDefaults(), ...stored };
  const routeSupplierId = state.route.name === "opportunity-new" ? String(state.route.supplier_id || "") : "";
  if (routeSupplierId) {
    const supplier = state.opportunityPrefillSupplier;
    draft.supplier_id = routeSupplierId;
    draft.new_supplier_name = "";
    draft.new_supplier_contact_name = draft.new_supplier_contact_name || supplier?.contact_name || "";
    draft.new_supplier_phone = draft.new_supplier_phone || supplier?.phone || "";
    draft.new_supplier_email = draft.new_supplier_email || supplier?.email || "";
    draft.new_supplier_location = draft.new_supplier_location || supplier?.location || "";
  }
  return draft;
}

function persistOpportunityDraftFromForm(form) {
  const formData = new FormData(form);
  writeJson(OPPORTUNITY_DRAFT_KEY, {
    supplier_id: String(formData.get("supplier_id") || ""),
    new_supplier_name: String(formData.get("new_supplier_name") || ""),
    new_supplier_contact_name: String(formData.get("new_supplier_contact_name") || ""),
    new_supplier_phone: String(formData.get("new_supplier_phone") || ""),
    new_supplier_email: String(formData.get("new_supplier_email") || ""),
    new_supplier_location: String(formData.get("new_supplier_location") || ""),
    strain_name: String(formData.get("strain_name") || ""),
    expected_weight_lbs: String(formData.get("expected_weight_lbs") || ""),
    expected_potency_pct: String(formData.get("expected_potency_pct") || ""),
    offered_price_per_lb: String(formData.get("offered_price_per_lb") || ""),
    availability_date: String(formData.get("availability_date") || ""),
    clean_or_dirty: String(formData.get("clean_or_dirty") || "clean"),
    testing_notes: String(formData.get("testing_notes") || ""),
    notes: String(formData.get("notes") || ""),
    confirm_new_supplier: formData.get("confirm_new_supplier") === "on",
  });
}

function persistSupplierDraftFromForm(form) {
  const formData = new FormData(form);
  writeJson(SUPPLIER_DRAFT_KEY, {
    name: String(formData.get("name") || ""),
    location: String(formData.get("location") || ""),
    contact_name: String(formData.get("contact_name") || ""),
    phone: String(formData.get("phone") || ""),
    email: String(formData.get("email") || ""),
    notes: String(formData.get("notes") || ""),
    confirm_new_supplier: formData.get("confirm_new_supplier") === "on",
  });
}

function setLoading(value) {
  state.loading = value;
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
  const buyingWorkflow = buyingWorkflowState();
  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-badge">Purchasing Agent App</div>
          <h1>Gold Drop</h1>
          <p>Mobile-first buying, delivery intake, and supplier context.</p>
          <p class="subtle">${escapeHtml(state.auth.site?.site_name || "Mock site")}</p>
        </div>
        ${
          state.auth.authenticated && buyingWorkflow.enabled && buyingWorkflow.allowed
            ? `
          <nav class="nav">
            <a href="#/home" class="${state.route.name === "home" ? "active" : ""}">Home <small>Dashboard</small></a>
            <a href="#/opportunities/new" class="${state.route.name === "opportunity-new" ? "active" : ""}">New Opportunity <small>Create</small></a>
            <a href="#/opportunities" class="${state.route.name === "opportunities" ? "active" : ""}">My Opportunities <small>Track</small></a>
            <a href="#/suppliers" class="${["suppliers", "supplier", "supplier-new"].includes(state.route.name) ? "active" : ""}">Suppliers <small>Search</small></a>
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
  if (!buyingWorkflowState().enabled || !buyingWorkflowState().allowed) return renderWorkflowUnavailable();
  if (state.route.name === "home") return renderHome();
  if (state.route.name === "opportunities") return renderOpportunityList();
  if (state.route.name === "suppliers") return renderSuppliers();
  if (state.route.name === "supplier") return renderSupplierDetail();
  if (state.route.name === "supplier-new") return renderSupplierForm();
  if (state.route.name === "opportunity-new") return renderOpportunityForm("create");
  if (state.route.name === "opportunity") return renderOpportunityDetail();
  if (state.route.name === "edit") return renderOpportunityForm("edit", state.opportunity);
  if (state.route.name === "delivery") return renderDeliveryForm();
  return `<div class="empty">Page not found.</div>`;
}

function renderLogin() {
  return `
    <section class="panel" style="max-width: 640px; margin: 7vh auto;">
      <div class="stack">
        <div class="brand-badge">Standalone App</div>
        <h1 class="page-title">Purchasing Agent Login</h1>
        <p class="subtle">Sign in with your Gold Drop user identity. Mock mode is on by default and can switch to live endpoints later without changing the UI.</p>
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

function renderWorkflowUnavailable() {
  return `
    <section class="panel" style="max-width: 760px; margin: 7vh auto;">
      <div class="stack">
        <div class="brand-badge">Workflow unavailable</div>
        <h1 class="page-title">Purchasing workflow not available</h1>
        <p class="subtle">${escapeHtml(buyingWorkflowMessage())}</p>
      </div>
      <div class="stack" style="margin-top: 18px;">
        <div class="callout warning">
          <strong>What to check</strong>
          <p class="subtle">If this is unexpected, confirm the site toggle for standalone purchasing is enabled and that this user still has purchase-edit rights.</p>
        </div>
        <div class="actions">
          <button class="btn btn-secondary" data-action="logout">Log out</button>
        </div>
      </div>
    </section>
  `;
}

function renderHome() {
  const stats = {
    pending: state.opportunities.filter((item) => item.status === "submitted").length,
    approved: state.opportunities.filter((item) => item.status === "approved").length,
    delivered: state.opportunities.filter((item) => item.status === "delivered").length,
  };
  const recent = [...state.opportunities].slice(0, 5);
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>Home</h2><div class="meta">Buyer dashboard and fast entry point for field work.</div></div>
        <div class="actions"><a class="btn btn-primary" href="#/opportunities/new">New Opportunity</a><a class="btn btn-secondary" href="#/suppliers">Search Suppliers</a></div>
      </div>
      <section class="card">
        <div class="row" style="grid-template-columns: 1fr auto;">
          <div class="stack">
            <h3>Deployment status</h3>
            <p>Live mode: ${escapeHtml(config.mode)}. Write workflow: ${escapeHtml(buyingWorkflowState().enabled ? "enabled" : "disabled")}.</p>
          </div>
          <div class="actions">
            <span class="chip ${buyingWorkflowState().enabled ? "approved" : "rejected"}">${escapeHtml(buyingWorkflowState().enabled ? "ready" : "disabled")}</span>
          </div>
        </div>
      </section>
      <section class="grid-3">
        <div class="card stat"><div class="label">Pending</div><div class="value">${stats.pending}</div><div class="hint">Awaiting review or approval</div></div>
        <div class="card stat"><div class="label">Approved</div><div class="value">${stats.approved}</div><div class="hint">Ready for delivery capture</div></div>
        <div class="card stat"><div class="label">Delivered</div><div class="value">${stats.delivered}</div><div class="hint">Completed opportunities</div></div>
      </section>
      <section class="grid-2">
        <div class="card">
          <div class="stack" style="margin-bottom: 12px;"><h3 style="margin:0;">Recent opportunities</h3><p class="subtle">Most recent activity from this buyer.</p></div>
          ${recent.length ? `<div class="list">${recent.map(renderOpportunityRow).join("")}</div>` : `<div class="empty">No opportunities yet.</div>`}
        </div>
        <div class="card">
          <div class="stack" style="margin-bottom: 12px;"><h3 style="margin:0;">Supplier context</h3><p class="subtle">Look up suppliers before you submit a new opportunity.</p></div>
          <form class="form" data-form="supplier-search"><div class="field"><label for="supplier-search">Search suppliers</label><input id="supplier-search" name="q" placeholder="Farmlane, Blue Coast, Cedar..." value="${escapeHtml(state.supplierQuery)}" /></div></form>
          <div style="margin-top: 12px;">${state.suppliers.slice(0, 4).map(renderSupplierCard).join("") || `<div class="empty">Search suppliers to see context.</div>`}</div>
        </div>
      </section>
    </div>
  `;
}

function renderOpportunityRow(item) {
  return `
    <div class="row">
      <div class="stack">
        <h3>${escapeHtml(item.supplier_name)} - ${escapeHtml(item.strain_name)}</h3>
        <p>${escapeHtml(String(item.expected_weight_lbs))} lbs - submitted ${escapeHtml(shortDate(item.submitted_at))}</p>
      </div>
      <div class="actions">${statusChip(item.status)}<a class="btn btn-secondary" href="#/opportunities/${encodeURIComponent(item.id)}">Open</a></div>
    </div>
  `;
}

function renderSupplierCard(supplier) {
  return `
    <div class="row">
      <div class="stack">
        <h3>${escapeHtml(supplier.name)}</h3>
        <p>${escapeHtml(supplier.location || "No location")} - ${escapeHtml(String(supplier.opportunity_count || 0))} opportunities</p>
      </div>
      <a class="btn btn-ghost" href="#/suppliers/${encodeURIComponent(supplier.id)}">Open</a>
    </div>
  `;
}

function renderOpportunityList() {
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>My Opportunities</h2><div class="meta">Track submitted, approved, and delivered lines.</div></div>
        <a class="btn btn-primary" href="#/opportunities/new">New Opportunity</a>
      </div>
      <section class="card">${state.opportunities.length ? `<div class="list">${state.opportunities.map(renderOpportunityRow).join("")}</div>` : `<div class="empty">No opportunities found.</div>`}</section>
    </div>
  `;
}

function statusChip(status) {
  const label = String(status || "unknown");
  return `<span class="chip ${escapeHtml(label)}">${escapeHtml(label)}</span>`;
}

function renderDuplicateBanner() {
  const context = state.duplicateContext;
  return `
    <section class="card" style="border-color: rgba(161, 98, 7, 0.34);">
      <div class="stack">
        <div class="brand-badge" style="background: rgba(161, 98, 7, 0.12); color: var(--warning);">Possible duplicate supplier</div>
        <p class="subtle">Review these likely matches before creating a new supplier.</p>
      </div>
      <div class="list" style="margin-top: 12px;">
        ${(context?.candidates || [])
          .map(
            (candidate) => `
              <div class="row">
                <div class="stack">
                  <h3>${escapeHtml(candidate.name)}</h3>
                  <p>${escapeHtml(candidate.location || "No location")} - Match: ${escapeHtml((candidate.match_reason || []).join(", "))}</p>
                </div>
                <div class="actions"><button class="btn btn-secondary" data-action="use-existing-supplier" data-kind="${escapeHtml(context.kind)}" data-supplier-id="${escapeHtml(candidate.id)}">Use existing</button></div>
              </div>`
          )
          .join("")}
        <div class="actions">
          <button class="btn btn-primary" data-action="confirm-new-record" data-kind="${escapeHtml(context.kind)}">Confirm new supplier</button>
          <button class="btn btn-ghost" data-action="dismiss-duplicate-warning">Dismiss</button>
        </div>
      </div>
    </section>
  `;
}

function rowLabel(label, value) {
  return `<div class="row" style="grid-template-columns: 180px 1fr;"><p class="subtle">${escapeHtml(label)}</p><div>${escapeHtml(value || "-")}</div></div>`;
}

function renderPhotoCard(photo) {
  return `
    <div class="photo-card">
      <img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.name || photo.photo_context || "photo")}" />
      <div class="subtle">${escapeHtml(photo.photo_context || "opportunity")}</div>
    </div>
  `;
}

async function uploadFiles(opportunityId, files, photoContext) {
  const uploaded = [];
  for (const file of files) {
    const result = await api.uploadPhoto(opportunityId, { file, photo_context: photoContext });
    uploaded.push(result.photo);
  }
  return uploaded;
}

async function handleLogin(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  setLoading(true);
  try {
    const result = await api.login(String(form.get("username") || ""), String(form.get("password") || ""));
    state.auth = {
      authenticated: true,
      user: result.user || null,
      permissions: result.permissions || {},
      capabilities: result.capabilities || null,
      site: result.site || null,
    };
    navigate("#/home");
    await loadRoute();
    showToast(`Signed in as ${state.auth.user?.display_name || state.auth.user?.username || "user"}`);
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Login failed");
  } finally {
    setLoading(false);
    render();
  }
}

async function handleLogout() {
  await api.logout();
  state.auth = { authenticated: false, user: null, permissions: {}, capabilities: null, site: null };
  state.opportunities = [];
  state.suppliers = [];
  state.opportunity = null;
  state.duplicateContext = null;
  navigate("#/login");
  render();
}

async function handleSearchInput(event) {
  const inputId = event.currentTarget.id;
  const query = event.currentTarget.value;
  const selectionStart = event.currentTarget.selectionStart ?? query.length;
  const selectionEnd = event.currentTarget.selectionEnd ?? query.length;
  state.supplierQuery = query;
  state.suppliers = await api.listSuppliers(query);
  render();
  const nextInput = app.querySelector(`#${inputId}`);
  if (nextInput) {
    nextInput.focus();
    nextInput.setSelectionRange(selectionStart, selectionEnd);
  }
}

async function submitOpportunityDraft(draft) {
  const result = await api.createOpportunity(draft.payload);
  if (result?.requires_confirmation) {
    state.duplicateContext = { ...draft, candidates: result.duplicate_candidates || [] };
    showToast("Possible duplicate supplier found.");
    render();
    return null;
  }
  await uploadFiles(result.id, draft.files || [], "opportunity");
  state.opportunity = await api.getOpportunity(result.id);
  state.duplicateContext = null;
  return result;
}

async function handleOpportunityCreate(event) {
  event.preventDefault();
  setLoading(true);
  try {
    persistOpportunityDraftFromForm(event.currentTarget);
    const payload = buildOpportunityPayload(new FormData(event.currentTarget));
    const files = pendingFilesFor("photo_upload").length
      ? pendingFilesFor("photo_upload")
      : selectedFilesFromForm(event.currentTarget, "photo_upload");
    const result = await submitOpportunityDraft({ kind: "opportunity", payload, files, formId: "create-opportunity" });
    if (result) {
      removeValue(OPPORTUNITY_DRAFT_KEY);
      clearPendingFiles("photo_upload");
      navigate(`#/opportunities/${encodeURIComponent(result.id)}`);
      await loadOpportunities();
      showToast("Opportunity created.");
    }
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to create opportunity");
  } finally {
    setLoading(false);
    await loadRoute();
    render();
  }
}

async function handleOpportunityEdit(event, id) {
  event.preventDefault();
  setLoading(true);
  try {
    await api.patchOpportunity(id, buildOpportunityPayload(new FormData(event.currentTarget)));
    await uploadFiles(
      id,
      pendingFilesFor("photo_upload").length ? pendingFilesFor("photo_upload") : selectedFilesFromForm(event.currentTarget, "photo_upload"),
      "opportunity",
    );
    clearPendingFiles("photo_upload");
    state.opportunity = await api.getOpportunity(id);
    navigate(`#/opportunities/${encodeURIComponent(id)}`);
    await loadOpportunities();
    showToast("Opportunity updated.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to update opportunity");
  } finally {
    setLoading(false);
    await loadRoute();
    render();
  }
}

async function handleDeliverySubmit(event, id) {
  event.preventDefault();
  setLoading(true);
  try {
    const form = new FormData(event.currentTarget);
    await api.recordDelivery(id, {
      delivered_weight_lbs: String(form.get("delivered_weight_lbs") || ""),
      delivery_date: String(form.get("delivery_date") || ""),
      testing_status: String(form.get("testing_status") || ""),
      actual_potency_pct: String(form.get("actual_potency_pct") || ""),
      clean_or_dirty: String(form.get("clean_or_dirty") || "clean"),
      delivery_notes: String(form.get("delivery_notes") || ""),
    });
    await uploadFiles(
      id,
      pendingFilesFor("delivery_photos").length ? pendingFilesFor("delivery_photos") : selectedFilesFromForm(event.currentTarget, "delivery_photos"),
      "delivery",
    );
    clearPendingFiles("delivery_photos");
    state.opportunity = await api.getOpportunity(id);
    navigate(`#/opportunities/${encodeURIComponent(id)}`);
    await loadOpportunities();
    showToast("Delivery recorded.");
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to record delivery");
  } finally {
    setLoading(false);
    await loadRoute();
    render();
  }
}

async function handleSupplierCreate(event) {
  event.preventDefault();
  setLoading(true);
  try {
    persistSupplierDraftFromForm(event.currentTarget);
    const payload = buildSupplierPayload(new FormData(event.currentTarget));
    const result = await api.createSupplier(payload);
    if (result.requires_confirmation) {
      state.duplicateContext = { kind: "supplier", payload, candidates: result.duplicate_candidates || [] };
      showToast("Possible duplicate supplier found.");
      render();
      return;
    }
    state.duplicateContext = null;
    removeValue(SUPPLIER_DRAFT_KEY);
    showToast(`Supplier created: ${result.supplier?.name || payload.name}`);
    navigate("#/suppliers");
    await loadSuppliers();
  } catch (error) {
    showToast(error.payload?.error?.message || error.message || "Unable to create supplier");
  } finally {
    setLoading(false);
    await loadRoute();
    render();
  }
}

async function handleDuplicateAction(event) {
  const action = event.target.getAttribute("data-action");
  if (!action) return;
  const kind = event.target.getAttribute("data-kind");

  if (action === "dismiss-duplicate-warning") {
    state.duplicateContext = null;
    render();
    return;
  }

  if (action === "use-existing-supplier") {
    const supplierId = event.target.getAttribute("data-supplier-id");
    const candidate = state.duplicateContext?.candidates?.find((item) => item.id === supplierId);
    if (!candidate) return;
    if (kind === "opportunity" && state.duplicateContext?.payload) {
      state.duplicateContext.payload.supplier_id = supplierId;
      delete state.duplicateContext.payload.new_supplier;
      state.duplicateContext.candidates = [];
      const supplierSelect = app.querySelector("#supplier_id");
      const nameInput = app.querySelector("#new_supplier_name");
      if (supplierSelect) supplierSelect.value = supplierId;
      if (nameInput) nameInput.value = "";
      showToast(`Using existing supplier: ${candidate.name}`);
      return;
    }
    if (kind === "supplier") {
      state.duplicateContext = null;
      navigate(`#/suppliers?q=${encodeURIComponent(candidate.name)}`);
      showToast(`Search existing supplier instead: ${candidate.name}`);
      return;
    }
  }

  if (action === "confirm-new-record" && kind === "opportunity" && state.duplicateContext?.payload) {
    setLoading(true);
    try {
      state.duplicateContext.payload.new_supplier = {
        ...(state.duplicateContext.payload.new_supplier || {}),
        confirm_new_supplier: true,
      };
      const result = await submitOpportunityDraft(state.duplicateContext);
      if (result) {
        navigate(`#/opportunities/${encodeURIComponent(result.id)}`);
        await loadOpportunities();
        showToast("Opportunity created after duplicate verification.");
      }
    } catch (error) {
      showToast(error.payload?.error?.message || error.message || "Unable to create opportunity");
    } finally {
      setLoading(false);
      await loadRoute();
      render();
    }
    return;
  }

  if (action === "confirm-new-record" && kind === "supplier" && state.duplicateContext?.payload) {
    setLoading(true);
    try {
      const payload = { ...state.duplicateContext.payload, confirm_new_supplier: true };
      const result = await api.createSupplier(payload);
      if (result.requires_confirmation) {
        state.duplicateContext.candidates = result.duplicate_candidates || [];
        render();
        return;
      }
      state.duplicateContext = null;
      showToast(`Supplier created: ${result.supplier?.name || payload.name}`);
      navigate("#/suppliers");
      await loadSuppliers();
    } catch (error) {
      showToast(error.payload?.error?.message || error.message || "Unable to create supplier");
    } finally {
      setLoading(false);
      await loadRoute();
      render();
    }
  }
}

function bind() {
  const loginForm = app.querySelector('[data-form="login"]');
  if (loginForm) loginForm.addEventListener("submit", handleLogin);

  const logoutBtn = app.querySelector('[data-action="logout"]');
  if (logoutBtn) logoutBtn.addEventListener("click", handleLogout);

  const searchInput = app.querySelector("#supplier-search") || app.querySelector("#supplier-search-page");
  if (searchInput) searchInput.addEventListener("input", handleSearchInput);

  const createForm = app.querySelector('[data-form="create-opportunity"]');
  if (createForm) {
    createForm.addEventListener("submit", handleOpportunityCreate);
    createForm.addEventListener("input", () => persistOpportunityDraftFromForm(createForm));
    createForm.addEventListener("change", () => persistOpportunityDraftFromForm(createForm));
  }

  const editForm = app.querySelector('[data-form="edit-opportunity"]');
  if (editForm) {
    const id = editForm.getAttribute("data-id");
    editForm.addEventListener("submit", (event) => handleOpportunityEdit(event, id));
  }

  const deliveryForm = app.querySelector('[data-form="delivery"]');
  if (deliveryForm) {
    const id = deliveryForm.getAttribute("data-id");
    deliveryForm.addEventListener("submit", (event) => handleDeliverySubmit(event, id));
  }

  const supplierForm = app.querySelector('[data-form="create-supplier"]');
  if (supplierForm) {
    supplierForm.addEventListener("submit", handleSupplierCreate);
    supplierForm.addEventListener("input", () => persistSupplierDraftFromForm(supplierForm));
    supplierForm.addEventListener("change", () => persistSupplierDraftFromForm(supplierForm));
  }

  app.querySelectorAll('[data-action="use-existing-supplier"], [data-action="confirm-new-record"], [data-action="dismiss-duplicate-warning"]').forEach((button) => {
    button.addEventListener("click", handleDuplicateAction);
  });

  app.querySelectorAll('input[type="file"]').forEach((input) => {
    input.addEventListener("change", () => {
      const files = queueFiles(input.name, [...(input.files || [])]);
      const helper = input.closest(".field")?.querySelector(".helper");
      if (helper) helper.textContent = `${files.length} file(s) selected. Additional picks will be added, not replaced.`;
      input.value = "";
    });
  });
}

function renderOpportunityDetail() {
  const item = state.opportunity;
  if (!item) return `<div class="empty">Opportunity not found.</div>`;
  const canEdit = isOpportunityEditable(item.status);
  const deliveryAllowed = canRecordDelivery(item.status);
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>${escapeHtml(opportunityTitle(item))}</h2><div class="meta">Status driven workflow for opportunity to delivery.</div></div>
        <div class="actions">
          ${statusChip(item.status)}
          ${canEdit ? `<a class="btn btn-secondary" href="#/opportunities/${encodeURIComponent(item.id)}/edit">Edit Opportunity</a>` : ""}
          ${deliveryAllowed ? `<a class="btn btn-primary" href="#/opportunities/${encodeURIComponent(item.id)}/delivery">Record Delivery</a>` : ""}
        </div>
      </div>
      <section class="grid-2">
        <div class="card">
          <h3 style="margin-top:0;">Opportunity</h3>
          <div class="stack">
            ${rowLabel("Supplier", item.supplier?.name)}
            ${rowLabel("Strain", item.strain_name)}
            ${rowLabel("Expected weight", `${item.expected_weight_lbs} lbs`)}
            ${rowLabel("Potency", item.expected_potency_pct ? `${item.expected_potency_pct}%` : "Not set")}
            ${rowLabel("Price", item.offered_price_per_lb ? `$${item.offered_price_per_lb}/lb` : "Not set")}
            ${rowLabel("Availability", item.availability_date || "Not set")}
            ${rowLabel("Clean / dirty", item.clean_or_dirty || "clean")}
            ${rowLabel("Testing notes", item.testing_notes || "None")}
            ${rowLabel("Notes", item.notes || "None")}
          </div>
        </div>
        <div class="card">
          <h3 style="margin-top:0;">Status and delivery</h3>
          <div class="stack">
            ${rowLabel("Editable", canEdit ? "Yes, before approval" : "Locked")}
            ${rowLabel("Delivery allowed", deliveryAllowed ? "Yes" : "No")}
            ${rowLabel("Submitted", shortDateTime(item.submitted_at))}
            ${rowLabel("Updated", shortDateTime(item.updated_at))}
            ${rowLabel("Approved at", item.approval?.approved_at ? shortDateTime(item.approval.approved_at) : "Not yet")}
            ${rowLabel("Approved by", item.approval?.approved_by_name || "Not yet")}
            ${rowLabel("Delivery status", item.delivery ? "Delivered" : "Pending")}
          </div>
        </div>
      </section>
      <section class="card">
        <h3 style="margin-top:0;">Photos</h3>
        ${item.photos?.length ? `<div class="photo-grid">${item.photos.map(renderPhotoCard).join("")}</div>` : `<div class="empty">No photos uploaded yet.</div>`}
      </section>
      ${
        item.delivery
          ? `<section class="card"><h3 style="margin-top:0;">Delivery</h3><div class="grid-2">${rowLabel("Delivered weight", `${item.delivery.delivered_weight_lbs} lbs`)}${rowLabel("Delivery date", item.delivery.delivery_date)}${rowLabel("Testing status", item.delivery.testing_status)}${rowLabel("Actual potency", item.delivery.actual_potency_pct ? `${item.delivery.actual_potency_pct}%` : "Not set")}${rowLabel("Delivered by", item.delivery.delivered_by_name || "Unknown")}${rowLabel("Notes", item.delivery.delivery_notes || "None")}</div></section>`
          : ""
      }
    </div>
  `;
}

function renderOpportunityForm(mode, opportunity = null) {
  const isEdit = mode === "edit";
  const source = isEdit
    ? opportunity
    : state.duplicateContext?.kind === "opportunity"
      ? state.duplicateContext.payload
      : currentOpportunityDraft();
  const selectedSupplierId = String(source?.supplier?.id || source?.supplier_id || "");
  const supplierNameValue = source?.new_supplier?.name || source?.new_supplier_name || "";
  const supplierContactValue = source?.new_supplier?.contact_name || source?.new_supplier_contact_name || "";
  const supplierPhoneValue = source?.new_supplier?.phone || source?.new_supplier_phone || "";
  const supplierEmailValue = source?.new_supplier?.email || source?.new_supplier_email || "";
  const supplierLocationValue = source?.new_supplier?.location || source?.new_supplier_location || "";
  const confirmNewSupplierValue = Boolean(source?.new_supplier?.confirm_new_supplier || source?.confirm_new_supplier);
  const supplierOptions = state.suppliers
    .map((supplier) => `<option value="${escapeHtml(supplier.id)}" ${selectedSupplierId === supplier.id ? "selected" : ""}>${escapeHtml(supplier.name)}${supplier.location ? ` - ${escapeHtml(supplier.location)}` : ""}</option>`)
    .join("");
  return `
    <div class="layout-grid">
      <div class="topbar"><div><h2>${isEdit ? "Edit Opportunity" : "New Opportunity"}</h2><div class="meta">${isEdit ? "Only editable before approval." : "Create a new buying opportunity."}</div></div></div>
      ${!isEdit && state.duplicateContext?.kind === "opportunity" ? renderDuplicateBanner() : ""}
      <section class="panel">
        <form class="form" data-form="${isEdit ? "edit-opportunity" : "create-opportunity"}" ${isEdit ? `data-id="${escapeHtml(opportunity.id)}"` : ""}>
          <div class="grid-2">
            <div class="field"><label for="supplier_id">Existing supplier</label><select id="supplier_id" name="supplier_id"><option value="">Choose existing supplier</option>${supplierOptions}</select><div class="helper">Use this if the supplier already exists.</div></div>
            <div class="field"><label for="new_supplier_name">Or create supplier</label><input id="new_supplier_name" name="new_supplier_name" placeholder="Farmlane" value="${escapeHtml(supplierNameValue)}" /><div class="helper">If no supplier matches, create one here.</div></div>
          </div>
          <div class="two-col">
            <div class="field"><label for="new_supplier_contact_name">Supplier contact</label><input id="new_supplier_contact_name" name="new_supplier_contact_name" placeholder="Contact name" value="${escapeHtml(supplierContactValue)}" /></div>
            <div class="field"><label for="new_supplier_phone">Supplier phone</label><input id="new_supplier_phone" name="new_supplier_phone" placeholder="555-0123" value="${escapeHtml(supplierPhoneValue)}" /></div>
          </div>
          <div class="two-col">
            <div class="field"><label for="new_supplier_email">Supplier email</label><input id="new_supplier_email" name="new_supplier_email" placeholder="sales@example.com" value="${escapeHtml(supplierEmailValue)}" /></div>
            <div class="field"><label for="new_supplier_location">Supplier location</label><input id="new_supplier_location" name="new_supplier_location" placeholder="Salinas, CA" value="${escapeHtml(supplierLocationValue)}" /></div>
          </div>
          <div class="field"><label for="strain_name">Strain</label><input id="strain_name" name="strain_name" required value="${escapeHtml(source?.strain_name || "")}" /></div>
          <div class="grid-3">
            <div class="field"><label for="expected_weight_lbs">Expected lbs</label><input id="expected_weight_lbs" name="expected_weight_lbs" inputmode="decimal" required value="${escapeHtml(source?.expected_weight_lbs || "")}" /></div>
            <div class="field"><label for="expected_potency_pct">Expected potency %</label><input id="expected_potency_pct" name="expected_potency_pct" inputmode="decimal" value="${escapeHtml(source?.expected_potency_pct || "")}" /></div>
            <div class="field"><label for="offered_price_per_lb">Price / lb</label><input id="offered_price_per_lb" name="offered_price_per_lb" inputmode="decimal" value="${escapeHtml(source?.offered_price_per_lb || "")}" /></div>
          </div>
          <div class="grid-2">
            <div class="field"><label for="availability_date">Availability date</label><input id="availability_date" name="availability_date" type="date" value="${escapeHtml(source?.availability_date || "")}" /></div>
            <div class="field"><label for="clean_or_dirty">Clean / dirty</label><select id="clean_or_dirty" name="clean_or_dirty"><option value="clean" ${source?.clean_or_dirty !== "dirty" ? "selected" : ""}>Clean</option><option value="dirty" ${source?.clean_or_dirty === "dirty" ? "selected" : ""}>Dirty</option></select></div>
          </div>
          <div class="field"><label for="testing_notes">Testing notes</label><textarea id="testing_notes" name="testing_notes">${escapeHtml(source?.testing_notes || "")}</textarea></div>
          <div class="field"><label for="notes">Notes</label><textarea id="notes" name="notes">${escapeHtml(source?.notes || "")}</textarea></div>
          <div class="field"><label for="photo_upload">Photos</label><input id="photo_upload" type="file" name="photo_upload" accept="image/*" multiple /><div class="helper">Photos are attached in one collection and tagged by context.</div></div>
          ${isEdit ? "" : `<div class="field"><label><input type="checkbox" name="confirm_new_supplier" ${confirmNewSupplierValue ? "checked" : ""} /> Confirm new supplier if duplicate is flagged</label></div>`}
          <div class="actions"><button class="btn btn-primary" type="submit">${state.loading ? "Saving..." : isEdit ? "Save changes" : "Submit opportunity"}</button><a class="btn btn-secondary" href="#/opportunities${opportunity?.id ? `/${encodeURIComponent(opportunity.id)}` : ""}">Cancel</a></div>
        </form>
      </section>
    </div>
  `;
}

function renderDeliveryForm() {
  const item = state.opportunity;
  if (!item) return `<div class="empty">Opportunity not found.</div>`;
  if (!canRecordDelivery(item.status)) return `<div class="empty">Delivery can only be recorded from approved or committed opportunities.</div>`;
  return `
    <div class="layout-grid">
      <div class="topbar"><div><h2>Record Delivery</h2><div class="meta">${escapeHtml(opportunityTitle(item))}</div></div></div>
      <section class="panel">
        <form class="form" data-form="delivery" data-id="${escapeHtml(item.id)}">
          <div class="grid-2">
            <div class="field"><label for="delivered_weight_lbs">Delivered lbs</label><input id="delivered_weight_lbs" name="delivered_weight_lbs" inputmode="decimal" required /></div>
            <div class="field"><label for="delivery_date">Delivery date</label><input id="delivery_date" name="delivery_date" type="date" required /></div>
          </div>
          <div class="grid-2">
            <div class="field"><label for="testing_status">Testing status</label><select id="testing_status" name="testing_status"><option value="pending">Pending</option><option value="completed">Completed</option><option value="waived">Waived</option></select></div>
            <div class="field"><label for="actual_potency_pct">Actual potency %</label><input id="actual_potency_pct" name="actual_potency_pct" inputmode="decimal" /></div>
          </div>
          <div class="field"><label for="clean_or_dirty">Clean / dirty</label><select id="clean_or_dirty" name="clean_or_dirty"><option value="clean">Clean</option><option value="dirty">Dirty</option></select></div>
          <div class="field"><label for="delivery_notes">Delivery notes</label><textarea id="delivery_notes" name="delivery_notes"></textarea></div>
          <div class="field"><label for="delivery_photos">Photos</label><input id="delivery_photos" type="file" name="delivery_photos" accept="image/*" multiple /><div class="helper">Delivery photos attach to the same opportunity collection and are tagged as delivery context.</div></div>
          <div class="actions"><button class="btn btn-primary" type="submit">${state.loading ? "Recording..." : "Record Delivery"}</button><a class="btn btn-secondary" href="#/opportunities/${encodeURIComponent(item.id)}">Cancel</a></div>
        </form>
      </section>
    </div>
  `;
}

function renderSuppliers() {
  return `
    <div class="layout-grid">
      <div class="topbar"><div><h2>Suppliers</h2><div class="meta">Search context before submitting an opportunity.</div></div><div class="actions"><a class="btn btn-primary" href="#/opportunities/new">New Opportunity</a><a class="btn btn-secondary" href="#/suppliers/new">Create Supplier</a></div></div>
      <section class="panel"><div class="field"><label for="supplier-search-page">Search suppliers</label><input id="supplier-search-page" name="q" placeholder="Search supplier name, location, email, or phone" value="${escapeHtml(state.supplierQuery)}" /></div></section>
      <section class="card">${state.suppliers.length ? `<div class="list">${state.suppliers.map(renderSupplierCard).join("")}</div>` : `<div class="empty">No suppliers match your search.</div>`}</section>
    </div>
  `;
}

function renderSupplierDetail() {
  const supplier = state.supplier;
  if (!supplier) return `<div class="empty">Supplier not found.</div>`;
  return `
    <div class="layout-grid">
      <div class="topbar">
        <div><h2>${escapeHtml(supplier.name)}</h2><div class="meta">Supplier context for buyer workflows.</div></div>
        <div class="actions">
          <a class="btn btn-secondary" href="#/suppliers">Back to search</a>
          <a class="btn btn-primary" href="#/opportunities/new?supplier_id=${encodeURIComponent(supplier.id)}">New Opportunity</a>
        </div>
      </div>
      <section class="grid-2">
        <div class="card">
          <h3 style="margin-top:0;">Supplier profile</h3>
          <div class="stack">
            ${rowLabel("Name", supplier.name)}
            ${rowLabel("Location", supplier.location || "Not set")}
            ${rowLabel("Contact", supplier.contact_name || "Not set")}
            ${rowLabel("Phone", supplier.phone || "Not set")}
            ${rowLabel("Email", supplier.email || "Not set")}
            ${rowLabel("Notes", supplier.notes || "None")}
          </div>
        </div>
        <div class="card">
          <h3 style="margin-top:0;">Context</h3>
          <div class="stack">
            ${rowLabel("Opportunities", String(supplier.opportunity_count || 0))}
            ${rowLabel("Open opportunities", String(supplier.open_count || 0))}
            ${rowLabel("Profile completeness", supplier.profile_incomplete ? "Needs follow-up" : "Complete enough")}
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderSupplierForm() {
  const draft = state.duplicateContext?.payload || readJson(SUPPLIER_DRAFT_KEY, supplierDraftDefaults()) || supplierDraftDefaults();
  return `
    <div class="layout-grid">
      <div class="topbar"><div><h2>Create Supplier</h2><div class="meta">Duplicates will be flagged for verification.</div></div></div>
      ${state.duplicateContext?.kind === "supplier" ? renderDuplicateBanner() : ""}
      <section class="panel">
        <form class="form" data-form="create-supplier">
          <div class="grid-2">
            <div class="field"><label for="name">Name</label><input id="name" name="name" required autocomplete="organization" value="${escapeHtml(draft.name || "")}" /></div>
            <div class="field"><label for="location">Location</label><input id="location" name="location" autocomplete="address-level2" value="${escapeHtml(draft.location || "")}" /></div>
          </div>
          <div class="grid-2">
            <div class="field"><label for="contact_name">Contact</label><input id="contact_name" name="contact_name" autocomplete="name" value="${escapeHtml(draft.contact_name || "")}" /></div>
            <div class="field"><label for="phone">Phone</label><input id="phone" name="phone" autocomplete="tel" value="${escapeHtml(draft.phone || "")}" /></div>
          </div>
          <div class="field"><label for="email">Email</label><input id="email" name="email" autocomplete="email" value="${escapeHtml(draft.email || "")}" /></div>
          <div class="field"><label for="notes">Notes</label><textarea id="notes" name="notes">${escapeHtml(draft.notes || "")}</textarea></div>
          <div class="field"><label><input type="checkbox" name="confirm_new_supplier" ${draft.confirm_new_supplier ? "checked" : ""} /> Confirm new supplier if a duplicate is flagged</label></div>
          <div class="actions"><button class="btn btn-primary" type="submit">${state.loading ? "Creating..." : "Create supplier"}</button><a class="btn btn-secondary" href="#/suppliers">Cancel</a></div>
        </form>
      </section>
    </div>
  `;
}
