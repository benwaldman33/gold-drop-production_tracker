import { cloneSeedState } from "./mock-data.js";
import { readJson, removeValue, writeJson } from "./storage.js";

const STATE_KEY = "gold-drop-extraction-lab-state-v1";
const SESSION_KEY = "gold-drop-extraction-lab-session-v1";

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

function boardViewOptions() {
  return [
    { value: "all", label: "All reactors" },
    { value: "active", label: "Active only" },
    { value: "pending", label: "Pending only" },
    { value: "running", label: "Running only" },
    { value: "completed_today", label: "Completed today" },
    { value: "cancelled_today", label: "Cancelled today" },
  ];
}

function historyEntry(label, toState) {
  return {
    label,
    timestamp_label: new Date().toLocaleString(),
    details: toState ? { to_state: toState } : {},
  };
}

function buildMockBoard(state, boardView = "all") {
  const charges = state.charges || [];
  const configuredReactors = 3;
  const cards = [];
  for (let reactorNumber = 1; reactorNumber <= configuredReactors; reactorNumber += 1) {
    const charge = charges.find((row) => Number(row.reactor_number) === reactorNumber);
    const stateKey = charge?.status || "empty";
    const visible =
      boardView === "all" ||
      (boardView === "active" && stateKey !== "empty") ||
      (boardView === "pending" && ["pending", "in_reactor", "applied"].includes(stateKey)) ||
      (boardView === "running" && stateKey === "running") ||
      (boardView === "completed_today" && stateKey === "completed") ||
      (boardView === "cancelled_today" && stateKey === "cancelled");
    if (!visible) continue;
    cards.push({
      reactor_number: reactorNumber,
      state_key: stateKey,
      state_label: charge?.state_label || "Empty",
      state_badge: "badge",
      next_step: charge ? "Advance the lifecycle or open the linked run." : "Ready for the next charge.",
      pending_count: charge ? 1 : 0,
      pending_weight_lbs: charge ? Number(charge.charged_weight_lbs || 0) : 0,
      show_history: true,
      current: charge
        ? {
            charge_id: charge.id,
            tracking_id: charge.tracking_id,
            lot_id: charge.lot_id || "lot-1001",
            supplier_name: charge.supplier_name,
            strain_name: charge.strain_name,
            charged_weight_lbs: Number(charge.charged_weight_lbs || 0),
            charged_at_label: charge.charged_at_label,
            operator_name: "Extractor One",
            state_key: charge.status,
            state_label: charge.state_label,
            source_mode: charge.source_mode,
            run_id: charge.run_id || null,
            available_actions:
              charge.status === "running"
                ? [{ target_state: "completed", label: "Mark Complete" }, { target_state: "cancelled", label: "Cancel Charge" }]
                : [{ target_state: "in_reactor", label: "Mark In Reactor" }, { target_state: "running", label: "Mark Running" }],
            history: charge.history || [],
          }
        : null,
    });
  }

  return {
    summary: {
      open_lot_count: state.lots.length,
      ready_lot_count: state.lots.filter((lot) => lot.ready_for_charge).length,
      pending_charge_count: charges.filter((charge) => ["pending", "in_reactor", "applied", "running"].includes(charge.status)).length,
      pending_charge_weight_lbs: charges.reduce((sum, charge) => sum + Number(charge.charged_weight_lbs || 0), 0),
      active_reactor_count: charges.length,
      reactor_count: configuredReactors,
    },
    board_view: boardView,
    board_view_options: boardViewOptions(),
    reactor_cards: cards,
    pending_cards: cards.filter((card) => card.current).map((card) => ({ reactor_number: card.reactor_number, count: card.current ? 1 : 0, total_lbs: card.current?.charged_weight_lbs || 0, charges: card.current ? [card.current] : [] })),
    applied_cards: [],
    reactor_history: cards.map((card) => ({ reactor_number: card.reactor_number, state_label: card.state_label, entries: card.current?.history || [] })),
    floor_state_cards: [
      { key: "inventory", label: "In inventory", count: state.lots.filter((lot) => lot.floor_state === "inventory").length },
      { key: "reactor_staging", label: "Reactor staging", count: state.lots.filter((lot) => lot.floor_state === "reactor_staging").length },
    ],
  };
}

