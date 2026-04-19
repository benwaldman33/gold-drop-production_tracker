from __future__ import annotations

from datetime import datetime, timezone

REACTOR_LIFECYCLE_ORDER = ("in_reactor", "running", "completed", "cancelled")
REACTOR_LIFECYCLE_DEFAULTS = {
    "in_reactor": {"enabled": True, "required": False},
    "running": {"enabled": True, "required": False},
    "completed": {"enabled": True, "required": False},
    "cancelled": {"enabled": True, "required": False},
}
REACTOR_CHARGE_STATE_META = {
    "pending": {"label": "Charged / waiting", "badge": "badge-gold"},
    "in_reactor": {"label": "In reactor", "badge": "badge-gold"},
    "applied": {"label": "Run linked", "badge": "badge-green"},
    "running": {"label": "Running", "badge": "badge-green"},
    "completed": {"label": "Completed today", "badge": "badge-gray"},
    "cancelled": {"label": "Cancelled today", "badge": "badge-red"},
}

from gold_drop.list_state import app_display_zoneinfo


def default_charge_datetime_local(now_utc: datetime | None = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    return now.astimezone(app_display_zoneinfo()).strftime("%Y-%m-%dT%H:%M")


def display_charge_datetime_local(value: datetime | None) -> str:
    if value is None:
        return ""
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_display_zoneinfo()).strftime("%Y-%m-%d %H:%M")


def reactor_count(root) -> int:
    try:
        count = int(float(root.SystemSetting.get("num_reactors", "3") or 3))
    except (TypeError, ValueError):
        count = 3
    return max(1, min(12, count))


def charge_state_label(state: str | None) -> str:
    return REACTOR_CHARGE_STATE_META.get((state or "").strip(), REACTOR_CHARGE_STATE_META["pending"])["label"]


def charge_state_badge(state: str | None) -> str:
    return REACTOR_CHARGE_STATE_META.get((state or "").strip(), REACTOR_CHARGE_STATE_META["pending"])["badge"]


def reactor_lifecycle_settings(root) -> dict:
    states = {}
    for state_key, defaults in REACTOR_LIFECYCLE_DEFAULTS.items():
        enabled_raw = (root.SystemSetting.get(f"reactor_state_{state_key}_enabled", "1" if defaults["enabled"] else "0") or "0").strip().lower()
        required_raw = (root.SystemSetting.get(f"reactor_state_{state_key}_required", "1" if defaults["required"] else "0") or "0").strip().lower()
        states[state_key] = {
            "enabled": enabled_raw in ("1", "true", "yes", "on"),
            "required": required_raw in ("1", "true", "yes", "on"),
            "label": charge_state_label(state_key),
        }
    running_linked_raw = (root.SystemSetting.get("reactor_running_requires_linked_run", "1") or "1").strip().lower()
    show_history_raw = (root.SystemSetting.get("reactor_show_state_history", "1") or "1").strip().lower()
    return {
        "states": states,
        "running_requires_linked_run": running_linked_raw in ("1", "true", "yes", "on"),
        "show_history": show_history_raw in ("1", "true", "yes", "on"),
    }


