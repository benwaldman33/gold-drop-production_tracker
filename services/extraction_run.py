from __future__ import annotations

from datetime import datetime, timezone

from services.extraction_charge import (
    app_display_zoneinfo,
    build_charge_prefill_payload,
    charge_history_entries,
    display_charge_datetime_local,
    update_charge_state,
)
from services.lot_allocation import apply_run_allocations
from services.supervisor_notifications import create_notification, resolve_matching_notifications

EXTRACTION_RUN_DEFAULTS = {
    "extraction_default_biomass_blend_milled_pct": ("100", "Default milled biomass percentage for extraction run drafts"),
    "extraction_default_fill_count": ("1", "Default fill count for extraction run drafts"),
    "extraction_default_fill_total_weight_lbs": ("", "Default total fill weight (lbs) for extraction run drafts"),
    "extraction_default_flush_count": ("0", "Default flush count for extraction run drafts"),
    "extraction_default_flush_total_weight_lbs": ("", "Default total flush weight (lbs) for extraction run drafts"),
    "extraction_default_stringer_basket_count": ("0", "Default stringer basket count for extraction run drafts"),
    "extraction_default_crc_blend": ("", "Default CRC blend note for extraction run drafts"),
    "extraction_target_primary_soak_minutes": ("30", "Target minutes for the primary soak window"),
    "extraction_target_mixer_minutes": ("5", "Target minutes for the primary mixer window"),
    "extraction_target_flush_minutes": ("10", "Target minutes for the flush soak window"),
    "extraction_target_final_purge_minutes": ("", "Optional target minutes for the final purge window"),
}

TIMING_POLICY_OPTIONS = [
    ("informational", "Informational"),
    ("warning", "Warning only"),
    ("supervisor_override", "Require supervisor override"),
    ("hard_stop", "Hard stop"),
]

TIMING_POLICY_DEFAULTS = {
    "extraction_policy_primary_soak": ("warning", "Policy for primary soak timing deviations"),
    "extraction_policy_mixer": ("warning", "Policy for mixer timing deviations"),
    "extraction_policy_flush": ("warning", "Policy for flush soak timing deviations"),
    "extraction_policy_final_purge": ("informational", "Policy for final purge timing deviations"),
}

RUN_PROGRESSION = {
    "ready_to_confirm_vacuum": {
        "label": "Confirm vacuum down",
        "description": "Confirm the reactor was vacuumed down before solvent charging begins.",
        "actions": [{"action_id": "confirm_vacuum_down", "label": "Confirm Vacuum Down"}],
    },
    "ready_to_record_solvent_charge": {
        "label": "Record solvent charge",
        "description": "Enter the primary solvent charge and record it before starting the soak.",
        "actions": [{"action_id": "record_solvent_charge", "label": "Record Solvent Charge"}],
    },
    "ready_to_start_primary_soak": {
        "label": "Start primary soak",
        "description": "The primary solvent charge is recorded. Start the primary soak to begin booth execution timing.",
        "actions": [{"action_id": "start_primary_soak", "label": "Start Primary Soak"}],
    },
    "ready_to_start_mixer": {
        "label": "Ready to start mixer",
        "description": "Primary soak is active. Start the mixer when agitation begins.",
        "actions": [{"action_id": "start_mixer", "label": "Start Mixer"}],
    },
    "mixing": {
        "label": "Mixer running",
        "description": "Mixer timing is active during primary extraction. Stop it when agitation is done.",
        "actions": [{"action_id": "stop_mixer", "label": "Stop Mixer"}],
    },
    "ready_to_confirm_filter_clear": {
        "label": "Confirm filter clear",
        "description": "Mixer timing is complete. Confirm the basket filter is cleared before pressurization.",
        "actions": [{"action_id": "confirm_filter_clear", "label": "Confirm Filter Clear"}],
    },
    "ready_to_start_pressurization": {
        "label": "Start pressurization",
        "description": "Begin nitrogen pressurization after the filter-clear checkpoint is complete.",
        "actions": [{"action_id": "start_pressurization", "label": "Start Pressurization"}],
    },
    "ready_to_begin_recovery": {
        "label": "Begin recovery",
        "description": "Pressurization has started. Begin flow to filtration and recovery.",
        "actions": [{"action_id": "begin_recovery", "label": "Begin Recovery"}],
    },
    "ready_to_begin_flush_cycle": {
        "label": "Begin flush cycle",
        "description": "Primary extraction checkpoints are complete. Move into the flush cycle.",
        "actions": [{"action_id": "begin_flush_cycle", "label": "Begin Flush Cycle"}],
    },
    "ready_to_verify_flush_temps": {
        "label": "Verify flush temperatures",
        "description": "Record the solvent chiller and plate temperatures before flush solvent is charged.",
        "actions": [{"action_id": "verify_flush_temps", "label": "Verify Flush Temps"}],
    },
    "ready_to_record_flush_solvent_charge": {
        "label": "Record flush solvent charge",
        "description": "Record the flush solvent charge after temperature verification is complete.",
        "actions": [{"action_id": "record_flush_solvent_charge", "label": "Record Flush Solvent Charge"}],
    },
    "ready_to_flush": {
        "label": "Start flush soak",
        "description": "The flush solvent charge is recorded. Start the flush timer when the flush soak begins.",
        "actions": [{"action_id": "start_flush", "label": "Start Flush"}],
    },
    "flushing": {
        "label": "Flush running",
        "description": "Flush timing is active. Stop it when the flush is done.",
        "actions": [{"action_id": "stop_flush", "label": "Stop Flush"}],
    },
    "ready_to_confirm_flow_resumed": {
        "label": "Confirm flow resumed",
        "description": "Record whether flow resumed after flush recovery adjustments.",
        "actions": [{"action_id": "confirm_flow_resumed", "label": "Confirm Flow Resumed"}],
    },
    "flow_adjustment_required": {
        "label": "Flow adjustment required",
        "description": "Flow has not resumed yet. Keep adjusting recovery, then return here to re-check the flow decision.",
        "actions": [{"action_id": "resume_flow_check", "label": "Re-check Flow"}],
    },
    "ready_to_start_final_purge": {
        "label": "Start final purge",
        "description": "Flow resumed is confirmed. Start the final purge / burp step.",
        "actions": [{"action_id": "start_final_purge", "label": "Start Final Purge"}],
    },
    "purging": {
        "label": "Final purge running",
        "description": "Final purge timing is active. Stop it when the purge is complete.",
        "actions": [{"action_id": "stop_final_purge", "label": "Stop Final Purge"}],
    },
    "ready_to_confirm_clarity": {
        "label": "Confirm final clarity",
        "description": "Record whether the system is clear enough to proceed into shutdown.",
        "actions": [{"action_id": "confirm_final_clarity", "label": "Confirm Final Clarity"}],
    },
    "clarity_adjustment_required": {
        "label": "More purge / clarity work required",
        "description": "The system is not clear enough yet. Resume final purge or additional adjustment work, then confirm clarity again.",
        "actions": [{"action_id": "resume_final_purge", "label": "Resume Final Purge"}],
    },
    "ready_to_complete_shutdown": {
        "label": "Complete shutdown checklist",
        "description": "Finish the shutdown checklist before closing the booth process.",
        "actions": [{"action_id": "complete_shutdown", "label": "Complete Shutdown"}],
    },
    "ready_to_complete": {
        "label": "Ready to complete",
        "description": "Booth checkpoints and shutdown are complete. Complete the run to close out the operator workflow.",
        "actions": [{"action_id": "mark_complete", "label": "Mark Run Complete"}],
    },
    "completed": {
        "label": "Completed",
        "description": "This run has been marked complete in the standalone execution workflow.",
        "actions": [],
    },
}

RUN_STAGE_SEQUENCE = {
    "ready_to_confirm_vacuum": "ready_to_record_solvent_charge",
    "ready_to_record_solvent_charge": "ready_to_start_primary_soak",
    "ready_to_start_primary_soak": "ready_to_start_mixer",
    "ready_to_start_mixer": "mixing",
    "mixing": "ready_to_confirm_filter_clear",
    "ready_to_confirm_filter_clear": "ready_to_start_pressurization",
    "ready_to_start_pressurization": "ready_to_begin_recovery",
    "ready_to_begin_recovery": "ready_to_begin_flush_cycle",
    "ready_to_begin_flush_cycle": "ready_to_verify_flush_temps",
    "ready_to_verify_flush_temps": "ready_to_record_flush_solvent_charge",
    "ready_to_record_flush_solvent_charge": "ready_to_flush",
    "ready_to_flush": "flushing",
    "flushing": "ready_to_confirm_flow_resumed",
    "flow_adjustment_required": "ready_to_confirm_flow_resumed",
    "ready_to_confirm_flow_resumed": "ready_to_start_final_purge",
    "ready_to_start_final_purge": "purging",
    "purging": "ready_to_confirm_clarity",
    "clarity_adjustment_required": "ready_to_start_final_purge",
    "ready_to_confirm_clarity": "ready_to_complete_shutdown",
    "ready_to_complete_shutdown": "ready_to_complete",
    "ready_to_complete": "completed",
}

