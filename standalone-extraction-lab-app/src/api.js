import { cloneSeedState } from "./mock-data.js";
import { readJson, removeValue, writeJson } from "./storage.js";

const STATE_KEY = "gold-drop-extraction-lab-state-v1";
const SESSION_KEY = "gold-drop-extraction-lab-session-v1";
const MOCK_RUN_DEFAULTS = {
  biomass_blend_milled_pct: 100,
  biomass_blend_unmilled_pct: 0,
  flush_count: 0,
  flush_total_weight_lbs: null,
  fill_count: 1,
  fill_total_weight_lbs: null,
  stringer_basket_count: 0,
  crc_blend: "",
};

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

function minutesBetween(startValue, endValue) {
  if (!startValue || !endValue) return null;
  const start = new Date(startValue);
  const end = new Date(endValue);
  const delta = end.getTime() - start.getTime();
  if (!Number.isFinite(delta) || delta < 0) return null;
  return Math.round(delta / 60000);
}

function nowLocalInputValue() {
  const dt = new Date();
  const offset = dt.getTimezoneOffset();
  return new Date(dt.getTime() - offset * 60_000).toISOString().slice(0, 16);
}

function progressionForRun(run) {
  if (run.run_completed_at) {
    return {
      stage_key: "completed",
      stage_label: "Completed",
      description: "This run has been marked complete in the standalone execution workflow.",
      actions: [],
      completed_at: run.run_completed_at,
    };
  }
  if (run.flush_started_at && !run.flush_ended_at) {
    return {
      stage_key: "flushing",
      stage_label: "Flush running",
      description: "Flush timing is active. Stop it when the flush is done.",
      actions: [{ action_id: "stop_flush", label: "Stop Flush" }],
      completed_at: "",
    };
  }
  if (run.flush_ended_at) {
    return {
      stage_key: "ready_to_complete",
      stage_label: "Ready to complete",
      description: "Core extraction steps are timed. Complete the run to close out the operator workflow.",
      actions: [{ action_id: "mark_complete", label: "Mark Run Complete" }],
      completed_at: "",
    };
  }
  if (run.mixer_started_at && !run.mixer_ended_at) {
    return {
      stage_key: "mixing",
      stage_label: "Mixer running",
      description: "Mixer timing is active. Stop the mixer when that step is done.",
      actions: [{ action_id: "stop_mixer", label: "Stop Mixer" }],
      completed_at: "",
    };
  }
  if (run.mixer_ended_at) {
    return {
      stage_key: "ready_to_flush",
      stage_label: "Ready to flush",
      description: "Mixer timing is complete. Start the flush when the reactor is ready.",
      actions: [{ action_id: "start_flush", label: "Start Flush" }],
      completed_at: "",
    };
  }
  if (run.run_fill_started_at) {
    return {
      stage_key: "ready_to_mix",
      stage_label: "Ready to mix",
      description: "The run has started. Start the mixer when material is loaded.",
      actions: [{ action_id: "start_mixer", label: "Start Mixer" }],
      completed_at: "",
    };
  }
  return {
    stage_key: "ready_to_start",
    stage_label: "Ready to start",
    description: "Record the start of the run before moving into mixer work.",
    actions: [{ action_id: "start_run", label: "Start Run" }],
    completed_at: "",
  };
}

function postExtractionForRun(run) {
  const pathwayMap = {
    pot_pour_100: "100 lb pot pour",
    minor_run_200: "200 lb minor run",
  };
  const pathwayLabel = pathwayMap[run.post_extraction_pathway] || "";
  if (!run.run_completed_at) {
    return {
      stage_key: "blocked_until_run_complete",
      stage_label: "Complete extraction first",
      description: "Post-extraction handoff begins only after the extraction run is marked complete.",
      actions: [],
      pathway_label: pathwayLabel,
    };
  }
  if (!run.post_extraction_started_at) {
    return {
      stage_key: "ready_to_start",
      stage_label: "Ready to start post-extraction",
      description: "Select the downstream pathway and start the post-extraction session.",
      actions: [{ action_id: "start_post_extraction", label: "Start Post-Extraction" }],
      pathway_label: pathwayLabel,
    };
  }
  if (!run.post_extraction_initial_outputs_recorded_at) {
    return {
      stage_key: "ready_to_confirm_initial_outputs",
      stage_label: "Ready to confirm initial outputs",
      description: "Record the initial wet THCA and wet HTE outputs to hand this run into downstream processing.",
      actions: [{ action_id: "confirm_initial_outputs", label: "Confirm Initial Outputs" }],
      pathway_label: pathwayLabel,
    };
  }
  return {
    stage_key: "session_started",
    stage_label: "Post-extraction session started",
    description: "This run is now handed off into the downstream post-extraction workflow foundation.",
    actions: [],
    pathway_label: pathwayLabel,
  };
}

