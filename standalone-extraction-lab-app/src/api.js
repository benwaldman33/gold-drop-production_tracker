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
const MOCK_TIMING_TARGETS = {
  primary_soak_minutes: 30,
  mixer_minutes: 5,
  flush_minutes: 10,
  final_purge_minutes: null,
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
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = isFormData
    ? { ...(options.headers || {}) }
    : {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
  return fetchImpl(`${baseUrl}${path}`, {
    credentials: "include",
    headers,
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

function activeMinutesSince(startValue) {
  if (!startValue) return null;
  const start = new Date(startValue);
  const delta = Date.now() - start.getTime();
  if (!Number.isFinite(delta) || delta < 0) return null;
  return Math.round(delta / 60000);
}

function timingControl(label, targetMinutes, startValue, endValue) {
  const actualMinutes = minutesBetween(startValue, endValue);
  const activeMinutes = startValue && !endValue ? activeMinutesSince(startValue) : null;
  let status = "not_started";
  if (startValue && !endValue) {
    status = targetMinutes == null ? "active" : (activeMinutes || 0) >= targetMinutes ? "active_target_reached" : "active_on_track";
  } else if (startValue && endValue) {
    status = targetMinutes == null ? "recorded" : (actualMinutes || 0) >= targetMinutes ? "on_target" : "short";
  }
  let deltaMinutes = null;
  if (targetMinutes != null) {
    const baseline = endValue ? actualMinutes : activeMinutes;
    if (baseline != null) deltaMinutes = baseline - targetMinutes;
  }
  return {
    label,
    target_minutes: targetMinutes,
    actual_minutes: actualMinutes,
    active_minutes: activeMinutes,
    status,
    delta_minutes: deltaMinutes,
  };
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
  const stageKey = run.booth_stage_key || "ready_to_confirm_vacuum";
  const config = {
    ready_to_confirm_vacuum: {
      stage_label: "Confirm vacuum down",
      description: "Confirm the reactor was vacuumed down before solvent charging begins.",
      actions: [{ action_id: "confirm_vacuum_down", label: "Confirm Vacuum Down" }],
    },
    ready_to_record_solvent_charge: {
      stage_label: "Record solvent charge",
      description: "Enter the primary solvent charge and record it before starting the soak.",
      actions: [{ action_id: "record_solvent_charge", label: "Record Solvent Charge" }],
    },
    ready_to_start_primary_soak: {
      stage_label: "Start primary soak",
      description: "The primary solvent charge is recorded. Start the primary soak to begin booth execution timing.",
      actions: [{ action_id: "start_primary_soak", label: "Start Primary Soak" }],
    },
    ready_to_start_mixer: {
      stage_label: "Ready to start mixer",
      description: "Primary soak is active. Start the mixer when agitation begins.",
      actions: [{ action_id: "start_mixer", label: "Start Mixer" }],
    },
    mixing: {
      stage_label: "Mixer running",
      description: "Mixer timing is active during primary extraction. Stop it when agitation is done.",
      actions: [{ action_id: "stop_mixer", label: "Stop Mixer" }],
    },
    ready_to_confirm_filter_clear: {
      stage_label: "Confirm filter clear",
      description: "Mixer timing is complete. Confirm the basket filter is cleared before pressurization.",
      actions: [{ action_id: "confirm_filter_clear", label: "Confirm Filter Clear" }],
    },
    ready_to_start_pressurization: {
      stage_label: "Start pressurization",
      description: "Begin nitrogen pressurization after the filter-clear checkpoint is complete.",
      actions: [{ action_id: "start_pressurization", label: "Start Pressurization" }],
    },
    ready_to_begin_recovery: {
      stage_label: "Begin recovery",
      description: "Pressurization has started. Begin flow to filtration and recovery.",
      actions: [{ action_id: "begin_recovery", label: "Begin Recovery" }],
    },
    ready_to_begin_flush_cycle: {
      stage_label: "Begin flush cycle",
      description: "Primary extraction checkpoints are complete. Move into the flush cycle.",
      actions: [{ action_id: "begin_flush_cycle", label: "Begin Flush Cycle" }],
    },
    ready_to_verify_flush_temps: {
      stage_label: "Verify flush temperatures",
      description: "Record the solvent chiller and plate temperatures before flush solvent is charged.",
      actions: [{ action_id: "verify_flush_temps", label: "Verify Flush Temps" }],
    },
    ready_to_record_flush_solvent_charge: {
      stage_label: "Record flush solvent charge",
      description: "Record the flush solvent charge after temperature verification is complete.",
      actions: [{ action_id: "record_flush_solvent_charge", label: "Record Flush Solvent Charge" }],
    },
    ready_to_flush: {
      stage_label: "Start flush soak",
      description: "The flush solvent charge is recorded. Start the flush timer when the flush soak begins.",
      actions: [{ action_id: "start_flush", label: "Start Flush" }],
    },
    ready_to_confirm_flow_resumed: {
      stage_label: "Confirm flow resumed",
      description: "Record whether flow resumed after flush recovery adjustments.",
      actions: [{ action_id: "confirm_flow_resumed", label: "Confirm Flow Resumed" }],
    },
    flow_adjustment_required: {
      stage_label: "Flow adjustment required",
      description: "Flow has not resumed yet. Keep adjusting recovery, then return here to re-check the flow decision.",
      actions: [{ action_id: "resume_flow_check", label: "Re-check Flow" }],
    },
    ready_to_start_final_purge: {
      stage_label: "Start final purge",
      description: "Flow resumed is confirmed. Start the final purge / burp step.",
      actions: [{ action_id: "start_final_purge", label: "Start Final Purge" }],
    },
    purging: {
      stage_label: "Final purge running",
      description: "Final purge timing is active. Stop it when the purge is complete.",
      actions: [{ action_id: "stop_final_purge", label: "Stop Final Purge" }],
    },
    ready_to_confirm_clarity: {
      stage_label: "Confirm final clarity",
      description: "Record whether the system is clear enough to proceed into shutdown.",
      actions: [{ action_id: "confirm_final_clarity", label: "Confirm Final Clarity" }],
    },
    clarity_adjustment_required: {
      stage_label: "More purge / clarity work required",
      description: "The system is not clear enough yet. Resume final purge or additional adjustment work, then confirm clarity again.",
      actions: [{ action_id: "resume_final_purge", label: "Resume Final Purge" }],
    },
    ready_to_complete_shutdown: {
      stage_label: "Complete shutdown checklist",
      description: "Finish the shutdown checklist before closing the booth process.",
      actions: [{ action_id: "complete_shutdown", label: "Complete Shutdown" }],
    },
    ready_to_complete: {
      stage_label: "Ready to complete run",
      description: "Shutdown is complete. Mark the extraction run complete to hand it off downstream.",
      actions: [{ action_id: "mark_complete", label: "Mark Run Complete" }],
    },
  }[stageKey];
  if (config) {
    return {
      stage_key: stageKey,
      stage_label: config.stage_label,
      description: config.description,
      actions: config.actions,
      completed_at: "",
    };
  }
  return {
    stage_key: "ready_to_confirm_vacuum",
    stage_label: "Confirm vacuum down",
    description: "Confirm the reactor was vacuumed down before solvent charging begins.",
    actions: [{ action_id: "confirm_vacuum_down", label: "Confirm Vacuum Down" }],
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
  if (action === "confirm_vacuum_down") {
    run.booth_stage_key = "ready_to_record_solvent_charge";
    run.booth_history = [{ event_label: "Reactor vacuum confirmed", occurred_at: now }, ...(run.booth_history || [])];
    return;
  }
  if (action === "record_solvent_charge") {
    const solventLbs = Number(run.primary_solvent_charge_lbs || 0);
    if (!Number.isFinite(solventLbs) || solventLbs <= 0) throw new Error("Enter the primary solvent charge before continuing.");
    if (!run.primary_solvent_charged_at) run.primary_solvent_charged_at = now;
    run.booth_stage_key = "ready_to_start_primary_soak";
    run.booth_history = [{ event_label: "Primary solvent charge recorded", occurred_at: now }, ...(run.booth_history || [])];
    return;
  }
  if (action === "start_primary_soak") {
    if (!run.primary_solvent_charged_at) throw new Error("Record the primary solvent charge before starting the soak.");
    if (!run.run_fill_started_at) run.run_fill_started_at = now;
    run.booth_stage_key = "ready_to_start_mixer";
    run.booth_history = [{ event_label: "Primary soak started", occurred_at: now }, ...(run.booth_history || [])];
    return;
  }
  if (action === "start_mixer") {
    if (!run.run_fill_started_at) throw new Error("Start the primary soak before starting the mixer.");
    if (!run.mixer_started_at) run.mixer_started_at = now;
    run.booth_stage_key = "mixing";
    return;
  }
  if (action === "stop_mixer") {
    if (!run.mixer_started_at) throw new Error("Start the mixer before stopping it.");
    run.mixer_ended_at = now;
    run.booth_stage_key = "ready_to_confirm_filter_clear";
    return;
  }
  if (action === "confirm_filter_clear") {
    if (!run.mixer_ended_at) throw new Error("Stop the mixer before confirming the filter-clear step.");
    run.booth_stage_key = "ready_to_start_pressurization";
    return;
  }
  if (action === "start_pressurization") {
    run.booth_stage_key = "ready_to_begin_recovery";
    return;
  }
  if (action === "begin_recovery") {
    run.booth_stage_key = "ready_to_begin_flush_cycle";
    return;
  }
  if (action === "begin_flush_cycle") {
    run.booth_stage_key = "ready_to_verify_flush_temps";
    return;
  }
  if (action === "verify_flush_temps") {
    const chiller = Number(run.flush_solvent_chiller_temp_f ?? "");
    const plate = Number(run.flush_plate_temp_f ?? "");
    if (!Number.isFinite(chiller) || !Number.isFinite(plate)) throw new Error("Enter both flush temperatures before continuing.");
    if (chiller > -40) throw new Error("Solvent chiller temperature must be at or below -40F before continuing.");
    run.flush_temp_verified_at = now;
    run.flush_temp_threshold_passed = true;
    if (!run.flush_temp_slack_post_confirmed_at && run.flush_temp_slack_post_confirmed) run.flush_temp_slack_post_confirmed_at = now;
    run.booth_stage_key = "ready_to_record_flush_solvent_charge";
    return;
  }
  if (action === "record_flush_solvent_charge") {
    const solventLbs = Number(run.flush_solvent_charge_lbs || 0);
    if (!Number.isFinite(solventLbs) || solventLbs <= 0) throw new Error("Enter the flush solvent charge before continuing.");
    run.flush_solvent_charged_at = now;
    run.booth_stage_key = "ready_to_flush";
    return;
  }
  if (action === "start_flush") {
    if (run.booth_stage_key !== "ready_to_flush") throw new Error("Begin the flush cycle before starting the flush timer.");
    if (!run.flush_started_at) run.flush_started_at = now;
    return;
  }
  if (action === "stop_flush") {
    if (!run.flush_started_at) throw new Error("Start the flush before stopping it.");
    run.flush_ended_at = now;
    run.booth_stage_key = "ready_to_confirm_flow_resumed";
    return;
  }
  if (action === "confirm_flow_resumed") {
    if (!["yes", "no_adjusting"].includes(run.flow_resumed_decision)) {
      throw new Error("Choose whether flow resumed before continuing.");
    }
    run.flow_resumed_confirmed_at = now;
    run.booth_history = [
      { event_label: run.flow_resumed_decision === "yes" ? "Flow resumed confirmed" : "Flow still adjusting", occurred_at: now },
      ...(run.booth_history || []),
    ];
    run.booth_stage_key = run.flow_resumed_decision === "yes" ? "ready_to_start_final_purge" : "flow_adjustment_required";
    return;
  }
  if (action === "resume_flow_check") {
    if (run.flow_resumed_decision !== "no_adjusting") throw new Error("Use flow adjustment only when flow is still being adjusted.");
    run.booth_history = [{ event_label: "Flow adjustment resumed", occurred_at: now }, ...(run.booth_history || [])];
    run.booth_stage_key = "ready_to_confirm_flow_resumed";
    return;
  }
  if (action === "start_final_purge") {
    run.final_purge_started_at = now;
    run.final_purge_completed_at = "";
    run.booth_history = [{ event_label: "Final purge started", occurred_at: now }, ...(run.booth_history || [])];
    run.booth_stage_key = "purging";
    return;
  }
  if (action === "stop_final_purge") {
    if (!run.final_purge_started_at) throw new Error("Start final purge before stopping it.");
    run.final_purge_completed_at = now;
    run.booth_history = [{ event_label: "Final purge completed", occurred_at: now }, ...(run.booth_history || [])];
    run.booth_stage_key = "ready_to_confirm_clarity";
    return;
  }
  if (action === "confirm_final_clarity") {
    if (!["yes", "not_yet"].includes(run.final_clarity_decision)) {
      throw new Error("Choose whether the system is clear enough to proceed.");
    }
    run.final_clarity_confirmed_at = now;
    run.booth_history = [
      { event_label: run.final_clarity_decision === "yes" ? "Final clarity confirmed" : "Final clarity not yet acceptable", occurred_at: now },
      ...(run.booth_history || []),
    ];
    run.booth_stage_key = run.final_clarity_decision === "yes" ? "ready_to_complete_shutdown" : "clarity_adjustment_required";
    return;
  }
  if (action === "resume_final_purge") {
    if (run.final_clarity_decision !== "not_yet") throw new Error("Resume final purge only when clarity is not yet acceptable.");
    run.booth_history = [{ event_label: "Final purge resumed for additional clarity work", occurred_at: now }, ...(run.booth_history || [])];
    run.booth_stage_key = "ready_to_start_final_purge";
    return;
  }
  if (action === "complete_shutdown") {
    if (!run.shutdown_recovery_inlets_closed || !run.shutdown_filtration_pumpdown_started || !run.shutdown_nitrogen_off || !run.shutdown_dewax_inlet_closed) {
      throw new Error("Complete the shutdown checklist before continuing.");
    }
    run.final_recovery_inlets_closed_at = now;
    run.filtration_pumpdown_started_at = now;
    run.nitrogen_turned_off_at = now;
    run.dewax_inlet_closed_at = now;
    run.booth_process_completed_at = now;
    run.booth_stage_key = "ready_to_complete";
    return;
  }
  if (action === "mark_complete") {
    if (!run.flush_ended_at) throw new Error("Stop the flush before completing the run.");
    if (!run.booth_process_completed_at) throw new Error("Complete the shutdown checklist before completing the run.");
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
  const timingControls = {
    primary_soak: timingControl("Primary soak", MOCK_TIMING_TARGETS.primary_soak_minutes, run.run_fill_started_at, run.run_fill_ended_at),
    mixer: timingControl("Mixer", MOCK_TIMING_TARGETS.mixer_minutes, run.mixer_started_at, run.mixer_ended_at),
    flush: timingControl("Flush soak", MOCK_TIMING_TARGETS.flush_minutes, run.flush_started_at, run.flush_ended_at),
    final_purge: timingControl("Final purge", MOCK_TIMING_TARGETS.final_purge_minutes, run.final_purge_started_at, run.final_purge_completed_at),
  };
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
    booth: {
      status: run.run_completed_at ? "completed" : "in_progress",
      current_stage_key: run.booth_stage_key || "ready_to_confirm_vacuum",
      primary_solvent_charge_lbs: run.primary_solvent_charge_lbs ?? null,
      primary_solvent_charged_at: run.primary_solvent_charged_at || "",
      flush_solvent_chiller_temp_f: run.flush_solvent_chiller_temp_f ?? null,
      flush_plate_temp_f: run.flush_plate_temp_f ?? null,
      flush_temp_verified_at: run.flush_temp_verified_at || "",
      flush_temp_threshold_passed: run.flush_temp_threshold_passed ?? null,
      flush_temp_slack_post_confirmed_at: run.flush_temp_slack_post_confirmed_at || "",
      flush_solvent_charge_lbs: run.flush_solvent_charge_lbs ?? null,
      flush_solvent_charged_at: run.flush_solvent_charged_at || "",
      flow_resumed_decision: run.flow_resumed_decision || "",
      flow_resumed_confirmed_at: run.flow_resumed_confirmed_at || "",
      final_purge_started_at: run.final_purge_started_at || "",
      final_purge_completed_at: run.final_purge_completed_at || "",
      final_purge_duration_minutes: minutesBetween(run.final_purge_started_at, run.final_purge_completed_at),
      final_clarity_decision: run.final_clarity_decision || "",
      final_clarity_confirmed_at: run.final_clarity_confirmed_at || "",
      final_recovery_inlets_closed_at: run.final_recovery_inlets_closed_at || "",
      filtration_pumpdown_started_at: run.filtration_pumpdown_started_at || "",
      nitrogen_turned_off_at: run.nitrogen_turned_off_at || "",
      dewax_inlet_closed_at: run.dewax_inlet_closed_at || "",
      booth_process_completed_at: run.booth_process_completed_at || "",
      timing_targets: { ...MOCK_TIMING_TARGETS },
      evidence_counts: {
        solvent_chiller_temp_photo: (run.booth_evidence || []).filter((row) => row.evidence_type === "solvent_chiller_temp_photo").length,
        plate_temp_photo: (run.booth_evidence || []).filter((row) => row.evidence_type === "plate_temp_photo").length,
      },
      evidence: (run.booth_evidence || []).slice(),
      history: run.booth_history || [],
    },
    timing_controls: timingControls,
    primary_solvent_charge_lbs: run.primary_solvent_charge_lbs ?? null,
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
    booth_stage_key: "ready_to_confirm_vacuum",
    primary_solvent_charge_lbs: null,
    primary_solvent_charged_at: "",
    flush_solvent_chiller_temp_f: null,
    flush_plate_temp_f: null,
    flush_temp_verified_at: "",
    flush_temp_threshold_passed: null,
    flush_temp_slack_post_confirmed_at: "",
    flush_solvent_charge_lbs: null,
    flush_solvent_charged_at: "",
    flow_resumed_decision: "",
    flow_resumed_confirmed_at: "",
    final_purge_started_at: "",
    final_purge_completed_at: "",
    final_clarity_decision: "",
    final_clarity_confirmed_at: "",
    final_recovery_inlets_closed_at: "",
    filtration_pumpdown_started_at: "",
    nitrogen_turned_off_at: "",
    dewax_inlet_closed_at: "",
    booth_process_completed_at: "",
    booth_evidence: [],
    booth_history: [],
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
    booth_stage_key: "ready_to_confirm_vacuum",
    primary_solvent_charge_lbs: null,
    primary_solvent_charged_at: "",
    flush_solvent_chiller_temp_f: null,
    flush_plate_temp_f: null,
    flush_temp_verified_at: "",
    flush_temp_threshold_passed: null,
    flush_temp_slack_post_confirmed_at: "",
    flush_solvent_charge_lbs: null,
    flush_solvent_charged_at: "",
    flow_resumed_decision: "",
    flow_resumed_confirmed_at: "",
    final_purge_started_at: "",
    final_purge_completed_at: "",
    final_clarity_decision: "",
    final_clarity_confirmed_at: "",
    final_recovery_inlets_closed_at: "",
    filtration_pumpdown_started_at: "",
    nitrogen_turned_off_at: "",
    dewax_inlet_closed_at: "",
    booth_process_completed_at: "",
    booth_evidence: [],
    booth_history: [],
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
    async getChargeRunEvidence(chargeId) {
      if (mode === "live") {
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/charges/${encodeURIComponent(chargeId)}/run/evidence`));
      }
      ensureMockSession();
      const state = loadState();
      const { run } = ensureMockRunForCharge(state, chargeId);
      return {
        evidence: (run.booth_evidence || []).slice().sort((left, right) => String(right.captured_at || "").localeCompare(String(left.captured_at || ""))),
      };
    },
    async uploadChargeRunEvidence(chargeId, evidenceType, files) {
      if (mode === "live") {
        const form = new FormData();
        form.append("evidence_type", evidenceType);
        for (const file of files || []) {
          form.append("photos", file);
        }
        return unwrapData(await liveRequest(apiBaseUrl, fetchImpl, `/api/mobile/v1/extraction/charges/${encodeURIComponent(chargeId)}/run/evidence`, {
          method: "POST",
          body: form,
        }));
      }
      ensureMockSession();
      const state = loadState();
      const { run } = ensureMockRunForCharge(state, chargeId);
      if (!["solvent_chiller_temp_photo", "plate_temp_photo", "other"].includes(String(evidenceType || ""))) {
        throw Object.assign(new Error("Evidence type must be solvent_chiller_temp_photo, plate_temp_photo, or other."), { status: 400 });
      }
      const uploadFiles = Array.from(files || []).filter((file) => file);
      if (!uploadFiles.length) {
        throw Object.assign(new Error("At least one photo file is required."), { status: 400 });
      }
      const timestamp = nowLocalInputValue();
      const created = uploadFiles.map((file, index) => ({
        id: `evidence-${Date.now()}-${index}`,
        evidence_type: evidenceType,
        file_path: `mock/${run.id}/${evidenceType}/${file.name || `upload-${index + 1}.jpg`}`,
        url: "",
        captured_at: timestamp,
      }));
      run.booth_evidence = [...created, ...(run.booth_evidence || [])];
      saveState(state);
      return {
        count: created.length,
        evidence_type: evidenceType,
        files: created.map((row) => ({ file_path: row.file_path, url: row.url })),
      };
    },
  };
}
