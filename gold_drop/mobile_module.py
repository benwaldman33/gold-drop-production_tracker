from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from flask import current_app, jsonify, request, url_for
from flask_login import current_user, login_user, logout_user

from models import AuditLog, PhotoAsset, Purchase, PurchaseLot, RunInput, Supplier, User, db
from services.api_site import build_meta
from services.purchase_helpers import (
    create_photo_asset,
    ensure_unique_batch_id,
    generate_batch_id,
    photo_asset_exists,
)
from services.lot_allocation import ensure_purchase_lot_tracking
from services.mobile_write_api import (
    audit_mobile_action,
    enforce_same_origin_for_write,
    mobile_capabilities,
    mobile_json,
    mobile_json_error,
    workflow_enabled,
    workflow_permissions,
)
from services.supplier_duplicates import supplier_duplicate_candidates
from services.extraction_charge import (
    build_charge_prefill_payload,
    charge_history_entries,
    charge_state_label,
    create_extraction_charge,
    default_charge_datetime_local,
    parse_charge_datetime,
    update_charge_state,
)
from services.extraction_run import apply_execution_payload, draft_run_payload, ensure_run_for_charge, mobile_run_payload
from gold_drop.floor_module import (
    BOARD_VIEW_OPTIONS,
    _build_active_reactor_board,
    _board_view_value,
    _build_floor_rollups,
    _build_reactor_charge_view,
    _build_reactor_history,
    _card_matches_board_view,
)
from gold_drop.uploads import save_uploads, allowed_image_filename


MOBILE_EDIT_LOCK_STATUSES = {"delivered", "cancelled", "complete"}


def _json_error(message: str, *, status_code: int, code: str):
    return mobile_json_error(message, status_code=status_code, code=code)


def _mobile_payload() -> dict[str, Any]:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {}
    for key in request.form.keys():
        values = request.form.getlist(key)
        if len(values) == 1:
            out[key] = values[0]
        elif values:
            out[key] = values
    return out


def _nested_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    raw = payload.get(key)
    if isinstance(raw, dict):
        return raw
    return {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: Any, field: str, *, allow_none: bool = True) -> float | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise ValueError(f"{field} is required.")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")


def _parse_date(value: Any, field: str, *, default_today: bool = False) -> date | None:
    if value is None or value == "":
        return date.today() if default_today else None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date.")


def _mobile_user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def _mobile_permissions(root, user: User) -> dict[str, bool]:
    return workflow_permissions(root, user)


def _mobile_opportunity_supplier_stub(purchase: Purchase) -> dict[str, Any] | None:
    supplier = purchase.supplier if purchase else None
    if not supplier:
        return None
    return {
        "id": supplier.id,
        "name": supplier.name,
    }


def _mobile_purchase_lot(purchase: Purchase) -> PurchaseLot | None:
    if not purchase:
        return None
    lots = purchase.lots.order_by(PurchaseLot.id.asc()).all() if hasattr(purchase.lots, "order_by") else list(purchase.lots or [])
    for lot in lots:
        if getattr(lot, "deleted_at", None) is None:
            return lot
    return None


def _mobile_photo_payload(photo: PhotoAsset) -> dict[str, Any]:
    return {
        "id": photo.id,
        "photo_context": photo.photo_context or "opportunity",
        "url": url_for("static", filename=photo.file_path),
        "title": photo.title,
        "uploaded_at": photo.uploaded_at.isoformat() if photo.uploaded_at else None,
    }


def _mobile_upload_limit_values() -> tuple[int, int]:
    per_request = int(current_app.config.get("MOBILE_UPLOAD_MAX_FILES_PER_REQUEST", 6))
    per_context_total = int(current_app.config.get("MOBILE_UPLOAD_MAX_FILES_PER_CONTEXT", 12))
    return max(1, per_request), max(1, per_context_total)


def _mobile_validate_photo_upload(purchase: Purchase, *, photo_context: str, files: list[Any]) -> None:
    per_request, per_context_total = _mobile_upload_limit_values()
    if len(files) > per_request:
        raise ValueError(f"You can upload at most {per_request} files at once.")
    existing_count = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
        PhotoAsset.photo_context == photo_context,
    ).count()
    if existing_count + len(files) > per_context_total:
        raise ValueError(f"This record can store at most {per_context_total} {photo_context} photos.")


def _mobile_purchase_editable(purchase: Purchase) -> bool:
    if purchase.deleted_at is not None:
        return False
    if purchase.status in MOBILE_EDIT_LOCK_STATUSES:
        return False
    return purchase.purchase_approved_at is None


def _mobile_delivery_allowed(purchase: Purchase) -> bool:
    if purchase.deleted_at is not None:
        return False
    if purchase.status in {"delivered", "cancelled", "complete"}:
        return False
    if purchase.purchase_approved_at is not None:
        return True
    return (purchase.status or "").strip() == "committed"


def _mobile_opportunity_status(purchase: Purchase) -> str:
    status = (purchase.status or "").strip().lower()
    if status in {"delivered", "cancelled", "complete", "committed"}:
        return status
    if purchase.purchase_approved_at is not None:
        return "approved"
    if status == "ordered":
        return "submitted"
    return status or "submitted"


def _mobile_purchase_summary(purchase: Purchase) -> dict[str, Any]:
    lot = _mobile_purchase_lot(purchase)
    active_photos = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
    ).order_by(PhotoAsset.uploaded_at.desc()).all()
    delivery_photo_count = sum(1 for photo in active_photos if (photo.photo_context or "opportunity") == "delivery")
    opportunity_photo_count = sum(1 for photo in active_photos if (photo.photo_context or "opportunity") == "opportunity")
    return {
        "id": purchase.id,
        "batch_id": purchase.batch_id,
        "status": _mobile_opportunity_status(purchase),
        "editable": _mobile_purchase_editable(purchase),
        "delivery_allowed": _mobile_delivery_allowed(purchase),
        "supplier": _mobile_opportunity_supplier_stub(purchase),
        "supplier_name": purchase.supplier_name,
        "strain_name": lot.strain_name if lot else None,
        "expected_weight_lbs": float(purchase.declared_weight_lbs or purchase.stated_weight_lbs or 0),
        "expected_potency_pct": float(purchase.stated_potency_pct or 0) if purchase.stated_potency_pct is not None else None,
        "offered_price_per_lb": float(purchase.declared_price_per_lb or 0) if purchase.declared_price_per_lb is not None else None,
        "availability_date": purchase.availability_date.isoformat() if purchase.availability_date else None,
        "submitted_at": purchase.created_at.isoformat() if purchase.created_at else None,
        "delivery_needed": purchase.purchase_approved_at is not None and _mobile_opportunity_status(purchase) != "delivered",
        "created_by_user_id": purchase.created_by_user_id,
        "photo_count": len(active_photos),
        "opportunity_photo_count": opportunity_photo_count,
        "delivery_photo_count": delivery_photo_count,
    }


