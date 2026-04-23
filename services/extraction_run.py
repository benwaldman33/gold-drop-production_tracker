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

EXTRACTION_RUN_DEFAULTS = {
    "extraction_default_biomass_blend_milled_pct": ("100", "Default milled biomass percentage for extraction run drafts"),
    "extraction_default_fill_count": ("1", "Default fill count for extraction run drafts"),
    "extraction_default_fill_total_weight_lbs": ("", "Default total fill weight (lbs) for extraction run drafts"),
    "extraction_default_flush_count": ("0", "Default flush count for extraction run drafts"),
    "extraction_default_flush_total_weight_lbs": ("", "Default total flush weight (lbs) for extraction run drafts"),
    "extraction_default_stringer_basket_count": ("0", "Default stringer basket count for extraction run drafts"),
    "extraction_default_crc_blend": ("", "Default CRC blend note for extraction run drafts"),
}

RUN_PROGRESSION = {
    "ready_to_start": {
        "label": "Ready to start",
        "description": "Record the start of the run before moving into mixer work.",
        "actions": [{"action_id": "start_run", "label": "Start Run"}],
    },
    "ready_to_mix": {
        "label": "Ready to mix",
        "description": "The run has started. Start the mixer when material is loaded.",
        "actions": [{"action_id": "start_mixer", "label": "Start Mixer"}],
    },
    "mixing": {
        "label": "Mixer running",
        "description": "Mixer timing is active. Stop the mixer when that step is done.",
        "actions": [{"action_id": "stop_mixer", "label": "Stop Mixer"}],
    },
    "ready_to_flush": {
        "label": "Ready to flush",
        "description": "Mixer timing is complete. Start the flush when the reactor is ready.",
        "actions": [{"action_id": "start_flush", "label": "Start Flush"}],
    },
    "flushing": {
        "label": "Flush running",
        "description": "Flush timing is active. Stop it when the flush is done.",
        "actions": [{"action_id": "stop_flush", "label": "Stop Flush"}],
    },
    "ready_to_complete": {
        "label": "Ready to complete",
        "description": "Core extraction steps are timed. Complete the run to close out the operator workflow.",
        "actions": [{"action_id": "mark_complete", "label": "Mark Run Complete"}],
    },
    "completed": {
        "label": "Completed",
        "description": "This run has been marked complete in the standalone execution workflow.",
        "actions": [],
    },
}

POST_EXTRACTION_PATHWAY_OPTIONS = [
    ("", "Not set"),
    ("pot_pour_100", "100 lb pot pour"),
    ("minor_run_200", "200 lb minor run"),
]

POST_EXTRACTION_PATHWAY_LABELS = {value: label for value, label in POST_EXTRACTION_PATHWAY_OPTIONS if value}


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


def _utc_now_localized() -> datetime:
    return datetime.now(app_display_zoneinfo()).astimezone(timezone.utc)


def run_progression_payload(run) -> dict:
    if run.run_completed_at:
        stage_key = "completed"
    elif run.flush_started_at and not run.flush_ended_at:
        stage_key = "flushing"
    elif run.flush_ended_at:
        stage_key = "ready_to_complete"
    elif run.mixer_started_at and not run.mixer_ended_at:
        stage_key = "mixing"
    elif run.mixer_ended_at:
        stage_key = "ready_to_flush"
    elif run.run_fill_started_at:
        stage_key = "ready_to_mix"
    else:
        stage_key = "ready_to_start"
    config = RUN_PROGRESSION[stage_key]
    return {
        "stage_key": stage_key,
        "stage_label": config["label"],
        "description": config["description"],
        "actions": list(config["actions"]),
        "completed_at": display_local_datetime(run.run_completed_at),
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


def apply_progression_action(run, action_id: str | None) -> None:
    action = (action_id or "").strip()
    if not action:
        return
    now = _utc_now_localized()
    if action == "start_run":
        if run.run_fill_started_at is None:
            run.run_fill_started_at = now
        return
    if action == "start_mixer":
        if run.run_fill_started_at is None:
            raise ValueError("Start the run before starting the mixer.")
        if run.mixer_started_at is None:
            run.mixer_started_at = now
        return
    if action == "stop_mixer":
        if run.mixer_started_at is None:
            raise ValueError("Start the mixer before stopping it.")
        run.mixer_ended_at = now
        return
    if action == "start_flush":
        if run.mixer_ended_at is None:
            raise ValueError("Stop the mixer before starting the flush.")
        if run.flush_started_at is None:
            run.flush_started_at = now
        return
    if action == "stop_flush":
        if run.flush_started_at is None:
            raise ValueError("Start the flush before stopping it.")
        run.flush_ended_at = now
        return
    if action == "mark_complete":
        if run.flush_ended_at is None:
            raise ValueError("Stop the flush before completing the run.")
        run.run_completed_at = now
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
            return run

    run = _draft_run_for_charge(root, charge)
    root.db.session.add(run)
    root.db.session.flush()
    _ensure_run_input(root, run, charge)
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
        "progression": run_progression_payload(run),
        "wet_hte_g": float(run.wet_hte_g or 0) if run.wet_hte_g is not None else None,
        "wet_thca_g": float(run.wet_thca_g or 0) if run.wet_thca_g is not None else None,
        "post_extraction_pathway": run.post_extraction_pathway or "",
        "post_extraction_pathway_options": [
            {"value": value, "label": label} for value, label in POST_EXTRACTION_PATHWAY_OPTIONS
        ],
        "post_extraction_started_at": display_local_datetime(run.post_extraction_started_at),
        "post_extraction_initial_outputs_recorded_at": display_local_datetime(run.post_extraction_initial_outputs_recorded_at),
        "post_extraction": post_extraction_progression_payload(run),
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