def charge_history_entries(root, charge_id: str, *, limit: int = 8) -> list[dict]:
    logs = (
        root.AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=str(charge_id))
        .order_by(root.AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    entries = []
    for log in logs:
        try:
            payload = root.json.loads(log.details or "{}")
        except (TypeError, ValueError):
            payload = {}
        if log.action == "create":
            label = "Charge recorded"
        elif log.action == "state_change":
            label = f"State -> {charge_state_label(payload.get('to_state'))}"
        else:
            label = log.action.replace("_", " ").title()
        resolution = payload.get("cancel_resolution")
        if resolution:
            label = f"{label} ({resolution})"
        entries.append(
            {
                "label": label,
                "timestamp_label": display_charge_datetime_local(log.timestamp),
                "details": payload,
            }
        )
    return entries


def _charge_seen_state(charge, history_entries: list[dict], state_key: str) -> bool:
    current_status = (getattr(charge, "status", None) or "").strip()
    if current_status == state_key:
        return True
    for entry in history_entries:
        details = entry.get("details") or {}
        if details.get("to_state") == state_key:
            return True
    return False


def validate_charge_transition(root, charge, target_state: str, *, history_entries: list[dict] | None = None) -> None:
    settings = reactor_lifecycle_settings(root)
    state_settings = settings["states"]
    target = (target_state or "").strip()
    if target not in {"applied", *REACTOR_LIFECYCLE_ORDER}:
        raise ValueError("Choose a valid reactor state.")
    if target in state_settings and not state_settings[target]["enabled"]:
        raise ValueError(f"{charge_state_label(target)} is currently hidden in Settings.")
    history = history_entries if history_entries is not None else charge_history_entries(root, charge.id, limit=20)
    if target == "running" and settings["running_requires_linked_run"] and not charge.run_id:
        raise ValueError("Mark Running requires a linked run under the current Settings policy.")
    if target in {"running", "completed"} and state_settings["in_reactor"]["enabled"] and state_settings["in_reactor"]["required"]:
        if not _charge_seen_state(charge, history, "in_reactor"):
            raise ValueError("Mark In Reactor is required before this transition.")
    if target == "completed" and state_settings["running"]["enabled"] and state_settings["running"]["required"]:
        if not _charge_seen_state(charge, history, "running"):
            raise ValueError("Mark Running is required before completion.")


def update_charge_state(
    root,
    charge,
    target_state: str,
    *,
    history_entries: list[dict] | None = None,
    cancel_resolution: str | None = None,
    context: dict | None = None,
) -> None:
    validate_charge_transition(root, charge, target_state, history_entries=history_entries)
    previous_state = (charge.status or "pending").strip() or "pending"
    charge.status = (target_state or "").strip()
    payload = {
        "from_state": previous_state,
        "to_state": charge.status,
        "run_id": charge.run_id,
    }
    if cancel_resolution:
        payload["cancel_resolution"] = cancel_resolution
    if context:
        payload.update(context)
    root.log_audit("state_change", "extraction_charge", charge.id, details=root.json.dumps(payload))


def charge_visible_on_board(root, charge) -> bool:
    status = (charge.status or "pending").strip() or "pending"
    settings = reactor_lifecycle_settings(root)
    if status in settings["states"] and not settings["states"][status]["enabled"]:
        return False
    if status in {"completed", "cancelled"}:
        charged_at = charge.charged_at
        if charged_at is None:
            return False
        if charged_at.tzinfo is None:
            charged_at = charged_at.replace(tzinfo=timezone.utc)
        local_dt = charged_at.astimezone(app_display_zoneinfo())
        now_local = datetime.now(timezone.utc).astimezone(app_display_zoneinfo())
        return local_dt.date() == now_local.date()
    return status in {"pending", "in_reactor", "applied", "running"}


def parse_charge_datetime(raw_value: str | None) -> datetime:
    text = (raw_value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=app_display_zoneinfo()).astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError("Enter a valid charge date and time.")


def validate_chargeable_lot(root, lot) -> None:
    if lot is None or lot.deleted_at is not None:
        raise ValueError("Lot not found.")
    purchase = getattr(lot, "purchase", None)
    if purchase is None or purchase.deleted_at is not None:
        raise ValueError("Lot belongs to a deleted purchase.")
    if float(lot.remaining_weight_lbs or 0) <= 0:
        raise ValueError("Lot has no remaining inventory to charge.")
    if purchase.purchase_approved_at is None:
        raise ValueError("Lot cannot be charged until the purchase is approved.")
    if purchase.status not in root.INVENTORY_ON_HAND_PURCHASE_STATUSES:
        raise ValueError("Lot is not currently in an on-hand inventory state.")


def create_extraction_charge(
    root,
    *,
    lot,
    charged_weight_lbs: float,
    reactor_number: int,
    charged_at,
    source_mode: str,
    notes: str | None = None,
    weight_capture_id: str | None = None,
    lot_scan_event_id: str | None = None,
    slack_ingested_message_id: str | None = None,
):
    validate_chargeable_lot(root, lot)

    if charged_weight_lbs <= 0:
        raise ValueError("Charge weight must be greater than zero.")

    remaining = float(lot.remaining_weight_lbs or 0)
    if charged_weight_lbs > remaining + 1e-9:
        raise ValueError(f"Charge weight cannot exceed the lot's {remaining:.1f} lbs remaining.")

    if reactor_number not in set(range(1, reactor_count(root) + 1)):
        raise ValueError("Choose a valid reactor.")

    charge = root.ExtractionCharge(
        purchase_lot_id=lot.id,
        charged_weight_lbs=float(charged_weight_lbs),
        reactor_number=reactor_number,
        charged_at=charged_at,
        source_mode=(source_mode or "main_app").strip() or "main_app",
        status="pending",
        notes=notes or None,
        weight_capture_id=weight_capture_id or None,
        lot_scan_event_id=lot_scan_event_id or None,
        slack_ingested_message_id=slack_ingested_message_id or None,
        created_by=getattr(root.current_user, "id", None),
    )
    root.db.session.add(charge)
    root.db.session.flush()
    root.log_audit(
        "create",
        "extraction_charge",
        charge.id,
        details=root.json.dumps(
            {
                "purchase_lot_id": lot.id,
                "tracking_id": getattr(lot, "tracking_id", None),
                "charged_weight_lbs": float(charged_weight_lbs),
                "reactor_number": reactor_number,
                "source_mode": charge.source_mode,
                "charged_at": charge.charged_at.isoformat() if charge.charged_at else None,
            }
        ),
    )
    return charge


def build_charge_prefill_payload(root, lot, charge, *, scale_device_id: str | None = None) -> dict:
    local_charge_dt = charge.charged_at
    if local_charge_dt and local_charge_dt.tzinfo is None:
        local_charge_dt = local_charge_dt.replace(tzinfo=timezone.utc)
    local_charge_dt = local_charge_dt.astimezone(app_display_zoneinfo()) if local_charge_dt else None
    return {
        "lot_id": lot.id,
        "purchase_id": lot.purchase.id,
        "tracking_id": lot.tracking_id,
        "batch_id": lot.purchase.batch_id,
        "supplier_name": lot.supplier_name,
        "strain_name": lot.strain_name,
        "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
        "suggested_allocations": [{"lot_id": lot.id, "weight_lbs": float(charge.charged_weight_lbs or 0)}],
        "run_start_mode": "charge_recorded",
        "planned_weight_lbs": float(charge.charged_weight_lbs or 0),
        "scale_device_id": (scale_device_id or "").strip(),
        "charge_id": charge.id,
        "reactor_number": int(charge.reactor_number or 0) or None,
        "charged_at": charge.charged_at.isoformat() if charge.charged_at else None,
        "charged_at_label": display_charge_datetime_local(charge.charged_at),
        "charge_notes": charge.notes or "",
        "charge_source_mode": charge.source_mode,
        "charge_status": charge.status,
        "charge_run_date": local_charge_dt.date().isoformat() if local_charge_dt else None,
    }
