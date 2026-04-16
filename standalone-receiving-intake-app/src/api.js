import { canConfirmReceipt } from "./domain.js";
import { cloneSeedState } from "./mock-data.js";
import { readJson, removeValue, writeJson } from "./storage.js";

const STATE_KEY = "gold-drop-receiving-intake-state-v1";
const SESSION_KEY = "gold-drop-receiving-intake-session-v1";

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

function ensureMockSession() {
  const session = loadSession();
  if (!session?.user) {
    const error = new Error("Not authenticated");
    error.status = 401;
    throw error;
  }
  return session;
}

function fileToDataUrl(file) {
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

function queueItemFromPayload(payload) {
  if (!payload) return payload;
  return {
    ...payload,
    supplier: payload.supplier || (payload.supplier_name ? { id: payload.supplier_id, name: payload.supplier_name } : null),
    photos: Array.isArray(payload.photos) ? payload.photos : [],
    lots: Array.isArray(payload.lots) ? payload.lots : [],
    receiving: payload.receiving || null,
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
          role: "receiver",
        },
        permissions: {
          can_receive_intake: true,
        },
        site: {
          site_code: "MOCK",
          site_name: "Gold Drop Mock Site",
          site_timezone: "America/Los_Angeles",
        },
      };
      saveSession(session);
      const state = loadState();
      state.session = session;
      saveState(state);
      return session;
    },
    async logout() {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/auth/logout", { method: "POST", body: JSON.stringify({}) }));
      }
      clearSession();
      const state = loadState();
      state.session = null;
      saveState(state);
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
    async listReceivingQueue(status = "ready") {
      if (mode === "live") {
        const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/receiving/queue${suffix}`));
        return Array.isArray(payload) ? payload.map(queueItemFromPayload) : [];
      }
      ensureMockSession();
      const state = loadState();
      const rows = state.receipts || [];
      if (!status || status === "all") return rows;
      if (status === "ready") return rows.filter((item) => canConfirmReceipt(item.status));
      return rows.filter((item) => String(item.status || "").toLowerCase() === String(status).toLowerCase());
    },
    async getReceivingItem(id) {
      if (mode === "live") {
        return queueItemFromPayload(unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/receiving/queue/${encodeURIComponent(id)}`)));
      }
      ensureMockSession();
      const item = (loadState().receipts || []).find((row) => row.id === id);
      if (!item) throw Object.assign(new Error("Receiving item not found"), { status: 404 });
      return item;
    },
    async receive(id, payload) {
      if (mode === "live") {
        const response = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/receiving/queue/${encodeURIComponent(id)}/receive`, {
          method: "POST",
          body: JSON.stringify(payload),
        }));
        return queueItemFromPayload(response?.receiving || response);
      }
      ensureMockSession();
      const state = loadState();
      const idx = state.receipts.findIndex((row) => row.id === id);
      if (idx < 0) throw Object.assign(new Error("Receiving item not found"), { status: 404 });
      const current = state.receipts[idx];
      const updated = {
        ...current,
        status: "delivered",
        delivery_allowed: false,
        delivery_needed: false,
        clean_or_dirty: payload.clean_or_dirty || current.clean_or_dirty,
        delivery: {
          delivered_weight_lbs: Number(payload.delivered_weight_lbs || current.expected_weight_lbs || 0),
          delivery_date: payload.delivery_date,
          testing_status: payload.testing_status || null,
          actual_potency_pct: payload.actual_potency_pct ? Number(payload.actual_potency_pct) : null,
          clean_or_dirty: payload.clean_or_dirty || current.clean_or_dirty,
          delivery_notes: payload.delivery_notes || "",
          delivered_by_name: state.session?.user?.display_name || "Receiving User",
        },
        lots: (current.lots || []).map((lot, index) =>
          index === 0
            ? {
                ...lot,
                weight_lbs: Number(payload.delivered_weight_lbs || lot.weight_lbs || 0),
                remaining_weight_lbs: Number(payload.delivered_weight_lbs || lot.remaining_weight_lbs || 0),
                location: payload.location || lot.location,
                floor_state: payload.floor_state || lot.floor_state,
                notes: payload.lot_notes || lot.notes || "",
              }
            : lot
        ),
        receiving: {
          queue_state: "closed",
          location: payload.location || current.receiving?.location || "",
          floor_state: payload.floor_state || current.receiving?.floor_state || "receiving",
          lot_count: current.receiving?.lot_count || (current.lots || []).length,
          photo_count: current.receiving?.photo_count || 0,
        },
      };
      state.receipts[idx] = updated;
      saveState(state);
      return updated;
    },
    async uploadPhoto(id, { file, photo_context }) {
      if (mode === "live") {
        const form = new FormData();
        form.append("photo_context", photo_context);
        form.append("photo", file);
        const response = await fetchImpl(`${apiBaseUrl}/api/mobile/v1/receiving/queue/${encodeURIComponent(id)}/photos`, {
          method: "POST",
          credentials: "include",
          body: form,
        });
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
        return unwrapData(await response.json());
      }
      ensureMockSession();
      const state = loadState();
      const idx = state.receipts.findIndex((row) => row.id === id);
      if (idx < 0) throw Object.assign(new Error("Receiving item not found"), { status: 404 });
      const photo = {
        id: `photo-${Date.now()}`,
        url: await fileToDataUrl(file),
        name: file.name,
        photo_context,
      };
      state.receipts[idx].photos = [...(state.receipts[idx].photos || []), photo];
      state.receipts[idx].receiving = {
        ...(state.receipts[idx].receiving || {}),
        photo_count: (state.receipts[idx].receiving?.photo_count || 0) + 1,
      };
      saveState(state);
      return {
        photo_context,
        count: state.receipts[idx].photos.length,
        photos: state.receipts[idx].photos,
      };
    },
  };
}
