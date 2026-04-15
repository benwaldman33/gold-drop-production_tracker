import { canRecordDelivery, findDuplicateSupplierCandidates, isOpportunityEditable, normalizeText } from "./domain.js";
import { cloneSeedState } from "./mock-data.js";
import { readJson, removeValue, writeJson } from "./storage.js";

const STATE_KEY = "gold-drop-purchasing-agent-state-v1";
const SESSION_KEY = "gold-drop-purchasing-agent-session-v1";

function loadState() {
  return readJson(STATE_KEY, cloneSeedState());
}

function saveState(state) {
  writeJson(STATE_KEY, state);
}

function loadSession() {
  return readJson(SESSION_KEY, null);
}

function saveSession(session) {
  writeJson(SESSION_KEY, session);
}

function clearSession() {
  removeValue(SESSION_KEY);
}

function nowIso() {
  return new Date().toISOString();
}

function toOpportunitySummary(opportunity) {
  return {
    id: opportunity.id,
    status: opportunity.status,
    editable: isOpportunityEditable(opportunity.status),
    delivery_allowed: canRecordDelivery(opportunity.status),
    supplier_name: opportunity.supplier?.name || "",
    strain_name: opportunity.strain_name || "",
    expected_weight_lbs: opportunity.expected_weight_lbs || 0,
    submitted_at: opportunity.submitted_at || opportunity.updated_at || nowIso(),
    delivery_needed: Boolean(opportunity.delivery_allowed || opportunity.status === "approved" || opportunity.status === "committed"),
  };
}

function matchesStatusFilter(opportunity, status) {
  if (!status) return true;
  return normalizeText(opportunity.status) === normalizeText(status);
}

function filterSuppliers(query, suppliers) {
  const q = normalizeText(query);
  if (!q) return suppliers;
  return suppliers.filter((supplier) => {
    const haystack = normalizeText([supplier.name, supplier.location, supplier.contact_name, supplier.phone, supplier.email].filter(Boolean).join(" "));
    return haystack.includes(q);
  });
}

function ensureMockSession() {
  const session = loadSession();
  if (!session?.user) {
    const error = new Error("Not authenticated");
    error.status = 401;
    throw error;
  }
  return session;
}

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error || new Error("Unable to read file"));
    reader.readAsDataURL(file);
  });
}