POST_EXTRACTION_PATHWAY_OPTIONS = [
    ("", "Not set"),
    ("pot_pour_100", "100 lb pot pour"),
    ("minor_run_200", "200 lb minor run"),
]

POST_EXTRACTION_PATHWAY_LABELS = {value: label for value, label in POST_EXTRACTION_PATHWAY_OPTIONS if value}
THCA_DESTINATION_OPTIONS = [
    ("", "Not set"),
    ("sell_thca", "Sell THCA"),
    ("make_ld", "Make LD"),
    ("formulate_badders_sugars", "Formulate in badders / sugars"),
]
THCA_DESTINATION_LABELS = {value: label for value, label in THCA_DESTINATION_OPTIONS if value}
HTE_CLEAN_DECISION_OPTIONS = [
    ("", "Not set"),
    ("clean", "Clean"),
    ("dirty", "Dirty"),
]
HTE_CLEAN_DECISION_LABELS = {value: label for value, label in HTE_CLEAN_DECISION_OPTIONS if value}
HTE_FILTER_OUTCOME_OPTIONS = [
    ("", "Not set"),
    ("standard", "Standard refinement path"),
    ("needs_prescott", "Oil darker / thick / harder to filter — use Prescott"),
]
HTE_FILTER_OUTCOME_LABELS = {value: label for value, label in HTE_FILTER_OUTCOME_OPTIONS if value}
HTE_POTENCY_DISPOSITION_OPTIONS = [
    ("", "Not set"),
    ("hold_hp_base_oil", "Hold for HP base oil"),
    ("hold_distillate", "Hold to be made into distillate"),
]
HTE_POTENCY_DISPOSITION_LABELS = {value: label for value, label in HTE_POTENCY_DISPOSITION_OPTIONS if value}
HTE_QUEUE_DESTINATION_OPTIONS = [
    ("", "Not set"),
    ("golddrop_queue", "GoldDrop production queue"),
    ("liquid_loud_hold", "Liquid Loud hold"),
    ("terp_strip_cage", "Terp stripping / CDT cage"),
]
HTE_QUEUE_DESTINATION_LABELS = {value: label for value, label in HTE_QUEUE_DESTINATION_OPTIONS if value}