function mockChargePayload(state, charge) {
  const lot = state.lots.find((row) => row.id === charge.purchase_lot_id) || state.lots[0];
  return {
    id: charge.id,
    status: charge.status,
    state_label: charge.state_label,
    reactor_number: charge.reactor_number,
    charged_weight_lbs: charge.charged_weight_lbs,
    charged_at: charge.charged_at,
    charged_at_label: charge.charged_at_label,
    source_mode: charge.source_mode,
    notes: charge.notes,
    run_id: charge.run_id || null,
    tracking_id: lot?.tracking_id || null,
    supplier_name: lot?.supplier_name || "Unknown",
    strain_name: lot?.strain_name || "Unknown",
    history: charge.history || [],
  };
}

export function createApiClient({ mode = "mock", apiBaseUrl = "", fetchImpl = fetch } = {}) {
  return {
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
      const state = loadState();
      saveSession(state.session);
      return state.session;
    },
    async logout() {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, "/api/mobile/v1/auth/logout", { method: "POST", body: JSON.stringify({}) }));
      }
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
    async getBoard(boardView = "all") {
      if (mode === "live") {
        const suffix = boardView ? `?board_view=${encodeURIComponent(boardView)}` : "";
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/board${suffix}`));
      }
      ensureMockSession();
      return buildMockBoard(loadState(), boardView);
    },
    async listLots(query = "") {
      if (mode === "live") {
        const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/lots${suffix}`));
        return Array.isArray(payload) ? payload : [];
      }
      ensureMockSession();
      const state = loadState();
      const q = String(query || "").trim().toLowerCase();
      if (!q) return state.lots;
      return state.lots.filter((lot) =>
        [lot.tracking_id, lot.batch_id, lot.supplier_name, lot.strain_name].some((value) => String(value || "").toLowerCase().includes(q))
      );
    },
    async getLot(id) {
      if (mode === "live") {
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/lots/${encodeURIComponent(id)}`));
        return payload?.lot || payload;
      }
      ensureMockSession();
      const lot = loadState().lots.find((row) => row.id === id);
      if (!lot) throw Object.assign(new Error("Lot not found"), { status: 404 });
      return lot;
    },
    async lookupLot(trackingId) {
      if (mode === "live") {
        const payload = unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/lookup/${encodeURIComponent(trackingId)}`));
        return payload?.lot || payload;
      }
      ensureMockSession();
      const lot = loadState().lots.find((row) => row.tracking_id === trackingId);
      if (!lot) throw Object.assign(new Error("Lot not found"), { status: 404 });
      return lot;
    },
    async createCharge(lotId, payload) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/lots/${encodeURIComponent(lotId)}/charge`, {
          method: "POST",
          body: JSON.stringify(payload),
        }));
      }
      ensureMockSession();
      const state = loadState();
      const lot = state.lots.find((row) => row.id === lotId);
      if (!lot) throw Object.assign(new Error("Lot not found"), { status: 404 });
      const charge = {
        id: `chg-${Date.now()}`,
        purchase_lot_id: lot.id,
        status: "pending",
        state_label: "Charged / waiting",
        reactor_number: Number(payload.reactor_number || 1),
        charged_weight_lbs: Number(payload.charged_weight_lbs || 0),
        charged_at: payload.charged_at,
        charged_at_label: new Date(payload.charged_at).toLocaleString(),
        source_mode: "standalone_extraction",
        notes: payload.notes || "",
        run_id: null,
        history: [historyEntry("Charge recorded")],
      };
      state.charges.push(charge);
      saveState(state);
      return {
        charge: mockChargePayload(state, charge),
        lot,
        next_run_url: "/runs/new?return_to=/floor-ops",
      };
    },
    async transitionCharge(chargeId, payload) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/charges/${encodeURIComponent(chargeId)}/transition`, {
          method: "POST",
          body: JSON.stringify(payload),
        }));
      }
      ensureMockSession();
      const state = loadState();
      const charge = state.charges.find((row) => row.id === chargeId);
      if (!charge) throw Object.assign(new Error("Charge not found"), { status: 404 });
      charge.status = payload.target_state;
      charge.state_label = payload.target_state === "completed" ? "Completed today" : payload.target_state === "cancelled" ? "Cancelled today" : payload.target_state === "running" ? "Running" : "In reactor";
      charge.history = [historyEntry(`State -> ${charge.state_label}`, payload.target_state), ...(charge.history || [])];
      saveState(state);
      return { charge: mockChargePayload(state, charge) };
    },
  };
}
