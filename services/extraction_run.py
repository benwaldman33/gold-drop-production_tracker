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
    "extraction_default_flush_count": ("0", "Default flush count for extraction run drafts"),
    "extraction_default_stringer_basket_count": ("0", "Default stringer basket count for extraction run drafts"),
    "extraction_default_crc_blend": ("", "Default CRC blend note for extraction run drafts"),
}


def extraction_run_defaults(root) -> dict[str, float | int | str]:
    milled_pct = root.SystemSetting.get_float("extraction_default_biomass_blend_milled_pct", 100.0)
    milled_pct = max(0.0, min(100.0, float(milled_pct)))
    fill_count = max(0, int(root.SystemSetting.get_float("extraction_default_fill_count", 1) or 0))
    flush_count = max(0, int(root.SystemSetting.get_float("extraction_default_flush_count", 0) or 0))
    stringer_basket_count = max(0, int(root.SystemSetting.get_float("extraction_default_stringer_basket_count", 0) or 0))
    crc_blend = (root.SystemSetting.get("extraction_default_crc_blend", "") or "").strip()
    return {
        "biomass_blend_milled_pct": milled_pct,
        "biomass_blend_unmilled_pct": round(100.0 - milled_pct, 1),
        "fill_count": fill_count,
        "flush_count": flush_count,
        "stringer_basket_count": stringer_basket_count,
        "crc_blend": crc_blend,
    }


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
    milled_pct = _clamped_percent(payload.get("biomass_blend_milled_pct"), field="Milled blend %")
    unmilled_pct = _clamped_percent(payload.get("biomass_blend_unmilled_pct"), field="Unmilled blend %")
    if milled_pct is not None and unmilled_pct is not None and abs((milled_pct + unmilled_pct) - 100.0) > 0.6:
        raise ValueError("Milled and unmilled blend percentages must total 100.")

    run.run_fill_started_at = parse_local_datetime(payload.get("run_fill_started_at"))
    run.run_fill_ended_at = parse_local_datetime(payload.get("run_fill_ended_at"))
    run.biomass_blend_milled_pct = milled_pct
    run.biomass_blend_unmilled_pct = unmilled_pct
    run.flush_count = _opt_int(payload.get("flush_count"), field="Flush count")
    run.flush_total_weight_lbs = _opt_float(payload.get("flush_total_weight_lbs"), field="Flush total weight")
    run.fill_count = _opt_int(payload.get("fill_count"), field="Fill count")
    run.fill_total_weight_lbs = _opt_float(payload.get("fill_total_weight_lbs"), field="Fill total weight")
    run.stringer_basket_count = _opt_int(payload.get("stringer_basket_count"), field="Stringer basket count")
    run.crc_blend = (payload.get("crc_blend") or "").strip() or None
    run.mixer_started_at = parse_local_datetime(payload.get("mixer_started_at"))
    run.mixer_ended_at = parse_local_datetime(payload.get("mixer_ended_at"))
    run.flush_started_at = parse_local_datetime(payload.get("flush_started_at"))
    run.flush_ended_at = parse_local_datetime(payload.get("flush_ended_at"))
    run.notes = (payload.get("notes") or "").strip() or None


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
    run.run_fill_started_at = charge.charged_at
    run.biomass_blend_milled_pct = defaults["biomass_blend_milled_pct"]
    run.biomass_blend_unmilled_pct = defaults["biomass_blend_unmilled_pct"]
    run.fill_count = defaults["fill_count"]
    run.flush_count = defaults["flush_count"]
    run.stringer_basket_count = defaults["stringer_basket_count"]
    run.crc_blend = defaults["crc_blend"] or None
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