def _setting_float_or_none(root, key: str) -> float | None:
    raw = (root.SystemSetting.get(key, "") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extraction_run_defaults(root) -> dict[str, float | int | str]:
    milled_pct = root.SystemSetting.get_float("extraction_default_biomass_blend_milled_pct", 100.0)
    milled_pct = max(0.0, min(100.0, float(milled_pct)))
    fill_count = max(0, int(root.SystemSetting.get_float("extraction_default_fill_count", 1) or 0))
    fill_total_weight_lbs = _setting_float_or_none(root, "extraction_default_fill_total_weight_lbs")
    flush_count = max(0, int(root.SystemSetting.get_float("extraction_default_flush_count", 0) or 0))
    flush_total_weight_lbs = _setting_float_or_none(root, "extraction_default_flush_total_weight_lbs")
    stringer_basket_count = max(0, int(root.SystemSetting.get_float("extraction_default_stringer_basket_count", 0) or 0))
    crc_blend = (root.SystemSetting.get("extraction_default_crc_blend", "") or "").strip()
    return {
        "biomass_blend_milled_pct": milled_pct,
        "biomass_blend_unmilled_pct": round(100.0 - milled_pct, 1),
        "fill_count": fill_count,
        "fill_total_weight_lbs": fill_total_weight_lbs,
        "flush_count": flush_count,
        "flush_total_weight_lbs": flush_total_weight_lbs,
        "stringer_basket_count": stringer_basket_count,
        "crc_blend": crc_blend,
    }


def extraction_timing_targets(root) -> dict[str, int | None]:
    return {
        "primary_soak_minutes": int(root.SystemSetting.get_float("extraction_target_primary_soak_minutes", 30) or 30),
        "mixer_minutes": int(root.SystemSetting.get_float("extraction_target_mixer_minutes", 5) or 5),
        "flush_minutes": int(root.SystemSetting.get_float("extraction_target_flush_minutes", 10) or 10),
        "final_purge_minutes": _opt_int(root.SystemSetting.get("extraction_target_final_purge_minutes", "") or "", field="Final purge target"),
    }


def extraction_timing_policies(root) -> dict[str, str]:
    allowed = {value for value, _label in TIMING_POLICY_OPTIONS}
    return {
        "primary_soak": _normalized_timing_policy(root.SystemSetting.get("extraction_policy_primary_soak", TIMING_POLICY_DEFAULTS["extraction_policy_primary_soak"][0]), allowed),
        "mixer": _normalized_timing_policy(root.SystemSetting.get("extraction_policy_mixer", TIMING_POLICY_DEFAULTS["extraction_policy_mixer"][0]), allowed),
        "flush": _normalized_timing_policy(root.SystemSetting.get("extraction_policy_flush", TIMING_POLICY_DEFAULTS["extraction_policy_flush"][0]), allowed),
        "final_purge": _normalized_timing_policy(root.SystemSetting.get("extraction_policy_final_purge", TIMING_POLICY_DEFAULTS["extraction_policy_final_purge"][0]), allowed),
    }


def _normalized_timing_policy(raw_value: str | None, allowed: set[str]) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in allowed else "warning"


def _utc_now_localized() -> datetime:
    return datetime.now(app_display_zoneinfo()).astimezone(timezone.utc)


def ensure_booth_session(root, run, charge=None):
    session = getattr(run, "booth_session", None)
    if session is None and getattr(run, "id", None):
        session = root.ExtractionBoothSession.query.filter_by(run_id=run.id).first()
    if session is not None:
        if charge is not None and getattr(session, "charge_id", None) != getattr(charge, "id", None):
            session.charge_id = getattr(charge, "id", None)
        if getattr(session, "operator_user_id", None) is None:
            session.operator_user_id = getattr(root.current_user, "id", None)
        return session

    session = root.ExtractionBoothSession(
        run_id=run.id,
        charge_id=getattr(charge, "id", None),
        operator_user_id=getattr(root.current_user, "id", None),
        current_stage_key="ready_to_confirm_vacuum",
        status="in_progress",
    )
    root.db.session.add(session)
    root.db.session.flush()
    return session


def _booth_event(root, session, event_key: str):
    return (
        session.booth_events.filter_by(event_key=event_key)
        .order_by(root.ExtractionBoothEvent.occurred_at.desc())
        .first()
    )


def _record_booth_event(root, session, *, event_key: str, event_label: str, numeric_value=None, text_value=None, decision_value=None, payload=None):
    event = root.ExtractionBoothEvent(
        session_id=session.id,
        run_id=session.run_id,
        event_key=event_key,
        event_label=event_label,
        stage_key=session.current_stage_key,
        occurred_at=_utc_now_localized(),
        recorded_by_user_id=getattr(root.current_user, "id", None),
        decision_value=decision_value,
        numeric_value=numeric_value,
        text_value=text_value,
        payload_json=root.json.dumps(payload or {}) if payload else None,
    )
    root.db.session.add(event)
    return event


def booth_session_payload(root, run) -> dict:
    session = getattr(run, "booth_session", None)
    if session is None:
        return {
            "status": "not_started",
            "current_stage_key": "ready_to_confirm_vacuum",
            "primary_solvent_charge_lbs": None,
            "primary_solvent_charged_at": "",
            "flush_solvent_chiller_temp_f": None,
            "flush_plate_temp_f": None,
            "flush_temp_verified_at": "",
            "flush_temp_threshold_passed": None,
            "flush_temp_slack_post_confirmed_at": "",
            "flush_solvent_charge_lbs": None,
            "flush_solvent_charged_at": "",
            "flow_resumed_decision": "",
            "flow_resumed_confirmed_at": "",
            "final_purge_started_at": "",
            "final_purge_completed_at": "",
            "final_purge_duration_minutes": None,
            "final_clarity_decision": "",
            "final_clarity_confirmed_at": "",
            "final_recovery_inlets_closed_at": "",
            "filtration_pumpdown_started_at": "",
            "nitrogen_turned_off_at": "",
            "dewax_inlet_closed_at": "",
            "booth_process_completed_at": "",
            "timing_targets": extraction_timing_targets(root),
            "evidence_counts": {},
            "history": [],
        }
    history = (
        session.booth_events.order_by(root.ExtractionBoothEvent.occurred_at.desc()).limit(8).all()
        if hasattr(session.booth_events, "order_by")
        else []
    )
    return {
        "status": session.status,
        "current_stage_key": session.current_stage_key,
        "primary_solvent_charge_lbs": float(session.primary_solvent_charge_lbs or 0) if session.primary_solvent_charge_lbs is not None else None,
        "primary_solvent_charged_at": display_local_datetime(session.primary_solvent_charged_at),
        "flush_solvent_chiller_temp_f": float(session.flush_solvent_chiller_temp_f or 0) if session.flush_solvent_chiller_temp_f is not None else None,
        "flush_plate_temp_f": float(session.flush_plate_temp_f or 0) if session.flush_plate_temp_f is not None else None,
        "flush_temp_verified_at": display_local_datetime(session.flush_temp_verified_at),
        "flush_temp_threshold_passed": session.flush_temp_threshold_passed,
        "flush_temp_slack_post_confirmed_at": display_local_datetime(session.flush_temp_slack_post_confirmed_at),
        "flush_solvent_charge_lbs": float(session.flush_solvent_charge_lbs or 0) if session.flush_solvent_charge_lbs is not None else None,
        "flush_solvent_charged_at": display_local_datetime(session.flush_solvent_charged_at),
        "flow_resumed_decision": session.flow_resumed_decision or "",
        "flow_resumed_confirmed_at": display_local_datetime(session.flow_resumed_confirmed_at),
        "final_purge_started_at": display_local_datetime(session.final_purge_started_at),
        "final_purge_completed_at": display_local_datetime(session.final_purge_completed_at),
        "final_purge_duration_minutes": duration_minutes(session.final_purge_started_at, session.final_purge_completed_at),
        "final_clarity_decision": session.final_clarity_decision or "",
        "final_clarity_confirmed_at": display_local_datetime(session.final_clarity_confirmed_at),
        "final_recovery_inlets_closed_at": display_local_datetime(session.final_recovery_inlets_closed_at),
        "filtration_pumpdown_started_at": display_local_datetime(session.filtration_pumpdown_started_at),
        "nitrogen_turned_off_at": display_local_datetime(session.nitrogen_turned_off_at),
        "dewax_inlet_closed_at": display_local_datetime(session.dewax_inlet_closed_at),
        "booth_process_completed_at": display_local_datetime(session.booth_process_completed_at),
        "timing_targets": extraction_timing_targets(root),
        "evidence_counts": {
            "solvent_chiller_temp_photo": session.booth_evidence.filter_by(evidence_type="solvent_chiller_temp_photo").count(),
            "plate_temp_photo": session.booth_evidence.filter_by(evidence_type="plate_temp_photo").count(),
        } if hasattr(session.booth_evidence, "filter_by") else {},
        "history": [
            {
                "event_key": item.event_key,
                "event_label": item.event_label,
                "occurred_at": display_local_timestamp(item.occurred_at),
            }
            for item in history
        ],
    }


def _active_duration_minutes(start_at: datetime | None) -> int | None:
    if start_at is None:
        return None
    start = start_at if start_at.tzinfo is not None else start_at.replace(tzinfo=timezone.utc)
    delta_seconds = (_utc_now_localized() - start).total_seconds()
    if delta_seconds < 0:
        return None
    return int(round(delta_seconds / 60.0))


def timing_control_payload(*, label: str, target_minutes: int | None, start_at: datetime | None, end_at: datetime | None) -> dict:
    actual_minutes = duration_minutes(start_at, end_at)
    active_minutes = _active_duration_minutes(start_at) if start_at is not None and end_at is None else None
    if start_at is None:
        status = "not_started"
    elif end_at is None:
        if target_minutes is None:
            status = "active"
        else:
            status = "active_target_reached" if (active_minutes or 0) >= target_minutes else "active_on_track"
    elif target_minutes is None:
        status = "recorded"
    else:
        status = "on_target" if (actual_minutes or 0) >= target_minutes else "short"
    delta_minutes = None
    if target_minutes is not None:
        baseline = active_minutes if end_at is None else actual_minutes
        if baseline is not None:
            delta_minutes = baseline - target_minutes
    return {
        "label": label,
        "target_minutes": target_minutes,
        "actual_minutes": actual_minutes,
        "active_minutes": active_minutes,
        "status": status,
        "delta_minutes": delta_minutes,
    }


def _notify_short_timing(
    root,
    run,
    session,
    *,
    event_key: str,
    label: str,
    actual_minutes: int | None,
    target_minutes: int | None,
    policy: str = "warning",
    operator_reason: str | None = None,
) -> None:
    if actual_minutes is None or target_minutes is None or actual_minutes >= target_minutes:
        resolve_matching_notifications(
            root,
            run=run,
            dedupe_keys=[event_key],
            note=f"{label} no longer appears short of target.",
        )
        return
    if policy == "informational":
        return
    create_notification(
        root,
        run=run,
        booth_session=session,
        event_key=event_key,
        dedupe_key=event_key,
        notification_class="warnings",
        severity="critical" if policy == "supervisor_override" else "warning",
        title=f"{label} finished short of target",
        message=(
            f"{label} recorded {actual_minutes} minute(s) against a {target_minutes}-minute target."
            + (" Supervisor override is required before continuing." if policy == "supervisor_override" else "")
        ),
        operator_reason=operator_reason,
    )


def _required_reason(payload: dict, field_name: str, prompt: str) -> str:
    reason = (payload.get(field_name) or "").strip()
    if not reason:
        raise ValueError(prompt)
    return reason


def _notification_override_approved(root, run, dedupe_key: str) -> bool:
    if run is None or getattr(run, "id", None) is None:
        return False
    row = root.SupervisorNotification.query.filter(
        root.SupervisorNotification.run_id == run.id,
        root.SupervisorNotification.dedupe_key == dedupe_key,
    ).order_by(root.SupervisorNotification.created_at.desc()).first()
    return bool(row is not None and (row.override_decision or "") == "approved_deviation")


def _active_override_required_notification(root, run, dedupe_key: str):
    if run is None or getattr(run, "id", None) is None:
        return None
    return root.SupervisorNotification.query.filter(
        root.SupervisorNotification.run_id == run.id,
        root.SupervisorNotification.dedupe_key == dedupe_key,
        root.SupervisorNotification.status.in_(("open", "acknowledged")),
    ).order_by(root.SupervisorNotification.created_at.desc()).first()


def _policy_block_payload(root, run, timing_key: str, dedupe_key: str, title: str) -> dict | None:
    policy = extraction_timing_policies(root).get(timing_key, "warning")
    if policy != "supervisor_override":
        return None
    row = _active_override_required_notification(root, run, dedupe_key)
    if row is None:
        return None
    if _notification_override_approved(root, run, dedupe_key):
        return None
    return {
        "timing_key": timing_key,
        "dedupe_key": dedupe_key,
        "title": title,
        "message": f"{title} requires supervisor override before the booth workflow can continue.",
        "notification_id": row.id,
    }


def _timing_policy_message(label: str, policy: str) -> str:
    if policy == "hard_stop":
        return f"{label} is configured as a hard stop. Continue the timed step until target is met."
    return f"{label} requires supervisor override before the booth workflow can continue."


def run_timing_controls_payload(root, run) -> dict:
    booth_session = getattr(run, "booth_session", None)
    timing_targets = extraction_timing_targets(root)
    timing_policies = extraction_timing_policies(root)
    payload = {
        "primary_soak": timing_control_payload(
            label="Primary soak",
            target_minutes=timing_targets.get("primary_soak_minutes"),
            start_at=getattr(run, "run_fill_started_at", None),
            end_at=getattr(run, "run_fill_ended_at", None),
        ),
        "mixer": timing_control_payload(
            label="Mixer",
            target_minutes=timing_targets.get("mixer_minutes"),
            start_at=getattr(run, "mixer_started_at", None),
            end_at=getattr(run, "mixer_ended_at", None),
        ),
        "flush": timing_control_payload(
            label="Flush soak",
            target_minutes=timing_targets.get("flush_minutes"),
            start_at=getattr(run, "flush_started_at", None),
            end_at=getattr(run, "flush_ended_at", None),
        ),
        "final_purge": timing_control_payload(
            label="Final purge",
            target_minutes=timing_targets.get("final_purge_minutes"),
            start_at=getattr(booth_session, "final_purge_started_at", None),
            end_at=getattr(booth_session, "final_purge_completed_at", None),
        ),
    }
    for key, item in payload.items():
        item["policy"] = timing_policies.get(key, "warning")
    return payload


def run_progression_payload(root, run) -> dict:
    session = getattr(run, "booth_session", None)
    if run.run_completed_at:
        stage_key = "completed"
    elif session is not None and (session.current_stage_key or "").strip() in RUN_PROGRESSION and (session.current_stage_key or "").strip() != "completed":
        stage_key = session.current_stage_key
    elif run.flush_started_at and not run.flush_ended_at:
        stage_key = "flushing"
    elif run.flush_ended_at:
        stage_key = "ready_to_complete"
    elif run.mixer_started_at and not run.mixer_ended_at:
        stage_key = "mixing"
    elif run.mixer_ended_at:
        stage_key = "ready_to_confirm_filter_clear"
    else:
        stage_key = "ready_to_confirm_vacuum"
    config = dict(RUN_PROGRESSION[stage_key])
    block = None
    if root is not None and run is not None:
        if stage_key in {"ready_to_start_mixer"}:
            block = _policy_block_payload(root, run, "primary_soak", "timing_short_primary_soak", "Primary soak timing deviation")
        elif stage_key in {"ready_to_confirm_filter_clear", "ready_to_start_pressurization", "ready_to_begin_recovery", "ready_to_begin_flush_cycle"}:
            block = _policy_block_payload(root, run, "mixer", "timing_short_mixer", "Mixer timing deviation")
        elif stage_key in {"ready_to_confirm_flow_resumed", "flow_adjustment_required", "ready_to_start_final_purge"}:
            block = _policy_block_payload(root, run, "flush", "timing_short_flush", "Flush timing deviation")
        elif stage_key in {"ready_to_confirm_clarity", "clarity_adjustment_required", "ready_to_complete_shutdown", "ready_to_complete"}:
            block = _policy_block_payload(root, run, "final_purge", "timing_short_final_purge", "Final purge timing deviation")
    if session is not None and stage_key == "ready_to_confirm_flow_resumed" and (session.flow_resumed_decision or "").strip().lower() == "no_adjusting":
        config["description"] = "Flow is still being adjusted. Re-check once recovery flow has resumed, then continue to final purge."
    if session is not None and stage_key == "ready_to_confirm_clarity" and (session.final_clarity_decision or "").strip().lower() == "not_yet":
        config["description"] = "Final clarity is not there yet. Confirm again after additional purge or adjustment work."
    if block is not None:
        config["description"] = block["message"]
        config["actions"] = []
    return {
        "stage_key": stage_key,
        "stage_label": config["label"],
        "description": config["description"],
        "actions": list(config["actions"]),
        "completed_at": display_local_datetime(run.run_completed_at),
        "policy_block": block,
    }


def post_extraction_progression_payload(run) -> dict:
    pathway = (getattr(run, "post_extraction_pathway", None) or "").strip()
    if not getattr(run, "run_completed_at", None):
        return {
            "stage_key": "blocked_until_run_complete",
            "stage_label": "Complete extraction first",
            "description": "Post-extraction handoff begins only after the extraction run is marked complete.",
            "actions": [],
            "pathway_label": POST_EXTRACTION_PATHWAY_LABELS.get(pathway, ""),
        }
    if not getattr(run, "post_extraction_started_at", None):
        return {
            "stage_key": "ready_to_start",
            "stage_label": "Ready to start post-extraction",
            "description": "Select the downstream pathway and start the post-extraction session.",
            "actions": [{"action_id": "start_post_extraction", "label": "Start Post-Extraction"}],
            "pathway_label": POST_EXTRACTION_PATHWAY_LABELS.get(pathway, ""),
        }
    if not getattr(run, "post_extraction_initial_outputs_recorded_at", None):
        return {
            "stage_key": "ready_to_confirm_initial_outputs",
            "stage_label": "Ready to confirm initial outputs",
            "description": "Record the initial wet THCA and wet HTE outputs to hand this run into downstream processing.",
            "actions": [{"action_id": "confirm_initial_outputs", "label": "Confirm Initial Outputs"}],
            "pathway_label": POST_EXTRACTION_PATHWAY_LABELS.get(pathway, ""),
        }
    return {
        "stage_key": "session_started",
        "stage_label": "Post-extraction session started",
        "description": "The run has been handed off into the downstream post-extraction workflow foundation.",
        "actions": [],
        "pathway_label": POST_EXTRACTION_PATHWAY_LABELS.get(pathway, ""),
    }


def apply_progression_action(root, run, action_id: str | None, payload: dict | None = None) -> None:
    action = (action_id or "").strip()
    if not action:
        return
    now = _utc_now_localized()
    session = ensure_booth_session(root, run)
    payload = payload or {}
    active_block = (
        _policy_block_payload(root, run, "primary_soak", "timing_short_primary_soak", "Primary soak timing deviation")
        or _policy_block_payload(root, run, "mixer", "timing_short_mixer", "Mixer timing deviation")
        or _policy_block_payload(root, run, "flush", "timing_short_flush", "Flush timing deviation")
        or _policy_block_payload(root, run, "final_purge", "timing_short_final_purge", "Final purge timing deviation")
    )
    if active_block is not None:
        raise ValueError(active_block["message"])
    if action == "confirm_vacuum_down":
        if _booth_event(root, session, "reactor_vacuum_confirmed") is None:
            _record_booth_event(root, session, event_key="reactor_vacuum_confirmed", event_label="Reactor vacuum confirmed")
        session.current_stage_key = "ready_to_record_solvent_charge"
        return
    if action == "record_solvent_charge":
        if _booth_event(root, session, "reactor_vacuum_confirmed") is None:
            raise ValueError("Confirm vacuum down before recording solvent charge.")
        try:
            solvent_lbs = float(payload.get("primary_solvent_charge_lbs") or 0)
        except (TypeError, ValueError):
            raise ValueError("Primary solvent charge must be a number.")
        if solvent_lbs <= 0:
            raise ValueError("Enter the primary solvent charge before continuing.")
        session.primary_solvent_charge_lbs = solvent_lbs
        if session.primary_solvent_charged_at is None:
            session.primary_solvent_charged_at = now
        if _booth_event(root, session, "primary_solvent_charged") is None:
            _record_booth_event(
                root,
                session,
                event_key="primary_solvent_charged",
                event_label="Primary solvent charge recorded",
                numeric_value=solvent_lbs,
            )
        session.current_stage_key = "ready_to_start_primary_soak"
        return
    if action == "start_primary_soak":
        if session.primary_solvent_charged_at is None:
            raise ValueError("Record the primary solvent charge before starting the soak.")
        if run.run_fill_started_at is None:
            run.run_fill_started_at = now
        if _booth_event(root, session, "primary_soak_started") is None:
            _record_booth_event(root, session, event_key="primary_soak_started", event_label="Primary soak started")
        session.current_stage_key = "ready_to_start_mixer"
        return
    if action == "start_mixer":
        if run.run_fill_started_at is None:
            raise ValueError("Start the primary soak before starting the mixer.")
        primary_soak_minutes = _active_duration_minutes(run.run_fill_started_at)
        primary_soak_target = extraction_timing_targets(root).get("primary_soak_minutes")
        primary_soak_policy = extraction_timing_policies(root).get("primary_soak", "warning")
        primary_soak_short = (
            primary_soak_minutes is not None
            and primary_soak_target is not None
            and primary_soak_minutes < primary_soak_target
        )
        if primary_soak_short and primary_soak_policy == "hard_stop":
            raise ValueError(_timing_policy_message("Primary soak", "hard_stop"))
        if primary_soak_short and primary_soak_policy == "supervisor_override" and not _notification_override_approved(root, run, "timing_short_primary_soak"):
            primary_reason = _required_reason(
                payload,
                "primary_soak_short_reason",
                "Enter a reason when the primary soak finishes short of target.",
            )
            create_notification(
                root,
                run=run,
                booth_session=session,
                event_key="timing_short_primary_soak",
                dedupe_key="timing_short_primary_soak",
                notification_class="warnings",
                severity="critical",
                title="Primary soak finished short of target",
                message=f"Primary soak reached {primary_soak_minutes} minute(s) against a {primary_soak_target}-minute target and requires supervisor override.",
                operator_reason=primary_reason,
            )
            raise ValueError(_timing_policy_message("Primary soak", "supervisor_override"))
        if primary_soak_short and primary_soak_policy == "warning":
            primary_reason = _required_reason(
                payload,
                "primary_soak_short_reason",
                "Enter a reason when the primary soak finishes short of target.",
            )
            _notify_short_timing(
                root,
                run,
                session,
                event_key="timing_short_primary_soak",
                label="Primary soak",
                actual_minutes=primary_soak_minutes,
                target_minutes=primary_soak_target,
                policy=primary_soak_policy,
                operator_reason=primary_reason,
            )
        if run.mixer_started_at is None:
            run.mixer_started_at = now
        if _booth_event(root, session, "primary_mixer_started") is None:
            _record_booth_event(root, session, event_key="primary_mixer_started", event_label="Primary mixer started")
        session.current_stage_key = "mixing"
        return
    if action == "stop_mixer":
        if run.mixer_started_at is None:
            raise ValueError("Start the mixer before stopping it.")
        prospective_mixer_minutes = duration_minutes(run.mixer_started_at, now)
        mixer_target = extraction_timing_targets(root).get("mixer_minutes")
        mixer_policy = extraction_timing_policies(root).get("mixer", "warning")
        if prospective_mixer_minutes is not None and mixer_target is not None and prospective_mixer_minutes < mixer_target and mixer_policy == "hard_stop":
            raise ValueError(_timing_policy_message("Mixer", "hard_stop"))
        run.mixer_ended_at = now
        mixer_minutes = duration_minutes(run.mixer_started_at, run.mixer_ended_at)
        mixer_short = mixer_minutes is not None and mixer_target is not None and mixer_minutes < mixer_target
        mixer_reason = None
        if mixer_short:
            mixer_reason = _required_reason(
                payload,
                "mixer_short_reason",
                "Enter a reason when the mixer finishes short of target.",
            )
        if _booth_event(root, session, "primary_mixer_stopped") is None:
            _record_booth_event(
                root,
                session,
                event_key="primary_mixer_stopped",
                event_label="Primary mixer stopped",
                text_value=mixer_reason,
                payload={"reason": mixer_reason} if mixer_reason else None,
            )
        _notify_short_timing(
            root,
            run,
            session,
            event_key="timing_short_mixer",
            label="Mixer",
            actual_minutes=mixer_minutes,
            target_minutes=mixer_target,
            policy=mixer_policy,
            operator_reason=mixer_reason,
        )
        session.current_stage_key = "ready_to_confirm_filter_clear"
        return
    if action == "confirm_filter_clear":
        if run.mixer_ended_at is None:
            raise ValueError("Stop the mixer before confirming the filter-clear step.")
        if _booth_event(root, session, "basket_filter_cleared") is None:
            _record_booth_event(root, session, event_key="basket_filter_cleared", event_label="Basket filter cleared")
        session.current_stage_key = "ready_to_start_pressurization"
        return
    if action == "start_pressurization":
        if _booth_event(root, session, "basket_filter_cleared") is None:
            raise ValueError("Confirm filter clear before starting pressurization.")
        if _booth_event(root, session, "nitrogen_pressurization_started") is None:
            _record_booth_event(
                root,
                session,
                event_key="nitrogen_pressurization_started",
                event_label="Nitrogen pressurization started",
            )
        session.current_stage_key = "ready_to_begin_recovery"
        return
    if action == "begin_recovery":
        if _booth_event(root, session, "nitrogen_pressurization_started") is None:
            raise ValueError("Start pressurization before beginning recovery.")
        if _booth_event(root, session, "recovery_flow_started") is None:
            _record_booth_event(root, session, event_key="recovery_flow_started", event_label="Recovery flow started")
        session.current_stage_key = "ready_to_begin_flush_cycle"
        return
    if action == "begin_flush_cycle":
        if _booth_event(root, session, "recovery_flow_started") is None:
            raise ValueError("Begin recovery before moving into the flush cycle.")
        if _booth_event(root, session, "flush_cycle_started") is None:
            _record_booth_event(root, session, event_key="flush_cycle_started", event_label="Flush cycle started")
        session.current_stage_key = "ready_to_verify_flush_temps"
        return
    if action == "verify_flush_temps":
        try:
            chiller_temp = float(payload.get("flush_solvent_chiller_temp_f") or 0)
            plate_temp = float(payload.get("flush_plate_temp_f") or 0)
        except (TypeError, ValueError):
            raise ValueError("Flush temperatures must be numbers.")
        if payload.get("flush_solvent_chiller_temp_f") in (None, "") or payload.get("flush_plate_temp_f") in (None, ""):
            raise ValueError("Enter both flush temperatures before continuing.")
        session.flush_solvent_chiller_temp_f = chiller_temp
        session.flush_plate_temp_f = plate_temp
        session.flush_temp_verified_at = now
        session.flush_temp_threshold_passed = bool(chiller_temp <= -40.0)
        if not session.flush_temp_threshold_passed:
            raise ValueError("Solvent chiller temperature must be at or below -40F before continuing.")
        if _truthy(payload.get("flush_temp_slack_post_confirmed")):
            session.flush_temp_slack_post_confirmed_at = now
        if _booth_event(root, session, "flush_temp_verified") is None:
            _record_booth_event(
                root,
                session,
                event_key="flush_temp_verified",
                event_label="Flush temperatures verified",
                payload={"chiller_temp_f": chiller_temp, "plate_temp_f": plate_temp},
            )
        session.current_stage_key = "ready_to_record_flush_solvent_charge"
        return
    if action == "record_flush_solvent_charge":
        if session.flush_temp_verified_at is None or not session.flush_temp_threshold_passed:
            raise ValueError("Verify flush temperatures before recording the flush solvent charge.")
        try:
            flush_solvent_lbs = float(payload.get("flush_solvent_charge_lbs") or 0)
        except (TypeError, ValueError):
            raise ValueError("Flush solvent charge must be a number.")
        if flush_solvent_lbs <= 0:
            raise ValueError("Enter the flush solvent charge before continuing.")
        session.flush_solvent_charge_lbs = flush_solvent_lbs
        session.flush_solvent_charged_at = now
        if _booth_event(root, session, "flush_solvent_charged") is None:
            _record_booth_event(
                root,
                session,
                event_key="flush_solvent_charged",
                event_label="Flush solvent charge recorded",
                numeric_value=flush_solvent_lbs,
            )
        session.current_stage_key = "ready_to_flush"
        return
    if action == "start_flush":
        if run.mixer_ended_at is None:
            raise ValueError("Stop the mixer before starting the flush.")
        if _booth_event(root, session, "flush_cycle_started") is None:
            raise ValueError("Begin the flush cycle before starting the flush timer.")
        if session.flush_solvent_charged_at is None:
            raise ValueError("Record the flush solvent charge before starting the flush.")
        if run.flush_started_at is None:
            run.flush_started_at = now
        session.current_stage_key = "flushing"
        return
    if action == "stop_flush":
        if run.flush_started_at is None:
            raise ValueError("Start the flush before stopping it.")
        prospective_flush_minutes = duration_minutes(run.flush_started_at, now)
        flush_target = extraction_timing_targets(root).get("flush_minutes")
        flush_policy = extraction_timing_policies(root).get("flush", "warning")
        if prospective_flush_minutes is not None and flush_target is not None and prospective_flush_minutes < flush_target and flush_policy == "hard_stop":
            raise ValueError(_timing_policy_message("Flush soak", "hard_stop"))
        run.flush_ended_at = now
        flush_minutes = duration_minutes(run.flush_started_at, run.flush_ended_at)
        flush_short = flush_minutes is not None and flush_target is not None and flush_minutes < flush_target
        flush_reason = None
        if flush_short:
            flush_reason = _required_reason(
                payload,
                "flush_short_reason",
                "Enter a reason when the flush soak finishes short of target.",
            )
        _record_booth_event(
            root,
            session,
            event_key="flush_stopped",
            event_label="Flush soak stopped",
            text_value=flush_reason,
            payload={"reason": flush_reason} if flush_reason else None,
        )
        _notify_short_timing(
            root,
            run,
            session,
            event_key="timing_short_flush",
            label="Flush soak",
            actual_minutes=flush_minutes,
            target_minutes=flush_target,
            policy=flush_policy,
            operator_reason=flush_reason,
        )
        session.current_stage_key = "ready_to_confirm_flow_resumed"
        return
    if action == "confirm_flow_resumed":
        decision = (payload.get("flow_resumed_decision") or "").strip().lower()
        if decision not in {"yes", "no_adjusting"}:
            raise ValueError("Choose whether flow resumed before continuing.")
        flow_reason = None
        if decision == "no_adjusting":
            flow_reason = _required_reason(
                payload,
                "flow_adjustment_reason",
                "Enter a reason when flow is still being adjusted.",
            )
        session.flow_resumed_decision = decision
        session.flow_resumed_confirmed_at = now
        _record_booth_event(
            root,
            session,
            event_key="flow_resumed_decision",
            event_label="Flow resumed confirmed" if decision == "yes" else "Flow still adjusting",
            decision_value=decision,
            text_value=flow_reason,
            payload={"reason": flow_reason} if flow_reason else None,
        )
        if decision == "yes":
            resolve_matching_notifications(
                root,
                run=run,
                dedupe_keys=["flow_adjustment_required"],
                note="Flow resumed was later confirmed in the booth workflow.",
            )
        else:
            create_notification(
                root,
                run=run,
                booth_session=session,
                event_key="flow_adjustment_required",
                dedupe_key="flow_adjustment_required",
                notification_class="warnings",
                severity="critical",
                title="Flow adjustment required",
                message="Recovery flow did not resume after flush adjustments. Supervisor review is required until the flow check passes.",
                operator_reason=flow_reason,
            )
        session.current_stage_key = "ready_to_start_final_purge" if decision == "yes" else "flow_adjustment_required"
        return
    if action == "resume_flow_check":
        if session.flow_resumed_decision != "no_adjusting":
            raise ValueError("Use flow adjustment only when flow is still being adjusted.")
        _record_booth_event(root, session, event_key="flow_adjustment_resumed", event_label="Flow adjustment resumed")
        session.current_stage_key = "ready_to_confirm_flow_resumed"
        return
    if action == "start_final_purge":
        if session.flow_resumed_decision != "yes":
            raise ValueError("Confirm flow resumed before starting final purge.")
        session.final_purge_started_at = now
        session.final_purge_completed_at = None
        _record_booth_event(root, session, event_key="final_purge_started", event_label="Final purge started")
        session.current_stage_key = "purging"
        return
    if action == "stop_final_purge":
        if session.final_purge_started_at is None:
            raise ValueError("Start final purge before stopping it.")
        prospective_final_purge_minutes = duration_minutes(session.final_purge_started_at, now)
        final_purge_target = extraction_timing_targets(root).get("final_purge_minutes")
        final_purge_policy = extraction_timing_policies(root).get("final_purge", "informational")
        if prospective_final_purge_minutes is not None and final_purge_target is not None and prospective_final_purge_minutes < final_purge_target and final_purge_policy == "hard_stop":
            raise ValueError(_timing_policy_message("Final purge", "hard_stop"))
        session.final_purge_completed_at = now
        final_purge_minutes = duration_minutes(session.final_purge_started_at, session.final_purge_completed_at)
        final_purge_short = final_purge_minutes is not None and final_purge_target is not None and final_purge_minutes < final_purge_target
        final_purge_reason = None
        if final_purge_short:
            final_purge_reason = _required_reason(
                payload,
                "final_purge_short_reason",
                "Enter a reason when the final purge finishes short of target.",
            )
        _record_booth_event(
            root,
            session,
            event_key="final_purge_completed",
            event_label="Final purge completed",
            text_value=final_purge_reason,
            payload={"reason": final_purge_reason} if final_purge_reason else None,
        )
        _notify_short_timing(
            root,
            run,
            session,
            event_key="timing_short_final_purge",
            label="Final purge",
            actual_minutes=final_purge_minutes,
            target_minutes=final_purge_target,
            policy=final_purge_policy,
            operator_reason=final_purge_reason,
        )
        session.current_stage_key = "ready_to_confirm_clarity"
        return
    if action == "confirm_final_clarity":
        decision = (payload.get("final_clarity_decision") or "").strip().lower()
        if decision not in {"yes", "not_yet"}:
            raise ValueError("Choose whether the system is clear enough to proceed.")
        clarity_reason = None
        if decision == "not_yet":
            clarity_reason = _required_reason(
                payload,
                "final_clarity_reason",
                "Enter a reason when final clarity is not yet acceptable.",
            )
        session.final_clarity_decision = decision
        session.final_clarity_confirmed_at = now
        _record_booth_event(
            root,
            session,
            event_key="final_clarity_confirmed",
            event_label="Final clarity confirmed" if decision == "yes" else "Final clarity not yet acceptable",
            decision_value=decision,
            text_value=clarity_reason,
            payload={"reason": clarity_reason} if clarity_reason else None,
        )
        if decision == "yes":
            resolve_matching_notifications(
                root,
                run=run,
                dedupe_keys=["final_clarity_retry_required"],
                note="Final clarity was later confirmed in the booth workflow.",
            )
        else:
            create_notification(
                root,
                run=run,
                booth_session=session,
                event_key="final_clarity_retry_required",
                dedupe_key="final_clarity_retry_required",
                notification_class="warnings",
                severity="critical",
                title="Final clarity still out of scope",
                message="Final clarity was marked not yet acceptable. Supervisor review is required until purge work is completed and clarity is re-confirmed.",
                operator_reason=clarity_reason,
            )
        session.current_stage_key = "ready_to_complete_shutdown" if decision == "yes" else "clarity_adjustment_required"
        return
    if action == "resume_final_purge":
        if session.final_clarity_decision != "not_yet":
            raise ValueError("Resume final purge only when clarity is not yet acceptable.")
        _record_booth_event(root, session, event_key="final_purge_resumed", event_label="Final purge resumed for additional clarity work")
        session.current_stage_key = "ready_to_start_final_purge"
        return
    if action == "complete_shutdown":
        if not _truthy(payload.get("shutdown_recovery_inlets_closed")):
            raise ValueError("Confirm recovery inlets are closed before completing shutdown.")
        if not _truthy(payload.get("shutdown_filtration_pumpdown_started")):
            raise ValueError("Confirm filtration pump-down started before completing shutdown.")
        if not _truthy(payload.get("shutdown_nitrogen_off")):
            raise ValueError("Confirm nitrogen is off before completing shutdown.")
        if not _truthy(payload.get("shutdown_dewax_inlet_closed")):
            raise ValueError("Confirm the dewax inlet is closed before completing shutdown.")
        session.final_recovery_inlets_closed_at = session.final_recovery_inlets_closed_at or now
        session.filtration_pumpdown_started_at = session.filtration_pumpdown_started_at or now
        session.nitrogen_turned_off_at = session.nitrogen_turned_off_at or now
        session.dewax_inlet_closed_at = session.dewax_inlet_closed_at or now
        session.booth_process_completed_at = now
        if _booth_event(root, session, "shutdown_completed") is None:
            _record_booth_event(root, session, event_key="shutdown_completed", event_label="Shutdown checklist completed")
        session.current_stage_key = "ready_to_complete"
        return
    if action == "mark_complete":
        if run.flush_ended_at is None:
            raise ValueError("Stop the flush before completing the run.")
        if session.booth_process_completed_at is None:
            raise ValueError("Complete the shutdown checklist before completing the run.")
        run.run_completed_at = now
        session.current_stage_key = "completed"
        session.completed_at = now
        session.status = "completed"
        create_notification(
            root,
            run=run,
            booth_session=session,
            event_key="run_completed",
            dedupe_key=f"run_completed:{run.id}",
            notification_class="completions",
            severity="info",
            title="Extraction run completed",
            message=f"Run {run.run_date.isoformat() if run.run_date else run.id} on reactor {run.reactor_number} completed the booth workflow.",
        )
        return
    raise ValueError("Unknown run progression action.")


def apply_post_extraction_action(run, action_id: str | None) -> None:
    action = (action_id or "").strip()
    if not action:
        return
    if run.run_completed_at is None:
        raise ValueError("Complete the extraction run before starting post-extraction.")
    now = _utc_now_localized()
    pathway = (getattr(run, "post_extraction_pathway", None) or "").strip()
    if action == "start_post_extraction":
        if not pathway:
            raise ValueError("Select the post-extraction pathway before starting the session.")
        if run.post_extraction_started_at is None:
            run.post_extraction_started_at = now
        return
    if action == "confirm_initial_outputs":
        if run.post_extraction_started_at is None:
            raise ValueError("Start the post-extraction session before confirming outputs.")
        if not pathway:
            raise ValueError("Select the post-extraction pathway before confirming outputs.")
        if run.wet_thca_g is None or run.wet_hte_g is None:
            raise ValueError("Enter both wet THCA and wet HTE before confirming the initial outputs.")
        run.post_extraction_initial_outputs_recorded_at = now
        return
    raise ValueError("Unknown post-extraction action.")


def parse_local_datetime(raw_value: str | None) -> datetime | None:
    text = (raw_value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=app_display_zoneinfo()).astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError("Enter a valid local date and time.")


def display_local_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_display_zoneinfo()).strftime("%Y-%m-%dT%H:%M")