def _mobile_purchase_detail(purchase: Purchase) -> dict[str, Any]:
    lot = _mobile_purchase_lot(purchase)
    photos = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
    ).order_by(PhotoAsset.uploaded_at.asc()).all()
    return {
        **_mobile_purchase_summary(purchase),
        "purchase_date": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
        "delivery_date": purchase.delivery_date.isoformat() if purchase.delivery_date else None,
        "actual_weight_lbs": float(purchase.actual_weight_lbs or 0) if purchase.actual_weight_lbs is not None else None,
        "testing_status": purchase.testing_status,
        "testing_notes": purchase.testing_notes,
        "testing_timing": purchase.testing_timing,
        "delivery_notes": purchase.delivery_notes,
        "clean_or_dirty": purchase.clean_or_dirty,
        "notes": purchase.notes,
        "approval": {
            "approved_at": purchase.purchase_approved_at.isoformat() if purchase.purchase_approved_at else None,
            "approved_by_user_id": purchase.purchase_approved_by_user_id,
            "approved_by_name": purchase.purchase_approved_by.display_name if purchase.purchase_approved_by else None,
        },
        "delivery": {
            "delivered_weight_lbs": float(purchase.actual_weight_lbs or 0) if purchase.actual_weight_lbs is not None else None,
            "delivery_date": purchase.delivery_date.isoformat() if purchase.delivery_date else None,
            "testing_status": purchase.testing_status,
            "actual_potency_pct": float(purchase.tested_potency_pct or 0) if purchase.tested_potency_pct is not None else None,
            "clean_or_dirty": purchase.clean_or_dirty,
            "delivery_notes": purchase.delivery_notes,
            "delivered_by_name": purchase.delivery_recorded_by.display_name if purchase.delivery_recorded_by else None,
        } if purchase.status == "delivered" or purchase.delivery_date else None,
        "lots": [
            {
                "id": lot_obj.id,
                "tracking_id": lot_obj.tracking_id,
                "strain_name": lot_obj.strain_name,
                "weight_lbs": float(lot_obj.weight_lbs or 0),
                "remaining_weight_lbs": float(lot_obj.remaining_weight_lbs or 0),
                "potency_pct": float(lot_obj.potency_pct or 0) if lot_obj.potency_pct is not None else None,
                "floor_state": lot_obj.floor_state,
                "location": lot_obj.location,
            }
            for lot_obj in purchase.lots.order_by(PurchaseLot.id.asc()).all()
            if getattr(lot_obj, "deleted_at", None) is None
        ],
        "photos": [_mobile_photo_payload(photo) for photo in photos],
    }


def _mobile_receiving_summary(root, purchase: Purchase) -> dict[str, Any]:
    detail = _mobile_purchase_detail(purchase)
    lots = detail.get("lots") or []
    primary_lot = lots[0] if lots else None
    receiving_editable, receiving_locked_reason = _mobile_receiving_edit_state(root, purchase)
    last_receiving_edit = _mobile_last_receiving_edit(purchase)
    if _mobile_delivery_allowed(purchase):
        queue_state = "ready"
    elif receiving_editable:
        queue_state = "received"
    else:
        queue_state = "locked"
    detail["receiving"] = {
        "queue_state": queue_state,
        "location": (primary_lot or {}).get("location"),
        "floor_state": (primary_lot or {}).get("floor_state"),
        "lot_count": len(lots),
        "photo_count": detail.get("delivery_photo_count", 0),
        "receiving_editable": receiving_editable,
        "locked_reason": receiving_locked_reason,
        "last_receiving_edit_at": last_receiving_edit["at"],
        "last_receiving_edit_by": last_receiving_edit["by"],
    }
    return detail


def _mobile_supplier_duplicate_candidates(root, supplier_name: str, *, limit: int = 5) -> list[dict[str, Any]]:
    return supplier_duplicate_candidates(root, supplier_name, limit=limit)


def _mobile_receiving_query(root):
    return root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.or_(
            root.Purchase.purchase_approved_at.is_not(None),
            root.Purchase.status.in_(("committed", "delivered")),
        ),
    )


def _mobile_extraction_chargeable_lots_query(root):
    return (
        root.PurchaseLot.query.join(root.Purchase)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.Purchase.purchase_approved_at.is_not(None),
            root.Purchase.status.in_(tuple(root.INVENTORY_ON_HAND_PURCHASE_STATUSES)),
        )
    )


def _mobile_extraction_lot_payload(root, lot: PurchaseLot) -> dict[str, Any]:
    testing_status = (lot.purchase.testing_status or "pending") if lot.purchase else "pending"
    floor_state = (lot.floor_state or "inventory").strip() or "inventory"
    ready = bool(lot.milled and testing_status in {"completed", "not_needed"} and floor_state == "reactor_staging")
    return {
        "id": lot.id,
        "tracking_id": lot.tracking_id,
        "purchase_id": lot.purchase.id if lot.purchase else None,
        "batch_id": lot.purchase.batch_id if lot.purchase else None,
        "supplier_name": lot.supplier_name,
        "strain_name": lot.strain_name,
        "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
        "weight_lbs": float(lot.weight_lbs or 0),
        "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
        "testing_status": testing_status,
        "clean_or_dirty": lot.purchase.clean_or_dirty if lot.purchase else None,
        "floor_state": floor_state,
        "location": lot.location,
        "milled": bool(lot.milled),
        "ready_for_charge": ready,
        "recommended_weight_lbs": float(lot.remaining_weight_lbs or 0),
        "charge_defaults": {
            "charged_weight_lbs": f"{float(lot.remaining_weight_lbs or 0):.1f}",
            "reactor_number": None,
            "charged_at": default_charge_datetime_local(),
        },
        "warnings": [
            warning
            for warning in (
                None if testing_status in {"completed", "not_needed"} else "Testing is not marked complete or waived.",
                None if lot.milled else "Lot prep is still marked not milled.",
                None if floor_state == "reactor_staging" else "Lot is not currently marked in reactor staging.",
            )
            if warning
        ],
    }


def _mobile_extraction_charge_payload(root, charge) -> dict[str, Any]:
    history = charge_history_entries(root, charge.id, limit=6)
    lot = charge.lot
    return {
        "id": charge.id,
        "status": (charge.status or "pending").strip() or "pending",
        "state_label": charge_state_label(charge.status),
        "reactor_number": int(charge.reactor_number or 0) if charge.reactor_number is not None else None,
        "charged_weight_lbs": float(charge.charged_weight_lbs or 0),
        "charged_at": charge.charged_at.isoformat() if charge.charged_at else None,
        "charged_at_label": lot and build_charge_prefill_payload(root, lot, charge).get("charged_at_label") or None,
        "source_mode": charge.source_mode,
        "notes": charge.notes,
        "run_id": charge.run_id,
        "tracking_id": lot.tracking_id if lot else None,
        "supplier_name": lot.supplier_name if lot else None,
        "strain_name": lot.strain_name if lot else None,
        "history": history,
    }


def _mobile_extraction_run_response(root, charge, run) -> dict[str, Any]:
    lot = charge.lot
    return {
        "charge": _mobile_extraction_charge_payload(root, charge),
        "lot": _mobile_extraction_lot_payload(root, lot) if lot is not None else None,
        "run": mobile_run_payload(root, run, charge),
    }


def _mobile_extraction_board_payload(root) -> dict[str, Any]:
    floor_rollups = _build_floor_rollups(root)
    active_reactor_board = _build_active_reactor_board(root)
    reactor_queue = _build_reactor_charge_view(root)
    board_view = _board_view_value(root)
    filtered_cards = [card for card in active_reactor_board["cards"] if _card_matches_board_view(card, board_view)]
    reactor_history = _build_reactor_history(root, active_reactor_board["cards"])
    return {
        "summary": {
            "open_lot_count": _mobile_extraction_chargeable_lots_query(root).count(),
            "ready_count": floor_rollups["ready_count"],
            "ready_weight_lbs": float(floor_rollups["ready_weight_lbs"] or 0),
            "pending_prep_count": floor_rollups["pending_prep_count"],
            "pending_testing_count": floor_rollups["pending_testing_count"],
            "pending_charge_count": reactor_queue["pending_count"],
            "pending_charge_weight_lbs": float(reactor_queue["pending_weight_lbs"] or 0),
            "active_reactor_count": active_reactor_board["active_count"],
            "reactor_count": active_reactor_board["reactor_count"],
        },
        "board_view": board_view,
        "board_view_options": [{"value": value, "label": label} for value, label in BOARD_VIEW_OPTIONS],
        "reactor_cards": filtered_cards,
        "pending_cards": reactor_queue["pending_cards"],
        "applied_cards": reactor_queue["applied_cards"],
        "reactor_history": reactor_history,
        "floor_state_cards": floor_rollups["state_cards"],
    }