function downstreamForRun(run) {
  const labels = {
    thca_destination: {
      sell_thca: "Sell THCA",
      make_ld: "Make LD",
      formulate_badders_sugars: "Formulate in badders / sugars",
    },
    hte_clean_decision: {
      clean: "Clean",
      dirty: "Dirty",
    },
    hte_filter_outcome: {
      standard: "Standard refinement path",
      needs_prescott: "Oil darker / thick / harder to filter — use Prescott",
    },
    hte_potency_disposition: {
      hold_hp_base_oil: "Hold for HP base oil",
      hold_distillate: "Hold to be made into distillate",
    },
    hte_queue_destination: {
      golddrop_queue: "GoldDrop production queue",
      liquid_loud_hold: "Liquid Loud hold",
      terp_strip_cage: "Terp stripping / CDT cage",
    },
  };
  return {
    thca_destination_label: labels.thca_destination[run.thca_destination] || "",
    hte_clean_decision_label: labels.hte_clean_decision[run.hte_clean_decision] || "",
    hte_filter_outcome_label: labels.hte_filter_outcome[run.hte_filter_outcome] || "",
    hte_potency_disposition_label: labels.hte_potency_disposition[run.hte_potency_disposition] || "",
    hte_queue_destination_label: labels.hte_queue_destination[run.hte_queue_destination] || "",
    pot_pour_offgas_duration_minutes: minutesBetween(run.pot_pour_offgas_started_at, run.pot_pour_offgas_completed_at),
    thca_oven_duration_minutes: minutesBetween(run.thca_oven_started_at, run.thca_oven_completed_at),
    hte_offgas_duration_minutes: minutesBetween(run.hte_offgas_started_at, run.hte_offgas_completed_at),
  };
}

function applyMockProgressionAction(run, action) {
  const now = nowLocalInputValue();
  if (action === "start_run") {
    if (!run.run_fill_started_at) run.run_fill_started_at = now;
    return;
  }
  if (action === "start_mixer") {
    if (!run.run_fill_started_at) throw new Error("Start the run before starting the mixer.");
    if (!run.mixer_started_at) run.mixer_started_at = now;
    return;
  }
  if (action === "stop_mixer") {
    if (!run.mixer_started_at) throw new Error("Start the mixer before stopping it.");
    run.mixer_ended_at = now;
    return;
  }
  if (action === "start_flush") {
    if (!run.mixer_ended_at) throw new Error("Stop the mixer before starting the flush.");
    if (!run.flush_started_at) run.flush_started_at = now;
    return;
  }
  if (action === "stop_flush") {
    if (!run.flush_started_at) throw new Error("Start the flush before stopping it.");
    run.flush_ended_at = now;
    return;
  }
  if (action === "mark_complete") {
    if (!run.flush_ended_at) throw new Error("Stop the flush before completing the run.");
    run.run_completed_at = now;
  }
}