def display_local_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_display_zoneinfo()).strftime("%Y-%m-%d %H:%M")


def duration_minutes(start_at: datetime | None, end_at: datetime | None) -> int | None:
    if start_at is None or end_at is None:
        return None
    start = start_at if start_at.tzinfo is not None else start_at.replace(tzinfo=timezone.utc)
    end = end_at if end_at.tzinfo is not None else end_at.replace(tzinfo=timezone.utc)
    delta_seconds = (end - start).total_seconds()
    if delta_seconds < 0:
        return None
    return int(round(delta_seconds / 60.0))


def downstream_state_payload(run) -> dict:
    return {
        "thca_destination_label": THCA_DESTINATION_LABELS.get(getattr(run, "thca_destination", None) or "", ""),
        "hte_clean_decision_label": HTE_CLEAN_DECISION_LABELS.get(getattr(run, "hte_clean_decision", None) or "", ""),
        "hte_filter_outcome_label": HTE_FILTER_OUTCOME_LABELS.get(getattr(run, "hte_filter_outcome", None) or "", ""),
        "hte_potency_disposition_label": HTE_POTENCY_DISPOSITION_LABELS.get(getattr(run, "hte_potency_disposition", None) or "", ""),
        "hte_queue_destination_label": HTE_QUEUE_DESTINATION_LABELS.get(getattr(run, "hte_queue_destination", None) or "", ""),
        "pot_pour_offgas_duration_hours": duration_minutes(getattr(run, "pot_pour_offgas_started_at", None), getattr(run, "pot_pour_offgas_completed_at", None)),
        "thca_oven_duration_hours": duration_minutes(getattr(run, "thca_oven_started_at", None), getattr(run, "thca_oven_completed_at", None)),
        "hte_offgas_duration_hours": duration_minutes(getattr(run, "hte_offgas_started_at", None), getattr(run, "hte_offgas_completed_at", None)),
    }