def _mobile_purchase_has_downstream_usage(root, purchase: Purchase) -> bool:
    return root.RunInput.query.join(
        root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
    ).filter(
        root.PurchaseLot.purchase_id == purchase.id,
        root.PurchaseLot.deleted_at.is_(None),
    ).count() > 0


def _mobile_last_receiving_edit(purchase: Purchase) -> dict[str, Any]:
    audit_row = AuditLog.query.filter(
        AuditLog.entity_type == "purchase",
        AuditLog.entity_id == purchase.id,
        AuditLog.action == "receive_edit",
    ).order_by(AuditLog.timestamp.desc()).first()
    return {
        "at": audit_row.timestamp.isoformat() if audit_row and audit_row.timestamp else None,
        "by": audit_row.user.display_name if audit_row and audit_row.user else None,
    }


def _mobile_receiving_edit_state(root, purchase: Purchase) -> tuple[bool, str | None]:
    if purchase.deleted_at is not None:
        return False, "Receiving record is deleted."
    status = (purchase.status or "").strip().lower()
    if status in {"cancelled", "complete"}:
        return False, "Receiving is locked for closed records."
    if _mobile_purchase_has_downstream_usage(root, purchase):
        return False, "Locked after downstream processing started."
    if _mobile_delivery_allowed(purchase):
        return True, None
    if status == "delivered" or purchase.delivery_date is not None:
        return True, None
    return False, "Receiving is not available for this record yet."


def _mobile_apply_delivery(root, purchase: Purchase, payload: dict[str, Any], *, actor: User, record_delivery_actor: bool = True) -> None:
    delivered_weight = _parse_float(payload.get("delivered_weight_lbs"), "Delivered weight lbs", allow_none=False)
    if delivered_weight is None or delivered_weight <= 0:
        raise ValueError("Delivered weight lbs must be greater than 0.")
    delivery_date = _parse_date(payload.get("delivery_date"), "Delivery date", default_today=True)
    if delivery_date is None:
        raise ValueError("Delivery date is required.")

    purchase.delivery_date = delivery_date
    purchase.actual_weight_lbs = float(delivered_weight)
    if "testing_status" in payload:
        purchase.testing_status = (payload.get("testing_status") or "").strip() or None
    if "actual_potency_pct" in payload:
        purchase.tested_potency_pct = _parse_float(payload.get("actual_potency_pct"), "Actual potency pct")
    if "clean_or_dirty" in payload:
        purchase.clean_or_dirty = (payload.get("clean_or_dirty") or "").strip() or None
    purchase.delivery_notes = (payload.get("delivery_notes") or "").strip() or None
    purchase.status = "delivered"
    if record_delivery_actor or not purchase.delivery_recorded_by_user_id:
        purchase.delivery_recorded_by_user_id = actor.id

    lot = _mobile_purchase_lot(purchase)
    if lot is None:
        lot = root.PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Opportunity total",
            weight_lbs=float(delivered_weight),
            remaining_weight_lbs=float(delivered_weight),
            potency_pct=purchase.tested_potency_pct or purchase.stated_potency_pct,
        )
        root.db.session.add(lot)
        root.db.session.flush()
    consumed = max(0.0, float(lot.weight_lbs or 0) - float(lot.remaining_weight_lbs or 0))
    lot.weight_lbs = float(delivered_weight)
    lot.remaining_weight_lbs = max(0.0, float(delivered_weight) - consumed)
    if purchase.tested_potency_pct is not None:
        lot.potency_pct = purchase.tested_potency_pct
    elif purchase.stated_potency_pct is not None:
        lot.potency_pct = purchase.stated_potency_pct
    if "location" in payload:
        lot.location = (payload.get("location") or "").strip() or None
    if "floor_state" in payload:
        lot.floor_state = (payload.get("floor_state") or "").strip() or lot.floor_state
    if "lot_notes" in payload:
        lot.notes = (payload.get("lot_notes") or "").strip() or None
    ensure_purchase_lot_tracking(purchase)

    if purchase.price_per_lb is not None:
        purchase.total_cost = float(delivered_weight) * float(purchase.price_per_lb)