function applyMockPostExtractionAction(run, action) {
  const now = nowLocalInputValue();
  if (!run.run_completed_at) throw new Error("Complete the extraction run before starting post-extraction.");
  if (action === "start_post_extraction") {
    if (!run.post_extraction_pathway) throw new Error("Select the post-extraction pathway before starting the session.");
    if (!run.post_extraction_started_at) run.post_extraction_started_at = now;
    return;
  }
  if (action === "confirm_initial_outputs") {
    if (!run.post_extraction_started_at) throw new Error("Start the post-extraction session before confirming outputs.");
    if (!run.post_extraction_pathway) throw new Error("Select the post-extraction pathway before confirming outputs.");
    if (run.wet_thca_g == null || run.wet_hte_g == null) throw new Error("Enter both wet THCA and wet HTE before confirming the initial outputs.");
    run.post_extraction_initial_outputs_recorded_at = now;
  }
}

function buildMockRunPayload(state, charge, run) {
  const lot = state.lots.find((row) => row.id === charge.purchase_lot_id) || state.lots.find((row) => row.tracking_id === charge.tracking_id) || state.lots[0];
  return {
    id: run.id,
    run_date: run.run_date,
    reactor_number: run.reactor_number,
    bio_in_reactor_lbs: run.bio_in_reactor_lbs,
    run_type: run.run_type || "standard",
    run_fill_started_at: run.run_fill_started_at || "",
    run_fill_ended_at: run.run_fill_ended_at || "",
    run_fill_duration_minutes: minutesBetween(run.run_fill_started_at, run.run_fill_ended_at),
    biomass_blend_milled_pct: run.biomass_blend_milled_pct,
    biomass_blend_unmilled_pct: run.biomass_blend_unmilled_pct,
    flush_count: run.flush_count,
    flush_total_weight_lbs: run.flush_total_weight_lbs,
    fill_count: run.fill_count,
    fill_total_weight_lbs: run.fill_total_weight_lbs,
    stringer_basket_count: run.stringer_basket_count,
    crc_blend: run.crc_blend || "",
    mixer_started_at: run.mixer_started_at || "",
    mixer_ended_at: run.mixer_ended_at || "",
    mixer_duration_minutes: minutesBetween(run.mixer_started_at, run.mixer_ended_at),
    flush_started_at: run.flush_started_at || "",
    flush_ended_at: run.flush_ended_at || "",
    flush_duration_minutes: minutesBetween(run.flush_started_at, run.flush_ended_at),
    run_completed_at: run.run_completed_at || "",
    progression: progressionForRun(run),
    wet_hte_g: run.wet_hte_g ?? null,
    wet_thca_g: run.wet_thca_g ?? null,
    post_extraction_pathway: run.post_extraction_pathway || "",
    post_extraction_pathway_options: [
      { value: "", label: "Not set" },
      { value: "pot_pour_100", label: "100 lb pot pour" },
      { value: "minor_run_200", label: "200 lb minor run" },
    ],
    post_extraction_started_at: run.post_extraction_started_at || "",
    post_extraction_initial_outputs_recorded_at: run.post_extraction_initial_outputs_recorded_at || "",
    post_extraction: postExtractionForRun(run),
    pot_pour_offgas_started_at: run.pot_pour_offgas_started_at || "",
    pot_pour_offgas_completed_at: run.pot_pour_offgas_completed_at || "",
    pot_pour_daily_stir_count: run.pot_pour_daily_stir_count ?? null,
    pot_pour_centrifuged_at: run.pot_pour_centrifuged_at || "",
    thca_oven_started_at: run.thca_oven_started_at || "",
    thca_oven_completed_at: run.thca_oven_completed_at || "",
    thca_milled_at: run.thca_milled_at || "",
    thca_destination: run.thca_destination || "",
    thca_destination_options: [
      { value: "", label: "Not set" },
      { value: "sell_thca", label: "Sell THCA" },
      { value: "make_ld", label: "Make LD" },
      { value: "formulate_badders_sugars", label: "Formulate in badders / sugars" },
    ],
    hte_offgas_started_at: run.hte_offgas_started_at || "",
    hte_offgas_completed_at: run.hte_offgas_completed_at || "",
    hte_clean_decision: run.hte_clean_decision || "",
    hte_clean_decision_options: [
      { value: "", label: "Not set" },
      { value: "clean", label: "Clean" },
      { value: "dirty", label: "Dirty" },
    ],
    hte_filter_outcome: run.hte_filter_outcome || "",
    hte_filter_outcome_options: [
      { value: "", label: "Not set" },
      { value: "standard", label: "Standard refinement path" },
      { value: "needs_prescott", label: "Oil darker / thick / harder to filter — use Prescott" },
    ],
    hte_prescott_processed_at: run.hte_prescott_processed_at || "",
    hte_potency_disposition: run.hte_potency_disposition || "",
    hte_potency_disposition_options: [
      { value: "", label: "Not set" },
      { value: "hold_hp_base_oil", label: "Hold for HP base oil" },
      { value: "hold_distillate", label: "Hold to be made into distillate" },
    ],
    hte_queue_destination: run.hte_queue_destination || "",
    hte_queue_destination_options: [
      { value: "", label: "Not set" },
      { value: "golddrop_queue", label: "GoldDrop production queue" },
      { value: "liquid_loud_hold", label: "Liquid Loud hold" },
      { value: "terp_strip_cage", label: "Terp stripping / CDT cage" },
    ],
    downstream: downstreamForRun(run),
    notes: run.notes || "",
    inherited: {
      tracking_id: lot?.tracking_id || "",
      supplier_name: lot?.supplier_name || "Unknown",
      strain_name: lot?.strain_name || "Unknown",
      source_summary: `${lot?.supplier_name || "Unknown"} - ${lot?.strain_name || "Unknown"}`,
      charge_weight_lbs: Number(charge.charged_weight_lbs || 0),
      charged_at_label: charge.charged_at_label || "",
    },
    open_main_app_url: run.id ? `/runs/${run.id}/edit?return_to=/floor-ops` : "/runs/new?return_to=/floor-ops",
  };
}