function liveRequest(baseUrl, fetchImpl, path, options = {}) {
  return fetchImpl(`${baseUrl}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  }).then(async (response) => {
    if (!response.ok) {
      const error = new Error(`Request failed with status ${response.status}`);
      error.status = response.status;
      try {
        error.payload = await response.json();
      } catch {
        error.payload = null;
      }
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  });
}

function unwrapData(payload) {
  if (payload && typeof payload === "object" && "data" in payload) return payload.data;
  return payload;
}

function supplierFromRow(row) {
  if (!row) return row;
  if (row.supplier?.id || row.supplier?.name) {
    return {
      id: row.supplier.id,
      name: row.supplier.name,
      location: row.location || "",
      contact_name: row.contact_name || "",
      phone: row.contact_phone || row.phone || "",
      email: row.contact_email || row.email || "",
      notes: row.notes || "",
      opportunity_count: row.opportunity_count || 0,
      open_count: row.open_count || 0,
      profile_incomplete: Boolean(row.profile_incomplete),
    };
  }
  return {
    id: row.id,
    name: row.name || row.label || "",
    location: row.location || row.subtitle || "",
    contact_name: row.contact_name || "",
    phone: row.phone || "",
    email: row.email || "",
    notes: row.notes || "",
    opportunity_count: row.opportunity_count || 0,
    open_count: row.open_count || 0,
    profile_incomplete: Boolean(row.profile_incomplete),
  };
}

function opportunityFromPayload(payload) {
  if (!payload) return payload;
  return {
    ...payload,
    supplier: payload.supplier || (payload.supplier_name ? { id: payload.supplier_id, name: payload.supplier_name } : null),
    photos: Array.isArray(payload.photos) ? payload.photos : [],
  };
}

export function createApiClient({ mode = "mock", apiBaseUrl = "", fetchImpl = fetch } = {}) {
  return {
    mode,
    async login(username, password) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        }));
      }

      if (!username || !password) {
        const error = new Error("Username and password are required");
        error.status = 400;
        throw error;
      }
      const session = {
        authenticated: true,
        user: {
          id: `user-${username}`,
          username,
          display_name: username.replace(/(^|[\s._-])([a-z])/g, (_, p1, p2) => `${p1}${p2.toUpperCase()}`),
          role: "buyer",
        },
        permissions: {
          can_create_opportunity: true,
          can_edit_preapproval_opportunity: true,
          can_record_delivery: true,
          can_create_supplier: true,
        },
        site: {
          site_code: "MOCK",
          site_name: "Gold Drop Mock Site",
          site_timezone: "America/Los_Angeles",
        },
      };
      const state = loadState();
      state.session = session;
      saveState(state);
      saveSession(session);
      return session;
    },
    async logout() {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/auth/logout", { method: "POST", body: JSON.stringify({}) }));
      }
      const state = loadState();
      state.session = null;
      saveState(state);
      clearSession();
      return { ok: true };
    },
    async me() {
      if (mode === "live") {
        try {
          return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/auth/me"));
        } catch (error) {
          if (error.status === 401) return { authenticated: false };
          throw error;
        }
      }
      return loadSession() || { authenticated: false };
    },
    async listSuppliers(query = "") {
      if (mode === "live") {
        const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/suppliers${suffix}`));
        return Array.isArray(payload) ? payload.map(supplierFromRow) : [];
      }
      const state = loadState();
      return filterSuppliers(query, state.suppliers).map((supplier) => ({
        ...supplier,
        opportunity_count: state.opportunities.filter((opp) => opp.supplier?.id === supplier.id).length,
        open_count: state.opportunities.filter((opp) => opp.supplier?.id === supplier.id && canRecordDelivery(opp.status)).length,
      }));
    },
    async getSupplier(id) {
      if (mode === "live") {
        return supplierFromRow(unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/suppliers/${encodeURIComponent(id)}`)));
      }
      const state = loadState();
      const supplier = state.suppliers.find((item) => item.id === id);
      if (!supplier) throw Object.assign(new Error("Supplier not found"), { status: 404 });
      return supplier;
    },
    async createSupplier(payload) {
      if (mode === "live") {
        const response = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/suppliers", {
          method: "POST",
          body: JSON.stringify(payload),
        }));
        if (response?.requires_confirmation) return response;
        if (response?.supplier) return { supplier: supplierFromRow(response.supplier) };
        return response;
      }
      ensureMockSession();
      const state = loadState();
      const matches = findDuplicateSupplierCandidates(payload.name, state.suppliers);
      if (matches.length && !payload.confirm_new_supplier) {
        return { requires_confirmation: true, duplicate_candidates: matches.slice(0, 5) };
      }
      const supplier = {
        id: `sup-${Date.now()}`,
        name: payload.name,
        contact_name: payload.contact_name || "",
        phone: payload.phone || "",
        email: payload.email || "",
        location: payload.location || "",
        notes: payload.notes || "",
      };
      state.suppliers.unshift(supplier);
      saveState(state);
      return { supplier };
    },
    async listOpportunitiesMine(status = "") {
      if (mode === "live") {
        const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/opportunities/mine${suffix}`));
        return Array.isArray(payload) ? payload.map(opportunityFromPayload) : [];
      }
      ensureMockSession();
      const state = loadState();
      return state.opportunities.filter((opp) => matchesStatusFilter(opp, status)).map(toOpportunitySummary);
    },
    async getOpportunity(id) {
      if (mode === "live") {
        return opportunityFromPayload(unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/opportunities/${encodeURIComponent(id)}`)));
      }
      ensureMockSession();
      const state = loadState();
      const opportunity = state.opportunities.find((item) => item.id === id);
      if (!opportunity) throw Object.assign(new Error("Opportunity not found"), { status: 404 });
      return JSON.parse(JSON.stringify(opportunity));
    },
    async createOpportunity(payload) {
      if (mode === "live") {
        const response = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/opportunities", {
          method: "POST",
          body: JSON.stringify(payload),
        }));
        if (response?.requires_confirmation) return response;
        if (response?.opportunity) return opportunityFromPayload(response.opportunity);
        return opportunityFromPayload(response);
      }
      ensureMockSession();
      const state = loadState();
      let supplier = null;
      if (payload.supplier_id) {
        supplier = state.suppliers.find((item) => item.id === payload.supplier_id) || null;
      } else if (payload.new_supplier?.name) {
        const supplierResult = await this.createSupplier({ ...payload.new_supplier, confirm_new_supplier: payload.new_supplier.confirm_new_supplier });
        if (supplierResult.requires_confirmation) return supplierResult;
        supplier = supplierResult.supplier;
      }
      if (!supplier) {
        const error = new Error("Supplier is required");
        error.status = 400;
        throw error;
      }
      const opportunity = {
        id: `opp-${Date.now()}`,
        status: "submitted",
        editable: true,
        delivery_allowed: false,
        supplier: {
          id: supplier.id,
          name: supplier.name,
        },
        strain_name: payload.strain_name,
        expected_weight_lbs: Number(payload.expected_weight_lbs),
        expected_potency_pct: payload.expected_potency_pct ? Number(payload.expected_potency_pct) : null,
        offered_price_per_lb: payload.offered_price_per_lb ? Number(payload.offered_price_per_lb) : null,
        availability_date: payload.availability_date || "",
        clean_or_dirty: payload.clean_or_dirty || "clean",
        testing_notes: payload.testing_notes || "",
        notes: payload.notes || "",
        approval: null,
        delivery: null,
        photos: payload.photos || [],
        submitted_at: nowIso(),
        updated_at: nowIso(),
        delivery_needed: false,
      };
      state.opportunities.unshift(opportunity);
      saveState(state);
      return JSON.parse(JSON.stringify(opportunity));
    },
    async patchOpportunity(id, payload) {
      if (mode === "live") {
        const response = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/opportunities/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        }));
        return opportunityFromPayload(response?.opportunity || response);
      }
      ensureMockSession();
      const state = loadState();
      const opportunity = state.opportunities.find((item) => item.id === id);
      if (!opportunity) throw Object.assign(new Error("Opportunity not found"), { status: 404 });
      if (!isOpportunityEditable(opportunity.status)) {
        const error = new Error("Opportunity can no longer be edited after approval.");
        error.status = 409;
        throw error;
      }
      if (payload.supplier_id) {
        const supplier = state.suppliers.find((item) => item.id === payload.supplier_id);
        if (supplier) opportunity.supplier = { id: supplier.id, name: supplier.name };
      }
      if (payload.strain_name !== undefined) opportunity.strain_name = payload.strain_name;
      if (payload.expected_weight_lbs !== undefined) opportunity.expected_weight_lbs = Number(payload.expected_weight_lbs);
      if (payload.expected_potency_pct !== undefined) opportunity.expected_potency_pct = payload.expected_potency_pct === "" ? null : Number(payload.expected_potency_pct);
      if (payload.offered_price_per_lb !== undefined) opportunity.offered_price_per_lb = payload.offered_price_per_lb === "" ? null : Number(payload.offered_price_per_lb);
      if (payload.availability_date !== undefined) opportunity.availability_date = payload.availability_date;
      if (payload.clean_or_dirty !== undefined) opportunity.clean_or_dirty = payload.clean_or_dirty;
      if (payload.testing_notes !== undefined) opportunity.testing_notes = payload.testing_notes;
      if (payload.notes !== undefined) opportunity.notes = payload.notes;
      opportunity.updated_at = nowIso();
      saveState(state);
      return JSON.parse(JSON.stringify(opportunity));
    },
    async recordDelivery(id, payload) {
      if (mode === "live") {
        const response = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/opportunities/${encodeURIComponent(id)}/delivery`, {
          method: "POST",
          body: JSON.stringify(payload),
        }));
        return opportunityFromPayload(response?.opportunity || response);
      }
      ensureMockSession();
      const state = loadState();
      const opportunity = state.opportunities.find((item) => item.id === id);
      if (!opportunity) throw Object.assign(new Error("Opportunity not found"), { status: 404 });
      if (!canRecordDelivery(opportunity.status)) {
        const error = new Error("Delivery can only be recorded for approved or committed opportunities.");
        error.status = 409;
        throw error;
      }
      opportunity.delivery = {
        delivered_weight_lbs: Number(payload.delivered_weight_lbs),
        delivery_date: payload.delivery_date,
        testing_status: payload.testing_status,
        actual_potency_pct: payload.actual_potency_pct ? Number(payload.actual_potency_pct) : null,
        clean_or_dirty: payload.clean_or_dirty || opportunity.clean_or_dirty || "clean",
        delivery_notes: payload.delivery_notes || "",
        delivered_by_name: loadSession()?.user?.display_name || "Buyer",
      };
      opportunity.status = "delivered";
      opportunity.editable = false;
      opportunity.delivery_allowed = false;
      opportunity.updated_at = nowIso();
      if (Array.isArray(payload.photos) && payload.photos.length) {
        opportunity.photos = [...opportunity.photos, ...payload.photos];
      }
      saveState(state);
      return JSON.parse(JSON.stringify(opportunity));
    },
    async uploadPhoto(id, { file, photo_context }) {
      if (mode === "live") {
        const form = new FormData();
        form.append("photo", file);
        form.append("photo_context", photo_context);
        const response = await fetchImpl(`${apiBaseUrl}/api/mobile/v1/opportunities/${encodeURIComponent(id)}/photos`, {
          method: "POST",
          credentials: "include",
          body: form,
        });
        if (!response.ok) {
          const error = new Error(`Upload failed with status ${response.status}`);
          error.status = response.status;
          try {
            error.payload = await response.json();
          } catch {
            error.payload = null;
          }
          throw error;
        }
        const payload = unwrapData(await response.json());
        const photos = Array.isArray(payload?.photos) ? payload.photos : [];
        return {
          photo_context: payload?.photo_context,
          count: payload?.count ?? photos.length,
          photos,
          photo: photos[0] || null,
        };
      }
      ensureMockSession();
      const state = loadState();
      const opportunity = state.opportunities.find((item) => item.id === id);
      if (!opportunity) throw Object.assign(new Error("Opportunity not found"), { status: 404 });
      const preview = await fileToDataUrl(file);
      const photo = {
        id: `photo-${Date.now()}`,
        url: preview,
        name: file.name,
        size: file.size,
        photo_context,
      };
      opportunity.photos = [...(opportunity.photos || []), photo];
      opportunity.updated_at = nowIso();
      saveState(state);
      return { photo };
    },
    async dashboard() {
      const opportunities = await this.listOpportunitiesMine();
      return {
        total: opportunities.length,
        pending: opportunities.filter((item) => item.status === "submitted").length,
        approved: opportunities.filter((item) => item.status === "approved").length,
        committed: opportunities.filter((item) => item.status === "committed").length,
        delivered: opportunities.filter((item) => item.status === "delivered").length,
      };
    },
  };
}
