from __future__ import annotations

from datetime import datetime, timezone

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

    if reactor_number not in {1, 2, 3}:
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