function buildMockDraftRun(charge) {
  return {
    id: null,
    run_date: String(charge.charged_at || "").slice(0, 10) || new Date().toISOString().slice(0, 10),
    reactor_number: Number(charge.reactor_number || 1),
    bio_in_reactor_lbs: Number(charge.charged_weight_lbs || 0),
    run_type: "standard",
    run_fill_started_at: "",
    run_fill_ended_at: "",
    biomass_blend_milled_pct: MOCK_RUN_DEFAULTS.biomass_blend_milled_pct,
    biomass_blend_unmilled_pct: MOCK_RUN_DEFAULTS.biomass_blend_unmilled_pct,
    flush_count: MOCK_RUN_DEFAULTS.flush_count,
    flush_total_weight_lbs: MOCK_RUN_DEFAULTS.flush_total_weight_lbs,
    fill_count: MOCK_RUN_DEFAULTS.fill_count,
    fill_total_weight_lbs: MOCK_RUN_DEFAULTS.fill_total_weight_lbs ?? Number(charge.charged_weight_lbs || 0),
    stringer_basket_count: MOCK_RUN_DEFAULTS.stringer_basket_count,
    crc_blend: MOCK_RUN_DEFAULTS.crc_blend,
    mixer_started_at: "",
    mixer_ended_at: "",
    flush_started_at: "",
    flush_ended_at: "",
    run_completed_at: "",
    wet_hte_g: null,
    wet_thca_g: null,
    post_extraction_pathway: "",
    post_extraction_started_at: "",
    post_extraction_initial_outputs_recorded_at: "",
    pot_pour_offgas_started_at: "",
    pot_pour_offgas_completed_at: "",
    pot_pour_daily_stir_count: null,
    pot_pour_centrifuged_at: "",
    thca_oven_started_at: "",
    thca_oven_completed_at: "",
    thca_milled_at: "",
    thca_destination: "",
    hte_offgas_started_at: "",
    hte_offgas_completed_at: "",
    hte_clean_decision: "",
    hte_filter_outcome: "",
    hte_prescott_processed_at: "",
    hte_potency_disposition: "",
    hte_queue_destination: "",
    notes: "",
  };
}