def _mobile_receiving_edit_changes(purchase: Purchase, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lot = _mobile_purchase_lot(purchase)
    before = {
        "delivered_weight_lbs": float(purchase.actual_weight_lbs) if purchase.actual_weight_lbs is not None else None,
        "delivery_date": purchase.delivery_date.isoformat() if purchase.delivery_date else None,
        "testing_status": purchase.testing_status,
        "actual_potency_pct": float(purchase.tested_potency_pct) if purchase.tested_potency_pct is not None else None,
        "clean_or_dirty": purchase.clean_or_dirty,
        "delivery_notes": purchase.delivery_notes,
        "location": lot.location if lot else None,
        "floor_state": lot.floor_state if lot else None,
        "lot_notes": lot.notes if lot else None,
    }
    after = {
        "delivered_weight_lbs": _parse_float(payload.get("delivered_weight_lbs"), "Delivered weight lbs", allow_none=False),
        "delivery_date": (_parse_date(payload.get("delivery_date"), "Delivery date", default_today=True) or date.today()).isoformat(),
        "testing_status": (payload.get("testing_status") or "").strip() or None,
        "actual_potency_pct": _parse_float(payload.get("actual_potency_pct"), "Actual potency pct"),
        "clean_or_dirty": (payload.get("clean_or_dirty") or "").strip() or None,
        "delivery_notes": (payload.get("delivery_notes") or "").strip() or None,
        "location": (payload.get("location") or "").strip() or None,
        "floor_state": (payload.get("floor_state") or "").strip() or None,
        "lot_notes": (payload.get("lot_notes") or "").strip() or None,
    }
    changes: dict[str, dict[str, Any]] = {}
    for key, old_value in before.items():
        new_value = after[key]
        if old_value != new_value:
            changes[key] = {"old": old_value, "new": new_value}
    return changes


def _resolve_mobile_supplier(root, payload: dict[str, Any]) -> tuple[Supplier | None, dict[str, Any] | None]:
    supplier_id = (payload.get("supplier_id") or "").strip()
    if supplier_id:
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        contact_name = (payload.get("new_supplier_contact_name") or payload.get("contact_name") or "").strip()
        contact_phone = (payload.get("new_supplier_phone") or payload.get("phone") or "").strip()
        contact_email = (payload.get("new_supplier_email") or payload.get("email") or "").strip()
        location = (payload.get("new_supplier_location") or payload.get("location") or "").strip()
        if contact_name and not (supplier.contact_name or "").strip():
            supplier.contact_name = contact_name
        if contact_phone and not (supplier.contact_phone or "").strip():
            supplier.contact_phone = contact_phone
        if contact_email and not (supplier.contact_email or "").strip():
            supplier.contact_email = contact_email
        if location and not (supplier.location or "").strip():
            supplier.location = location
        return supplier, None

    new_supplier = _nested_dict(payload, "new_supplier")
    new_name = (
        new_supplier.get("name")
        if new_supplier
        else payload.get("new_supplier_name") or payload.get("name") or ""
    ).strip()
    if not new_name:
        raise ValueError("Supplier is required.")

    confirm = _truthy(payload.get("confirm_new_supplier"))
    duplicate_candidates = _mobile_supplier_duplicate_candidates(root, new_name)
    if duplicate_candidates and not confirm:
        return None, {
            "requires_confirmation": True,
            "duplicate_candidates": duplicate_candidates,
        }

    supplier = root.Supplier(
        name=new_name,
        contact_name=((new_supplier.get("contact_name") if new_supplier else payload.get("new_supplier_contact_name") or payload.get("contact_name")) or "").strip() or None,
        contact_phone=((new_supplier.get("phone") if new_supplier else payload.get("new_supplier_phone") or payload.get("phone")) or "").strip() or None,
        contact_email=((new_supplier.get("email") if new_supplier else payload.get("new_supplier_email") or payload.get("email")) or "").strip() or None,
        location=((new_supplier.get("location") if new_supplier else payload.get("new_supplier_location") or payload.get("location")) or "").strip() or None,
        notes=((new_supplier.get("notes") if new_supplier else payload.get("new_supplier_notes") or payload.get("notes")) or "").strip() or None,
        is_active=True,
    )
    root.db.session.add(supplier)
    root.db.session.flush()
    return supplier, None


def _require_mobile_user():
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    return None


def _require_mobile_writer(root):
    auth_error = _require_mobile_user()
    if auth_error:
        return auth_error
    origin_error = enforce_same_origin_for_write(root)
    if origin_error:
        return origin_error
    if not current_user.can_edit_purchases:
        return _json_error("Purchase edit access required.", status_code=403, code="forbidden")
    return None


def _require_mobile_workflow(root, workflow: str):
    writer_error = _require_mobile_writer(root)
    if writer_error:
        return writer_error
    if not workflow_enabled(root, workflow):
        return _json_error("This standalone workflow is disabled for the site.", status_code=403, code="workflow_disabled")
    permissions = _mobile_permissions(root, current_user)
    if workflow == "buying" and not permissions["can_create_opportunity"]:
        return _json_error("Buying workflow access required.", status_code=403, code="forbidden")
    if workflow == "receiving" and not permissions["can_receive_intake"]:
        return _json_error("Receiving workflow access required.", status_code=403, code="forbidden")
    if workflow == "extraction" and not permissions["can_extract_lab"]:
        return _json_error("Extraction workflow access required.", status_code=403, code="forbidden")
    return None


def register_routes(app, root):
    def mobile_auth_login():
        return mobile_auth_login_view(root)

    def mobile_auth_logout():
        return mobile_auth_logout_view(root)

    def mobile_auth_me():
        return mobile_auth_me_view(root)

    def mobile_capabilities_view_func():
        return mobile_capabilities_view(root)

    def mobile_opportunities_mine():
        return mobile_opportunities_mine_view(root)

    def mobile_opportunity_detail(opportunity_id):
        return mobile_opportunity_detail_view(root, opportunity_id)

    def mobile_opportunity_photos(opportunity_id):
        return mobile_opportunity_photos_view(root, opportunity_id)

    def mobile_supplier_create():
        return mobile_supplier_create_view(root)

    def mobile_suppliers():
        return mobile_suppliers_view(root)

    def mobile_supplier_detail(supplier_id):
        return mobile_supplier_detail_view(root, supplier_id)

    def mobile_receiving_queue():
        return mobile_receiving_queue_view(root)

    def mobile_receiving_detail(opportunity_id):
        return mobile_receiving_detail_view(root, opportunity_id)

    def mobile_receiving_update(opportunity_id):
        return mobile_receiving_update_view(root, opportunity_id)

    def mobile_receiving_receive(opportunity_id):
        return mobile_receiving_receive_view(root, opportunity_id)

    def mobile_receiving_photos(opportunity_id):
        return mobile_receiving_photos_view(root, opportunity_id)

    def mobile_extraction_board():
        return mobile_extraction_board_view(root)

    def mobile_extraction_lots():
        return mobile_extraction_lots_view(root)

    def mobile_extraction_lot_detail(lot_id):
        return mobile_extraction_lot_detail_view(root, lot_id)

    def mobile_extraction_lookup(tracking_id):
        return mobile_extraction_lookup_view(root, tracking_id)

    def mobile_extraction_charge(lot_id):
        return mobile_extraction_charge_view(root, lot_id)

    def mobile_extraction_transition(charge_id):
        return mobile_extraction_transition_view(root, charge_id)

    def mobile_extraction_run(charge_id):
        return mobile_extraction_run_view(root, charge_id)

    def mobile_opportunity_create():
        return mobile_opportunity_create_view(root)

    def mobile_opportunity_update(opportunity_id):
        return mobile_opportunity_update_view(root, opportunity_id)

    def mobile_opportunity_delivery(opportunity_id):
        return mobile_opportunity_delivery_view(root, opportunity_id)

    app.add_url_rule("/api/mobile/v1/auth/login", endpoint="mobile_auth_login", view_func=mobile_auth_login, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/auth/logout", endpoint="mobile_auth_logout", view_func=mobile_auth_logout, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/auth/me", endpoint="mobile_auth_me", view_func=mobile_auth_me)
    app.add_url_rule("/api/mobile/v1/capabilities", endpoint="mobile_capabilities", view_func=mobile_capabilities_view_func)
    app.add_url_rule("/api/mobile/v1/opportunities", endpoint="mobile_opportunity_create", view_func=mobile_opportunity_create, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/opportunities/mine", endpoint="mobile_opportunities_mine", view_func=mobile_opportunities_mine)
    app.add_url_rule("/api/mobile/v1/opportunities/<opportunity_id>", endpoint="mobile_opportunity_detail", view_func=mobile_opportunity_detail, methods=["GET", "PATCH"])
    app.add_url_rule("/api/mobile/v1/opportunities/<opportunity_id>/delivery", endpoint="mobile_opportunity_delivery", view_func=mobile_opportunity_delivery, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/opportunities/<opportunity_id>/photos", endpoint="mobile_opportunity_photos", view_func=mobile_opportunity_photos, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/suppliers", endpoint="mobile_suppliers", view_func=mobile_suppliers, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/suppliers", endpoint="mobile_supplier_create", view_func=mobile_supplier_create, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/suppliers/<supplier_id>", endpoint="mobile_supplier_detail", view_func=mobile_supplier_detail, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/receiving/queue", endpoint="mobile_receiving_queue", view_func=mobile_receiving_queue, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/receiving/queue/<opportunity_id>", endpoint="mobile_receiving_detail", view_func=mobile_receiving_detail, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/receiving/queue/<opportunity_id>", endpoint="mobile_receiving_update", view_func=mobile_receiving_update, methods=["PATCH"])
    app.add_url_rule("/api/mobile/v1/receiving/queue/<opportunity_id>/receive", endpoint="mobile_receiving_receive", view_func=mobile_receiving_receive, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/receiving/queue/<opportunity_id>/photos", endpoint="mobile_receiving_photos", view_func=mobile_receiving_photos, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/extraction/board", endpoint="mobile_extraction_board", view_func=mobile_extraction_board, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/extraction/lots", endpoint="mobile_extraction_lots", view_func=mobile_extraction_lots, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/extraction/lots/<lot_id>", endpoint="mobile_extraction_lot_detail", view_func=mobile_extraction_lot_detail, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/extraction/lookup/<tracking_id>", endpoint="mobile_extraction_lookup", view_func=mobile_extraction_lookup, methods=["GET"])
    app.add_url_rule("/api/mobile/v1/extraction/lots/<lot_id>/charge", endpoint="mobile_extraction_charge", view_func=mobile_extraction_charge, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/extraction/charges/<charge_id>/transition", endpoint="mobile_extraction_transition", view_func=mobile_extraction_transition, methods=["POST"])
    app.add_url_rule("/api/mobile/v1/extraction/charges/<charge_id>/run", endpoint="mobile_extraction_run", view_func=mobile_extraction_run, methods=["GET", "POST"])


def _mobile_supplier_payload(supplier: Supplier) -> dict[str, Any]:
    if supplier is None:
        return {}
    opportunity_count = Purchase.query.filter(
        Purchase.deleted_at.is_(None),
        Purchase.supplier_id == supplier.id,
        Purchase.created_by_user_id == current_user.id,
    ).count()
    open_count = Purchase.query.filter(
        Purchase.deleted_at.is_(None),
        Purchase.supplier_id == supplier.id,
        Purchase.created_by_user_id == current_user.id,
        Purchase.purchase_approved_at.is_not(None),
        Purchase.status != "delivered",
    ).count()
    return {
        "id": supplier.id,
        "name": supplier.name,
        "contact_name": supplier.contact_name,
        "phone": supplier.contact_phone,
        "email": supplier.contact_email,
        "location": supplier.location,
        "notes": supplier.notes,
        "is_active": bool(supplier.is_active),
        "opportunity_count": opportunity_count,
        "open_count": open_count,
    }


def mobile_auth_login_view(root):
    origin_error = enforce_same_origin_for_write(root)
    if origin_error:
        return origin_error
    payload = _mobile_payload()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return _json_error("Username and password are required.", status_code=400, code="bad_request")
    user = root.User.query.filter(root.func.lower(root.User.username) == username.lower()).first()
    if not user or not user.check_password(password) or not getattr(user, "is_active_user", True):
        return _json_error("Invalid username or password.", status_code=401, code="unauthorized")
    login_user(user)
    root.session.permanent = True
    site_meta = build_meta()
    return jsonify({
        "meta": site_meta,
        "data": {
            "authenticated": True,
            "user": _mobile_user_payload(user),
            "site": {
                "site_code": site_meta["site_code"],
                "site_name": site_meta["site_name"],
                "site_timezone": site_meta["site_timezone"],
            },
            "permissions": _mobile_permissions(root, user),
            "capabilities": mobile_capabilities(root, user),
        },
    })


def mobile_auth_logout_view(root):
    origin_error = enforce_same_origin_for_write(root)
    if origin_error:
        return origin_error
    logout_user()
    return jsonify({"meta": build_meta(), "data": {"ok": True}})


def mobile_auth_me_view(root):
    auth_error = _require_mobile_user()
    if auth_error:
        return auth_error
    user = current_user
    site_meta = build_meta()
    return jsonify({
        "meta": site_meta,
        "data": {
            "authenticated": True,
            "user": _mobile_user_payload(user),
            "site": {
                "site_code": site_meta["site_code"],
                "site_name": site_meta["site_name"],
                "site_timezone": site_meta["site_timezone"],
            },
            "permissions": _mobile_permissions(root, user),
            "capabilities": mobile_capabilities(root, user),
        },
    })


def mobile_capabilities_view(root):
    auth_error = _require_mobile_user()
    if auth_error:
        return auth_error
    return mobile_json(mobile_capabilities(root, current_user))


def mobile_opportunities_mine_view(root):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    status_filter = (request.args.get("status") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit") or 25), 100))
    except ValueError:
        limit = 25
    try:
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        offset = 0
    query = root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.created_by_user_id == current_user.id,
    )
    if status_filter:
        query = query.filter(root.Purchase.status == status_filter)
    total = query.count()
    rows = query.order_by(root.Purchase.updated_at.desc().nullslast(), root.Purchase.created_at.desc().nullslast()).offset(offset).limit(limit).all()
    return jsonify({
        "meta": build_meta(count=total, limit=limit, offset=offset),
        "data": [_mobile_purchase_summary(purchase) for purchase in rows],
    })


def mobile_receiving_queue_view(root):
    write_error = _require_mobile_workflow(root, "receiving")
    if write_error:
        return write_error
    status_filter = (request.args.get("status") or "ready").strip().lower()
    supplier_id = (request.args.get("supplier_id") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit") or 25), 100))
    except ValueError:
        limit = 25
    try:
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        offset = 0

    query = _mobile_receiving_query(root)
    if supplier_id:
        query = query.filter(root.Purchase.supplier_id == supplier_id)
    if status_filter == "ready":
        query = query.filter(root.Purchase.status != "delivered")
    elif status_filter:
        if status_filter == "approved":
            query = query.filter(
                root.Purchase.purchase_approved_at.is_not(None),
                root.Purchase.status != "delivered",
            )
        else:
            query = query.filter(root.func.lower(root.Purchase.status) == status_filter)
    total = query.count()
    rows = query.order_by(
        root.Purchase.delivery_date.asc().nullslast(),
        root.Purchase.purchase_date.asc().nullslast(),
        root.Purchase.created_at.asc().nullslast(),
    ).offset(offset).limit(limit).all()
    return jsonify({
        "meta": build_meta(count=total, limit=limit, offset=offset, extra={"workflow": "receiving", "status_filter": status_filter}),
        "data": [_mobile_receiving_summary(root, purchase) for purchase in rows],
    })


def mobile_receiving_detail_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "receiving")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Receiving item not found.", status_code=404, code="not_found")
    if purchase.purchase_approved_at is None and purchase.status not in {"committed", "delivered"}:
        return _json_error("Receiving item not found.", status_code=404, code="not_found")
    return jsonify({"meta": build_meta(extra={"workflow": "receiving"}), "data": _mobile_receiving_summary(root, purchase)})


def mobile_receiving_update_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "receiving")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Receiving item not found.", status_code=404, code="not_found")
    receiving_editable, locked_reason = _mobile_receiving_edit_state(root, purchase)
    if not receiving_editable:
        return _json_error(locked_reason or "Receiving is locked for this record.", status_code=409, code="receiving_locked")

    payload = _mobile_payload()
    payload.setdefault("floor_state", _mobile_purchase_lot(purchase).floor_state if _mobile_purchase_lot(purchase) else "receiving")
    try:
        changes = _mobile_receiving_edit_changes(purchase, payload)
        _mobile_apply_delivery(root, purchase, payload, actor=current_user, record_delivery_actor=False)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")

    audit_mobile_action(
        root,
        action="receive_edit",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="receiving",
        details={
            "changed_fields": sorted(changes.keys()),
            "changes": changes,
        },
        user_id=current_user.id,
    )
    root.db.session.commit()
    return jsonify({"meta": build_meta(extra={"workflow": "receiving"}), "data": {"receiving": _mobile_receiving_summary(root, purchase)}})


def mobile_opportunity_detail_view(root, opportunity_id: str):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if purchase.created_by_user_id != current_user.id and not current_user.is_super_admin:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if request.method == "PATCH":
        return mobile_opportunity_update_view(root, opportunity_id)
    return jsonify({"meta": build_meta(), "data": _mobile_purchase_detail(purchase)})


def mobile_supplier_create_view(root):
    write_error = _require_mobile_workflow(root, "buying")
    if write_error:
        return write_error
    payload = _mobile_payload()
    try:
        supplier, warning = _resolve_mobile_supplier(root, payload)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")
    if warning:
        return jsonify({"meta": build_meta(), "data": warning})
    audit_mobile_action(root, action="create", entity_type="supplier", entity_id=supplier.id, workflow="buying", details={"name": supplier.name}, user_id=current_user.id)
    root.db.session.commit()
    return jsonify({"meta": build_meta(), "data": {"supplier": {"id": supplier.id, "name": supplier.name}}}), 201


def mobile_suppliers_view(root):
    auth_error = _require_mobile_user()
    if auth_error:
        return auth_error
    query_text = (request.args.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit") or 25), 100))
    except ValueError:
        limit = 25
    try:
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        offset = 0
    query = root.Supplier.query.filter(
        root.Supplier.is_active.is_(True),
        root.Supplier.merged_into_supplier_id.is_(None),
    )
    if query_text:
        query = query.filter(root.Supplier.name.ilike(f"%{query_text}%"))
    query = query.order_by(root.Supplier.name.asc(), root.Supplier.id.asc())
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    return jsonify({
        "meta": build_meta(count=total, limit=limit, offset=offset),
        "data": [_mobile_supplier_payload(supplier) for supplier in rows],
    })


def mobile_supplier_detail_view(root, supplier_id: str):
    auth_error = _require_mobile_user()
    if auth_error:
        return auth_error
    supplier = root.db.session.get(root.Supplier, supplier_id)
    if not supplier or not bool(supplier.is_active) or getattr(supplier, "merged_into_supplier_id", None):
        return _json_error("Supplier not found.", status_code=404, code="not_found")
    return jsonify({"meta": build_meta(), "data": _mobile_supplier_payload(supplier)})


def mobile_opportunity_create_view(root):
    write_error = _require_mobile_workflow(root, "buying")
    if write_error:
        return write_error
    payload = _mobile_payload()
    try:
        supplier, warning = _resolve_mobile_supplier(root, payload)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")
    if warning:
        return jsonify({"meta": build_meta(), "data": warning})

    strain_name = (payload.get("strain_name") or "").strip()
    if not strain_name:
        return _json_error("Strain name is required.", status_code=400, code="bad_request")
    expected_weight = _parse_float(payload.get("expected_weight_lbs"), "Expected weight lbs", allow_none=False)
    if expected_weight is None or expected_weight <= 0:
        return _json_error("Expected weight lbs must be greater than 0.", status_code=400, code="bad_request")

    availability_date = _parse_date(payload.get("availability_date"), "Availability date", default_today=True)
    expected_potency = _parse_float(payload.get("expected_potency_pct"), "Expected potency pct")
    offered_price = _parse_float(payload.get("offered_price_per_lb"), "Offered price per lb")

    purchase = root.Purchase(
        supplier_id=supplier.id,
        created_by_user_id=current_user.id,
        purchase_date=availability_date or date.today(),
        availability_date=availability_date or date.today(),
        status="ordered",
        declared_weight_lbs=float(expected_weight),
        stated_weight_lbs=float(expected_weight),
        declared_price_per_lb=offered_price,
        price_per_lb=offered_price,
        stated_potency_pct=expected_potency,
        clean_or_dirty=(payload.get("clean_or_dirty") or "").strip() or None,
        testing_notes=(payload.get("testing_notes") or "").strip() or None,
        notes=(payload.get("notes") or "").strip() or None,
    )
    root.db.session.add(purchase)
    root.db.session.flush()
    if not purchase.batch_id:
        batch_id = generate_batch_id(supplier.name, availability_date, expected_weight)
        purchase.batch_id = ensure_unique_batch_id(batch_id, exclude_purchase_id=purchase.id)

    lot = root.PurchaseLot(
        purchase_id=purchase.id,
        strain_name=strain_name,
        weight_lbs=float(expected_weight),
        remaining_weight_lbs=float(expected_weight),
        potency_pct=expected_potency,
    )
    root.db.session.add(lot)
    root.db.session.flush()
    ensure_purchase_lot_tracking(purchase)
    audit_mobile_action(
        root,
        action="create",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="buying",
        details={"batch_id": purchase.batch_id, "supplier_id": purchase.supplier_id, "created_by_user_id": current_user.id},
        user_id=current_user.id,
    )
    root.db.session.commit()
    return jsonify({"meta": build_meta(), "data": {"opportunity": _mobile_purchase_detail(purchase), "requires_confirmation": False}}), 201


def mobile_opportunity_update_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "buying")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if purchase.created_by_user_id != current_user.id and not current_user.is_super_admin:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if not _mobile_purchase_editable(purchase):
        return _json_error("Opportunity can no longer be edited after approval.", status_code=409, code="locked")

    payload = _mobile_payload()
    supplier_payload_keys = {
        "supplier_id",
        "new_supplier",
        "new_supplier_name",
        "confirm_new_supplier",
        "new_supplier_contact_name",
        "new_supplier_phone",
        "new_supplier_email",
        "new_supplier_location",
        "new_supplier_notes",
    }
    if any(key in payload for key in supplier_payload_keys):
        try:
            supplier, warning = _resolve_mobile_supplier(root, payload)
        except ValueError as exc:
            return _json_error(str(exc), status_code=400, code="bad_request")
        if warning:
            return jsonify({"meta": build_meta(), "data": warning})
        if supplier is not None:
            purchase.supplier_id = supplier.id

    if "availability_date" in payload:
        purchase.availability_date = _parse_date(payload.get("availability_date"), "Availability date", default_today=False)
    if "strain_name" in payload or "expected_weight_lbs" in payload or "expected_potency_pct" in payload or "offered_price_per_lb" in payload:
        lot = _mobile_purchase_lot(purchase)
        if lot is None:
            lot = root.PurchaseLot(purchase_id=purchase.id, strain_name=(payload.get("strain_name") or "").strip() or "Opportunity total", weight_lbs=0, remaining_weight_lbs=0)
            root.db.session.add(lot)
            root.db.session.flush()
        if "strain_name" in payload and (payload.get("strain_name") or "").strip():
            lot.strain_name = (payload.get("strain_name") or "").strip()
        if "expected_weight_lbs" in payload:
            expected_weight = _parse_float(payload.get("expected_weight_lbs"), "Expected weight lbs", allow_none=False)
            lot.weight_lbs = float(expected_weight or 0)
            lot.remaining_weight_lbs = float(expected_weight or 0)
            purchase.declared_weight_lbs = float(expected_weight or 0)
            purchase.stated_weight_lbs = float(expected_weight or 0)
        if "expected_potency_pct" in payload:
            expected_potency = _parse_float(payload.get("expected_potency_pct"), "Expected potency pct")
            purchase.stated_potency_pct = expected_potency
            lot.potency_pct = expected_potency
        if "offered_price_per_lb" in payload:
            purchase.declared_price_per_lb = _parse_float(payload.get("offered_price_per_lb"), "Offered price per lb")
            purchase.price_per_lb = purchase.declared_price_per_lb
        ensure_purchase_lot_tracking(purchase)

    if "clean_or_dirty" in payload:
        purchase.clean_or_dirty = (payload.get("clean_or_dirty") or "").strip() or None
    if "testing_notes" in payload:
        purchase.testing_notes = (payload.get("testing_notes") or "").strip() or None
    if "notes" in payload:
        purchase.notes = (payload.get("notes") or "").strip() or None

    audit_mobile_action(
        root,
        action="update",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="buying",
        details={"updated_fields": sorted(payload.keys())},
        user_id=current_user.id,
    )
    root.db.session.commit()
    return jsonify({"meta": build_meta(), "data": {"opportunity": _mobile_purchase_detail(purchase)}})


def mobile_opportunity_delivery_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "buying")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if purchase.created_by_user_id != current_user.id and not current_user.is_super_admin:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if not _mobile_delivery_allowed(purchase):
        return _json_error("Delivery can only be recorded after approval or commitment.", status_code=409, code="delivery_not_allowed")

    payload = _mobile_payload()
    try:
        _mobile_apply_delivery(root, purchase, payload, actor=current_user)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")

    audit_mobile_action(
        root,
        action="deliver",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="buying",
        details={"delivered_weight_lbs": purchase.actual_weight_lbs, "delivery_date": purchase.delivery_date.isoformat() if purchase.delivery_date else None},
        user_id=current_user.id,
    )
    root.db.session.commit()
    return jsonify({"meta": build_meta(), "data": {"opportunity": _mobile_purchase_detail(purchase)}})


def mobile_receiving_receive_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "receiving")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Receiving item not found.", status_code=404, code="not_found")
    if not _mobile_delivery_allowed(purchase):
        return _json_error("Receiving can only be recorded after approval or commitment.", status_code=409, code="delivery_not_allowed")
    payload = _mobile_payload()
    payload.setdefault("floor_state", "receiving")
    try:
        _mobile_apply_delivery(root, purchase, payload, actor=current_user)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")
    audit_mobile_action(
        root,
        action="receive",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="receiving",
        details={"delivered_weight_lbs": purchase.actual_weight_lbs, "location": (payload.get("location") or "").strip() or None},
        user_id=current_user.id,
    )
    root.db.session.commit()
    return jsonify({"meta": build_meta(extra={"workflow": "receiving"}), "data": {"receiving": _mobile_receiving_summary(root, purchase)}})


def mobile_receiving_photos_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "receiving")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Receiving item not found.", status_code=404, code="not_found")
    if not _mobile_delivery_allowed(purchase) and purchase.status != "delivered":
        return _json_error("Delivery photos can only be added after approval or commitment.", status_code=409, code="delivery_not_allowed")

    payload = _mobile_payload()
    photo_context = (payload.get("photo_context") or "").strip().lower() or "delivery"
    if photo_context != "delivery":
        return _json_error("Receiving photo context must be delivery.", status_code=400, code="bad_request")

    files = request.files.getlist("photos") or request.files.getlist("photo")
    if not files:
        single = request.files.get("photo")
        files = [single] if single and getattr(single, "filename", "") else []
    if not files:
        return _json_error("At least one photo file is required.", status_code=400, code="bad_request")
    try:
        _mobile_validate_photo_upload(purchase, photo_context="delivery", files=files)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")

    prefix = f"mobile-{purchase.id}-delivery"
    saved_paths = save_uploads(
        files,
        prefix=prefix,
        upload_dir=current_app.config["MOBILE_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("MOBILE_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_image_filename,
        error_message="Allowed image types: JPG, JPEG, PNG, WEBP, HEIC, HEIF.",
    )

    for path in saved_paths:
        if not photo_asset_exists(
            file_path=path,
            source_type="mobile_api",
            category="biomass",
            photo_context="delivery",
            purchase_id=purchase.id,
        ):
            create_photo_asset(
                path,
                source_type="mobile_api",
                category="biomass",
                photo_context="delivery",
                tags=["mobile", "delivery", "purchase"],
                title=f"Mobile delivery photo ({purchase.batch_id or purchase.id})",
                purchase_id=purchase.id,
                uploaded_by=current_user.id,
            )
    audit_mobile_action(
        root,
        action="upload_photo",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="receiving",
        details={"photo_context": "delivery", "count": len(saved_paths)},
        user_id=current_user.id,
    )
    root.db.session.commit()
    photos = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
        PhotoAsset.photo_context == "delivery",
    ).order_by(PhotoAsset.uploaded_at.desc()).all()
    return jsonify({
        "meta": build_meta(extra={"workflow": "receiving"}),
        "data": {
            "photo_context": "delivery",
            "count": len(photos),
            "photos": [_mobile_photo_payload(photo) for photo in photos],
        },
    }), 201


def mobile_extraction_board_view(root):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    if not workflow_enabled(root, "extraction"):
        return _json_error("This standalone workflow is disabled for the site.", status_code=403, code="workflow_disabled")
    permissions = _mobile_permissions(root, current_user)
    if not permissions["can_extract_lab"]:
        return _json_error("Extraction workflow access required.", status_code=403, code="forbidden")
    return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": _mobile_extraction_board_payload(root)})


def mobile_extraction_lots_view(root):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    if not workflow_enabled(root, "extraction"):
        return _json_error("This standalone workflow is disabled for the site.", status_code=403, code="workflow_disabled")
    permissions = _mobile_permissions(root, current_user)
    if not permissions["can_extract_lab"]:
        return _json_error("Extraction workflow access required.", status_code=403, code="forbidden")
    query_text = (request.args.get("q") or "").strip()
    query = _mobile_extraction_chargeable_lots_query(root).join(root.Supplier, root.Purchase.supplier_id == root.Supplier.id)
    if query_text:
        q = f"%{query_text}%"
        query = query.filter(
            root.or_(
                root.PurchaseLot.tracking_id.ilike(q),
                root.PurchaseLot.strain_name.ilike(q),
                root.Purchase.batch_id.ilike(q),
                root.Supplier.name.ilike(q),
            )
        )
    rows = query.order_by(
        root.Purchase.purchase_date.desc().nullslast(),
        root.PurchaseLot.id.desc(),
    ).limit(40).all()
    return jsonify({"meta": build_meta(extra={"workflow": "extraction", "query": query_text}), "data": [_mobile_extraction_lot_payload(root, lot) for lot in rows]})


def mobile_extraction_lot_detail_view(root, lot_id: str):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    if not workflow_enabled(root, "extraction"):
        return _json_error("This standalone workflow is disabled for the site.", status_code=403, code="workflow_disabled")
    permissions = _mobile_permissions(root, current_user)
    if not permissions["can_extract_lab"]:
        return _json_error("Extraction workflow access required.", status_code=403, code="forbidden")
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None or lot.purchase is None or lot.purchase.deleted_at is not None:
        return _json_error("Extraction lot not found.", status_code=404, code="not_found")
    if float(lot.remaining_weight_lbs or 0) <= 0:
        return _json_error("This lot has no remaining inventory.", status_code=409, code="not_chargeable")
    return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": {"lot": _mobile_extraction_lot_payload(root, lot)}})


def mobile_extraction_lookup_view(root, tracking_id: str):
    if not current_user.is_authenticated:
        return _json_error("Authentication required.", status_code=401, code="unauthorized")
    if not workflow_enabled(root, "extraction"):
        return _json_error("This standalone workflow is disabled for the site.", status_code=403, code="workflow_disabled")
    permissions = _mobile_permissions(root, current_user)
    if not permissions["can_extract_lab"]:
        return _json_error("Extraction workflow access required.", status_code=403, code="forbidden")
    lot = _mobile_extraction_chargeable_lots_query(root).filter(root.PurchaseLot.tracking_id == tracking_id).first()
    if not lot:
        return _json_error("Extraction lot not found.", status_code=404, code="not_found")
    return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": {"lot": _mobile_extraction_lot_payload(root, lot)}})


def mobile_extraction_charge_view(root, lot_id: str):
    write_error = _require_mobile_workflow(root, "extraction")
    if write_error:
        return write_error
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None or lot.purchase is None or lot.purchase.deleted_at is not None:
        return _json_error("Extraction lot not found.", status_code=404, code="not_found")
    payload = _mobile_payload()
    try:
        charged_weight_lbs = float(payload.get("charged_weight_lbs") or 0)
        reactor_number = int(payload.get("reactor_number") or 0)
        charged_at = parse_charge_datetime(payload.get("charged_at"))
        notes = (payload.get("notes") or "").strip() or None
        charge = create_extraction_charge(
            root,
            lot=lot,
            charged_weight_lbs=charged_weight_lbs,
            reactor_number=reactor_number,
            charged_at=charged_at,
            source_mode="standalone_extraction",
            notes=notes,
        )
        audit_mobile_action(
            root,
            action="create",
            entity_type="extraction_charge",
            entity_id=charge.id,
            workflow="extraction",
            details={"lot_id": lot.id, "reactor_number": reactor_number, "charged_weight_lbs": charged_weight_lbs},
            user_id=current_user.id,
        )
        root.session[root.SCAN_RUN_PREFILL_SESSION_KEY] = build_charge_prefill_payload(root, lot, charge)
        root.db.session.commit()
        return jsonify({
            "meta": build_meta(extra={"workflow": "extraction"}),
            "data": {
                "charge": _mobile_extraction_charge_payload(root, charge),
                "lot": _mobile_extraction_lot_payload(root, lot),
                "next_run_url": root.url_for("run_new", return_to=root.url_for("floor_ops")),
            },
        }), 201
    except ValueError as exc:
        root.db.session.rollback()
        return _json_error(str(exc), status_code=400, code="bad_request")


def mobile_extraction_transition_view(root, charge_id: str):
    write_error = _require_mobile_workflow(root, "extraction")
    if write_error:
        return write_error
    charge = root.db.session.get(root.ExtractionCharge, charge_id)
    if charge is None:
        return _json_error("Extraction charge not found.", status_code=404, code="not_found")
    payload = _mobile_payload()
    target_state = (payload.get("target_state") or "").strip()
    cancel_resolution = (payload.get("cancel_resolution") or "").strip().lower() or None
    try:
        update_charge_state(
            root,
            charge,
            target_state,
            history_entries=charge_history_entries(root, charge.id, limit=20),
            cancel_resolution=cancel_resolution,
            context={"source": "standalone_extraction"},
        )
        audit_mobile_action(
            root,
            action="transition",
            entity_type="extraction_charge",
            entity_id=charge.id,
            workflow="extraction",
            details={"target_state": target_state, "cancel_resolution": cancel_resolution},
            user_id=current_user.id,
        )
        root.db.session.commit()
        return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": {"charge": _mobile_extraction_charge_payload(root, charge)}})
    except ValueError as exc:
        root.db.session.rollback()
        return _json_error(str(exc), status_code=400, code="bad_request")


def mobile_extraction_run_view(root, charge_id: str):
    write_error = _require_mobile_workflow(root, "extraction")
    if write_error:
        return write_error
    charge = root.db.session.get(root.ExtractionCharge, charge_id)
    if charge is None:
        return _json_error("Extraction charge not found.", status_code=404, code="not_found")

    if request.method == "GET":
        if charge.run_id:
            run = root.db.session.get(root.Run, charge.run_id)
            if run is not None:
                return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": _mobile_extraction_run_response(root, charge, run)})
        return jsonify({
            "meta": build_meta(extra={"workflow": "extraction"}),
            "data": {
                "charge": _mobile_extraction_charge_payload(root, charge),
                "lot": _mobile_extraction_lot_payload(root, charge.lot) if charge.lot is not None else None,
                "run": draft_run_payload(root, charge),
            },
        })

    payload = _mobile_payload()
    try:
        had_run_before = bool(charge.run_id)
        run = ensure_run_for_charge(root, charge)
        apply_execution_payload(run, payload)
        run.calculate_yields()
        run.calculate_cost()
        audit_mobile_action(
            root,
            action="update" if had_run_before else "create",
            entity_type="run",
            entity_id=run.id,
            workflow="extraction",
            details={"charge_id": charge.id, "reactor_number": run.reactor_number},
            user_id=current_user.id,
        )
        root.db.session.commit()
        return jsonify({"meta": build_meta(extra={"workflow": "extraction"}), "data": _mobile_extraction_run_response(root, charge, run)})
    except ValueError as exc:
        root.db.session.rollback()
        return _json_error(str(exc), status_code=400, code="bad_request")


def mobile_opportunity_photos_view(root, opportunity_id: str):
    write_error = _require_mobile_workflow(root, "buying")
    if write_error:
        return write_error
    purchase = root.db.session.get(root.Purchase, opportunity_id)
    if not purchase or purchase.deleted_at is not None:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")
    if purchase.created_by_user_id != current_user.id and not current_user.is_super_admin:
        return _json_error("Opportunity not found.", status_code=404, code="not_found")

    payload = _mobile_payload()
    photo_context = (payload.get("photo_context") or "").strip().lower() or "opportunity"
    if photo_context not in {"opportunity", "delivery"}:
        return _json_error("Photo context must be opportunity or delivery.", status_code=400, code="bad_request")
    if photo_context == "opportunity" and not _mobile_purchase_editable(purchase):
        return _json_error("Opportunity photos can only be added before approval.", status_code=409, code="locked")
    if photo_context == "delivery" and not _mobile_delivery_allowed(purchase):
        return _json_error("Delivery photos can only be added after approval or commitment.", status_code=409, code="delivery_not_allowed")

    files = request.files.getlist("photos") or request.files.getlist("photo")
    if not files:
        single = request.files.get("photo")
        files = [single] if single and getattr(single, "filename", "") else []
    if not files:
        return _json_error("At least one photo file is required.", status_code=400, code="bad_request")
    try:
        _mobile_validate_photo_upload(purchase, photo_context=photo_context, files=files)
    except ValueError as exc:
        return _json_error(str(exc), status_code=400, code="bad_request")

    prefix = f"mobile-{purchase.id}-{photo_context}"
    saved_paths = save_uploads(
        files,
        prefix=prefix,
        upload_dir=current_app.config["MOBILE_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("MOBILE_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_image_filename,
        error_message="Allowed image types: JPG, JPEG, PNG, WEBP, HEIC, HEIF.",
    )

    created = []
    for path in saved_paths:
        if not photo_asset_exists(
            file_path=path,
            source_type="mobile_api",
            category="biomass",
            photo_context=photo_context,
            purchase_id=purchase.id,
        ):
            create_photo_asset(
                path,
                source_type="mobile_api",
                category="biomass",
                photo_context=photo_context,
                tags=["mobile", photo_context, "purchase"],
                title=f"Mobile {photo_context} photo ({purchase.batch_id or purchase.id})",
                purchase_id=purchase.id,
                uploaded_by=current_user.id,
            )
            created.append(path)
    audit_mobile_action(
        root,
        action="upload_photo",
        entity_type="purchase",
        entity_id=purchase.id,
        workflow="buying",
        details={"photo_context": photo_context, "count": len(saved_paths)},
        user_id=current_user.id,
    )
    root.db.session.commit()
    photos = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
        PhotoAsset.photo_context == photo_context,
    ).order_by(PhotoAsset.uploaded_at.desc()).all()
    return jsonify({
        "meta": build_meta(),
        "data": {
            "photo_context": photo_context,
            "count": len(photos),
            "photos": [_mobile_photo_payload(photo) for photo in photos],
        },
    }), 201