def _opt_float(value, *, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")


def _opt_int(value, *, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number.")


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clamped_percent(value, *, field: str) -> float | None:
    parsed = _opt_float(value, field=field)
    if parsed is None:
        return None
    if parsed < 0 or parsed > 100:
        raise ValueError(f"{field} must be between 0 and 100.")
    return parsed


def apply_execution_payload(run, payload: dict) -> None:
    if "run_type" in payload:
        run.run_type = (payload.get("run_type") or "").strip() or "standard"

    if "wet_hte_g" in payload:
        run.wet_hte_g = _opt_float(payload.get("wet_hte_g"), field="Wet HTE")
    if "wet_thca_g" in payload:
        run.wet_thca_g = _opt_float(payload.get("wet_thca_g"), field="Wet THCA")

    if "biomass_blend_milled_pct" in payload or "biomass_blend_unmilled_pct" in payload:
        milled_pct = _clamped_percent(
            payload.get("biomass_blend_milled_pct", run.biomass_blend_milled_pct), field="Milled blend %"
        )
        unmilled_pct = _clamped_percent(
            payload.get("biomass_blend_unmilled_pct", run.biomass_blend_unmilled_pct), field="Unmilled blend %"
        )
        if milled_pct is not None and unmilled_pct is not None and abs((milled_pct + unmilled_pct) - 100.0) > 0.6:
            raise ValueError("Milled and unmilled blend percentages must total 100.")
        run.biomass_blend_milled_pct = milled_pct
        run.biomass_blend_unmilled_pct = unmilled_pct

    field_map = (
        ("run_fill_started_at", parse_local_datetime),
        ("run_fill_ended_at", parse_local_datetime),
        ("flush_count", lambda value: _opt_int(value, field="Flush count")),
        ("flush_total_weight_lbs", lambda value: _opt_float(value, field="Flush total weight")),
        ("fill_count", lambda value: _opt_int(value, field="Fill count")),
        ("fill_total_weight_lbs", lambda value: _opt_float(value, field="Fill total weight")),
        ("stringer_basket_count", lambda value: _opt_int(value, field="Stringer basket count")),
        ("mixer_started_at", parse_local_datetime),
        ("mixer_ended_at", parse_local_datetime),
        ("flush_started_at", parse_local_datetime),
        ("flush_ended_at", parse_local_datetime),
        ("run_completed_at", parse_local_datetime),
    )
    for key, parser in field_map:
        if key in payload:
            setattr(run, key, parser(payload.get(key)))
    if "crc_blend" in payload:
        run.crc_blend = (payload.get("crc_blend") or "").strip() or None
    if "notes" in payload:
        run.notes = (payload.get("notes") or "").strip() or None
    if "post_extraction_pathway" in payload:
        pathway = (payload.get("post_extraction_pathway") or "").strip()
        allowed = {value for value, _label in POST_EXTRACTION_PATHWAY_OPTIONS}
        if pathway not in allowed:
            raise ValueError("Post-extraction pathway is invalid.")
        run.post_extraction_pathway = pathway or None
    if "post_extraction_started_at" in payload:
        run.post_extraction_started_at = parse_local_datetime(payload.get("post_extraction_started_at"))
    if "post_extraction_initial_outputs_recorded_at" in payload:
        run.post_extraction_initial_outputs_recorded_at = parse_local_datetime(payload.get("post_extraction_initial_outputs_recorded_at"))
    if "pot_pour_offgas_started_at" in payload:
        run.pot_pour_offgas_started_at = parse_local_datetime(payload.get("pot_pour_offgas_started_at"))
    if "pot_pour_offgas_completed_at" in payload:
        run.pot_pour_offgas_completed_at = parse_local_datetime(payload.get("pot_pour_offgas_completed_at"))
    if "pot_pour_daily_stir_count" in payload:
        run.pot_pour_daily_stir_count = _opt_int(payload.get("pot_pour_daily_stir_count"), field="Pot pour stir count")
    if "pot_pour_centrifuged_at" in payload:
        run.pot_pour_centrifuged_at = parse_local_datetime(payload.get("pot_pour_centrifuged_at"))
    if "thca_oven_started_at" in payload:
        run.thca_oven_started_at = parse_local_datetime(payload.get("thca_oven_started_at"))
    if "thca_oven_completed_at" in payload:
        run.thca_oven_completed_at = parse_local_datetime(payload.get("thca_oven_completed_at"))
    if "thca_milled_at" in payload:
        run.thca_milled_at = parse_local_datetime(payload.get("thca_milled_at"))
    if "thca_destination" in payload:
        destination = (payload.get("thca_destination") or "").strip()
        allowed = {value for value, _label in THCA_DESTINATION_OPTIONS}
        if destination not in allowed:
            raise ValueError("THCA destination is invalid.")
        run.thca_destination = destination or None
    if "hte_offgas_started_at" in payload:
        run.hte_offgas_started_at = parse_local_datetime(payload.get("hte_offgas_started_at"))
    if "hte_offgas_completed_at" in payload:
        run.hte_offgas_completed_at = parse_local_datetime(payload.get("hte_offgas_completed_at"))
    if "hte_clean_decision" in payload:
        decision = (payload.get("hte_clean_decision") or "").strip()
        allowed = {value for value, _label in HTE_CLEAN_DECISION_OPTIONS}
        if decision not in allowed:
            raise ValueError("HTE clean decision is invalid.")
        run.hte_clean_decision = decision or None
    if "hte_filter_outcome" in payload:
        outcome = (payload.get("hte_filter_outcome") or "").strip()
        allowed = {value for value, _label in HTE_FILTER_OUTCOME_OPTIONS}
        if outcome not in allowed:
            raise ValueError("HTE filter outcome is invalid.")
        run.hte_filter_outcome = outcome or None
    if "hte_prescott_processed_at" in payload:
        run.hte_prescott_processed_at = parse_local_datetime(payload.get("hte_prescott_processed_at"))
    if "hte_potency_disposition" in payload:
        disposition = (payload.get("hte_potency_disposition") or "").strip()
        allowed = {value for value, _label in HTE_POTENCY_DISPOSITION_OPTIONS}
        if disposition not in allowed:
            raise ValueError("HTE potency disposition is invalid.")
        run.hte_potency_disposition = disposition or None
    if "hte_queue_destination" in payload:
        destination = (payload.get("hte_queue_destination") or "").strip()
        allowed = {value for value, _label in HTE_QUEUE_DESTINATION_OPTIONS}
        if destination not in allowed:
            raise ValueError("HTE queue destination is invalid.")
        run.hte_queue_destination = destination or None


def _draft_run_for_charge(root, charge):
    prefill = build_charge_prefill_payload(root, charge.lot, charge)
    defaults = extraction_run_defaults(root)
    run = root.Run(
        run_date=root.datetime.strptime(prefill["charge_run_date"], "%Y-%m-%d").date() if prefill.get("charge_run_date") else root.date.today(),
        reactor_number=int(charge.reactor_number or 0) or 1,
        bio_in_reactor_lbs=float(charge.charged_weight_lbs or 0),
        bio_in_house_lbs=0.0,
        run_type="standard",
        created_by=getattr(root.current_user, "id", None),
    )
    run.biomass_blend_milled_pct = defaults["biomass_blend_milled_pct"]
    run.biomass_blend_unmilled_pct = defaults["biomass_blend_unmilled_pct"]
    run.fill_count = defaults["fill_count"]
    run.fill_total_weight_lbs = defaults["fill_total_weight_lbs"]
    run.flush_count = defaults["flush_count"]
    run.flush_total_weight_lbs = defaults["flush_total_weight_lbs"]
    run.stringer_basket_count = defaults["stringer_basket_count"]
    run.crc_blend = defaults["crc_blend"] or None
    if run.fill_total_weight_lbs is None:
        run.fill_total_weight_lbs = float(charge.charged_weight_lbs or 0)
    return run


def _ensure_run_input(root, run, charge) -> None:
    if run.inputs.filter_by(lot_id=charge.purchase_lot_id).first() is not None:
        return
    apply_run_allocations(
        root,
        run,
        [{"lot_id": charge.purchase_lot_id, "weight_lbs": float(charge.charged_weight_lbs or 0)}],
        allocation_source=charge.source_mode or "manual",
        allocation_confidence=1.0,
        slack_ingested_message_id=charge.slack_ingested_message_id,
    )


def ensure_run_for_charge(root, charge):
    if charge.run_id:
        run = root.db.session.get(root.Run, charge.run_id)
        if run is not None:
            _ensure_run_input(root, run, charge)
            ensure_booth_session(root, run, charge)
            return run

    run = _draft_run_for_charge(root, charge)
    root.db.session.add(run)
    root.db.session.flush()
    _ensure_run_input(root, run, charge)
    ensure_booth_session(root, run, charge)
    charge.run_id = run.id
    if (charge.status or "pending").strip() == "pending":
        update_charge_state(
            root,
            charge,
            "applied",
            history_entries=charge_history_entries(root, charge.id, limit=20),
            context={"source": "run_link"},
        )
    else:
        root.log_audit(
            "link_run",
            "extraction_charge",
            charge.id,
            details=root.json.dumps({"run_id": run.id, "source": "run_link_preserve_state", "status": charge.status}),
        )
    return run


def mobile_run_payload(root, run, charge) -> dict:
    lot = charge.lot
    booth_payload = booth_session_payload(root, run)
    timing_controls = run_timing_controls_payload(root, run)
    return {
        "id": run.id,
        "run_date": run.run_date.isoformat() if run.run_date else None,
        "reactor_number": int(run.reactor_number or 0) if run.reactor_number is not None else None,
        "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0),
        "run_type": run.run_type or "standard",
        "run_fill_started_at": display_local_datetime(run.run_fill_started_at),
        "run_fill_ended_at": display_local_datetime(run.run_fill_ended_at),
        "run_fill_duration_minutes": duration_minutes(run.run_fill_started_at, run.run_fill_ended_at),
        "biomass_blend_milled_pct": float(run.biomass_blend_milled_pct or 0) if run.biomass_blend_milled_pct is not None else None,
        "biomass_blend_unmilled_pct": float(run.biomass_blend_unmilled_pct or 0) if run.biomass_blend_unmilled_pct is not None else None,
        "flush_count": run.flush_count,
        "flush_total_weight_lbs": float(run.flush_total_weight_lbs or 0) if run.flush_total_weight_lbs is not None else None,
        "fill_count": run.fill_count,
        "fill_total_weight_lbs": float(run.fill_total_weight_lbs or 0) if run.fill_total_weight_lbs is not None else None,
        "stringer_basket_count": run.stringer_basket_count,
        "crc_blend": run.crc_blend,
        "mixer_started_at": display_local_datetime(run.mixer_started_at),
        "mixer_ended_at": display_local_datetime(run.mixer_ended_at),
        "mixer_duration_minutes": duration_minutes(run.mixer_started_at, run.mixer_ended_at),
        "flush_started_at": display_local_datetime(run.flush_started_at),
        "flush_ended_at": display_local_datetime(run.flush_ended_at),
        "flush_duration_minutes": duration_minutes(run.flush_started_at, run.flush_ended_at),
        "run_completed_at": display_local_datetime(run.run_completed_at),
        "progression": run_progression_payload(root, run),
        "booth": booth_payload,
        "timing_controls": timing_controls,
        "primary_solvent_charge_lbs": booth_payload["primary_solvent_charge_lbs"],
        "wet_hte_g": float(run.wet_hte_g or 0) if run.wet_hte_g is not None else None,
        "wet_thca_g": float(run.wet_thca_g or 0) if run.wet_thca_g is not None else None,
        "post_extraction_pathway": run.post_extraction_pathway or "",
        "post_extraction_pathway_options": [
            {"value": value, "label": label} for value, label in POST_EXTRACTION_PATHWAY_OPTIONS
        ],
        "post_extraction_started_at": display_local_datetime(run.post_extraction_started_at),
        "post_extraction_initial_outputs_recorded_at": display_local_datetime(run.post_extraction_initial_outputs_recorded_at),
        "post_extraction": post_extraction_progression_payload(run),
        "pot_pour_offgas_started_at": display_local_datetime(run.pot_pour_offgas_started_at),
        "pot_pour_offgas_completed_at": display_local_datetime(run.pot_pour_offgas_completed_at),
        "pot_pour_daily_stir_count": run.pot_pour_daily_stir_count,
        "pot_pour_centrifuged_at": display_local_datetime(run.pot_pour_centrifuged_at),
        "thca_oven_started_at": display_local_datetime(run.thca_oven_started_at),
        "thca_oven_completed_at": display_local_datetime(run.thca_oven_completed_at),
        "thca_milled_at": display_local_datetime(run.thca_milled_at),
        "thca_destination": run.thca_destination or "",
        "thca_destination_options": [{"value": value, "label": label} for value, label in THCA_DESTINATION_OPTIONS],
        "hte_offgas_started_at": display_local_datetime(run.hte_offgas_started_at),
        "hte_offgas_completed_at": display_local_datetime(run.hte_offgas_completed_at),
        "hte_clean_decision": run.hte_clean_decision or "",
        "hte_clean_decision_options": [{"value": value, "label": label} for value, label in HTE_CLEAN_DECISION_OPTIONS],
        "hte_filter_outcome": run.hte_filter_outcome or "",
        "hte_filter_outcome_options": [{"value": value, "label": label} for value, label in HTE_FILTER_OUTCOME_OPTIONS],
        "hte_prescott_processed_at": display_local_datetime(run.hte_prescott_processed_at),
        "hte_potency_disposition": run.hte_potency_disposition or "",
        "hte_potency_disposition_options": [{"value": value, "label": label} for value, label in HTE_POTENCY_DISPOSITION_OPTIONS],
        "hte_queue_destination": run.hte_queue_destination or "",
        "hte_queue_destination_options": [{"value": value, "label": label} for value, label in HTE_QUEUE_DESTINATION_OPTIONS],
        "downstream": downstream_state_payload(run),
        "notes": run.notes,
        "inherited": {
            "tracking_id": lot.tracking_id if lot else None,
            "supplier_name": lot.supplier_name if lot else None,
            "strain_name": lot.strain_name if lot else None,
            "source_summary": run.source_display,
            "charge_weight_lbs": float(charge.charged_weight_lbs or 0),
            "charged_at_label": display_charge_datetime_local(charge.charged_at),
        },
        "open_main_app_url": root.url_for("run_edit", run_id=run.id, return_to=root.url_for("floor_ops")) if getattr(run, "id", None) else root.url_for("run_new", return_to=root.url_for("floor_ops")),
    }


def draft_run_payload(root, charge) -> dict:
    return mobile_run_payload(root, _draft_run_for_charge(root, charge), charge)