function ensureMockRunForCharge(state, chargeId) {
  const charge = state.charges.find((row) => row.id === chargeId);
  if (!charge) throw Object.assign(new Error("Charge not found"), { status: 404 });
  if (charge.run_id) {
    const existing = state.runs.find((row) => row.id === charge.run_id);
    if (existing) return { charge, run: existing };
  }
  const run = {
    id: `run-${Date.now()}`,
    run_date: String(charge.charged_at || "").slice(0, 10) || new Date().toISOString().slice(0, 10),
    reactor_number: Number(charge.reactor_number || 1),
    bio_in_reactor_lbs: Number(charge.charged_weight_lbs || 0),
    run_type: "standard",
    run_fill_started_at: "",
    run_fill_ended_at: "",
    biomass_blend_milled_pct: MOCK_RUN_DEFAULTS.biomass_blend_milled_pct,
    biomass_blend_unmilled_pct: MOCK_RUN_DEFAULTS.biomass_blend_unmilled_pct,
    flush_count: MOCK_RUN_DEFAULTS.flush_count,
    flush_total_weight_lbs: MOCK_RUN_DEFAULTS.flush_total_weight_lbs,
    fill_count: MOCK_RUN_DEFAULTS.fill_count,
    fill_total_weight_lbs: MOCK_RUN_DEFAULTS.fill_total_weight_lbs ?? Number(charge.charged_weight_lbs || 0),
    stringer_basket_count: MOCK_RUN_DEFAULTS.stringer_basket_count,
    crc_blend: MOCK_RUN_DEFAULTS.crc_blend,
    mixer_started_at: "",
    mixer_ended_at: "",
    flush_started_at: "",
    flush_ended_at: "",
    run_completed_at: "",
    wet_hte_g: null,
    wet_thca_g: null,
    post_extraction_pathway: "",
    post_extraction_started_at: "",
    post_extraction_initial_outputs_recorded_at: "",
    pot_pour_offgas_started_at: "",
    pot_pour_offgas_completed_at: "",
    pot_pour_daily_stir_count: null,
    pot_pour_centrifuged_at: "",
    thca_oven_started_at: "",
    thca_oven_completed_at: "",
    thca_milled_at: "",
    thca_destination: "",
    hte_offgas_started_at: "",
    hte_offgas_completed_at: "",
    hte_clean_decision: "",
    hte_filter_outcome: "",
    hte_prescott_processed_at: "",
    hte_potency_disposition: "",
    hte_queue_destination: "",
    notes: "",
  };
  state.runs.push(run);
  charge.run_id = run.id;
  if (charge.status === "pending") {
    charge.status = "applied";
    charge.state_label = "Run linked";
    charge.history = [historyEntry("State -> Run linked", "applied"), ...(charge.history || [])];
  }
  saveState(state);
  return { charge, run };
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
    async getChargeRun(chargeId) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/charges/${encodeURIComponent(chargeId)}/run`));
      }
      ensureMockSession();
      const state = loadState();
      const charge = state.charges.find((row) => row.id === chargeId);
      if (!charge) throw Object.assign(new Error("Charge not found"), { status: 404 });
      const run = charge.run_id ? state.runs.find((row) => row.id === charge.run_id) : null;
      return {
        charge: mockChargePayload(state, charge),
        lot: state.lots.find((row) => row.id === charge.purchase_lot_id || row.tracking_id === charge.tracking_id) || null,
        run: buildMockRunPayload(state, charge, run || buildMockDraftRun(charge)),
      };
    },
    async saveChargeRun(chargeId, payload) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/charges/${encodeURIComponent(chargeId)}/run`, {
          method: "POST",
          body: JSON.stringify(payload),
        }));
      }
      ensureMockSession();
      const state = loadState();
      const { charge, run } = ensureMockRunForCharge(state, chargeId);
      Object.assign(run, {
        ...run,
        ...payload,
      });
      if (payload.progression_action) {
        applyMockProgressionAction(run, payload.progression_action);
      }
      if (payload.post_extraction_action) {
        applyMockPostExtractionAction(run, payload.post_extraction_action);
      }
      saveState(state);
      return {
        charge: mockChargePayload(state, charge),
        lot: state.lots.find((row) => row.id === charge.purchase_lot_id || row.tracking_id === charge.tracking_id) || null,
        run: buildMockRunPayload(state, charge, run),
      };
    },
  };
}
