from __future__ import annotations

from datetime import date, datetime

from models import PurchaseLot, RunInput
from services.api_site import build_meta


def iso_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def iso_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def envelope(data, *, count=None, limit=None, offset=None, **meta_extra):
    return {
        "meta": build_meta(count=count, limit=limit, offset=offset, extra=meta_extra or None),
        "data": data,
    }


def serialize_supplier_stub(supplier):
    if not supplier:
        return None
    return {
        "id": supplier.id,
        "name": supplier.name,
    }


def _purchase_weight(purchase):
    if purchase.actual_weight_lbs is not None:
        return float(purchase.actual_weight_lbs or 0)
    return float(purchase.stated_weight_lbs or 0)


def _purchase_allocation_metrics(purchase):
    lots = purchase.lots.all() if hasattr(purchase.lots, "all") else list(purchase.lots or [])
    allocated = float(sum(getattr(lot, "allocated_weight_lbs", 0) or 0 for lot in lots))
    remaining = float(sum(float(lot.remaining_weight_lbs or 0) for lot in lots))
    total = float(sum(float(lot.weight_lbs or 0) for lot in lots))
    if lots:
        if remaining <= 0 and total > 0:
            allocation_state = "fully_allocated"
        elif allocated > 0:
            allocation_state = "partially_allocated"
        else:
            allocation_state = "on_hand"
    else:
        allocation_state = "unallocated"
    return {
        "lot_count": len(lots),
        "allocated_weight_lbs": allocated,
        "remaining_weight_lbs": remaining,
        "allocation_state": allocation_state,
    }


def serialize_purchase_summary(purchase):
    allocation = _purchase_allocation_metrics(purchase)
    return {
        "id": purchase.id,
        "batch_id": purchase.batch_id,
        "supplier": serialize_supplier_stub(purchase.supplier),
        "purchase_date": iso_date(purchase.purchase_date),
        "delivery_date": iso_date(purchase.delivery_date),
        "status": purchase.status,
        "stated_weight_lbs": float(purchase.stated_weight_lbs or 0),
        "actual_weight_lbs": float(purchase.actual_weight_lbs or 0) if purchase.actual_weight_lbs is not None else None,
        "effective_weight_lbs": _purchase_weight(purchase),
        "stated_potency_pct": float(purchase.stated_potency_pct or 0) if purchase.stated_potency_pct is not None else None,
        "tested_potency_pct": float(purchase.tested_potency_pct or 0) if purchase.tested_potency_pct is not None else None,
        "price_per_lb": float(purchase.price_per_lb or 0) if purchase.price_per_lb is not None else None,
        "total_cost": float(purchase.total_cost or 0) if purchase.total_cost is not None else None,
        "purchase_approved_at": iso_dt(purchase.purchase_approved_at),
        "purchase_approved_by_user_id": purchase.purchase_approved_by_user_id,
        **allocation,
    }


def serialize_purchase_detail(purchase):
    payload = serialize_purchase_summary(purchase)
    payload.update(
        {
            "availability_date": iso_date(purchase.availability_date),
            "declared_weight_lbs": float(purchase.declared_weight_lbs or 0) if purchase.declared_weight_lbs is not None else None,
            "declared_price_per_lb": float(purchase.declared_price_per_lb or 0) if purchase.declared_price_per_lb is not None else None,
            "testing_timing": purchase.testing_timing,
            "testing_status": purchase.testing_status,
            "testing_date": iso_date(purchase.testing_date),
            "clean_or_dirty": purchase.clean_or_dirty,
            "notes": purchase.notes,
            "lots": [serialize_lot_summary(lot) for lot in purchase.lots.order_by(PurchaseLot.id.asc()).all()],
        }
    )
    return payload


def serialize_lot_summary(lot):
    return {
        "id": lot.id,
        "tracking_id": getattr(lot, "tracking_id", None),
        "barcode_value": getattr(lot, "barcode_value", None),
        "qr_value": getattr(lot, "qr_value", None),
        "purchase_id": lot.purchase_id,
        "batch_id": lot.purchase.batch_id if lot.purchase else None,
        "supplier": serialize_supplier_stub(lot.purchase.supplier if lot.purchase else None),
        "strain_name": lot.strain_name,
        "weight_lbs": float(lot.weight_lbs or 0),
        "allocated_weight_lbs": float(getattr(lot, "allocated_weight_lbs", 0) or 0),
        "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
        "remaining_pct": float(getattr(lot, "remaining_pct", 0) or 0),
        "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
        "testing_status": getattr(lot.purchase, "testing_status", None),
        "clean_or_dirty": getattr(lot.purchase, "clean_or_dirty", None),
        "deleted_at": iso_dt(lot.deleted_at),
    }


def serialize_material_lot_summary(material_lot):
    source_purchase_lot = getattr(material_lot, "source_purchase_lot", None)
    parent_run = getattr(material_lot, "parent_run", None)
    return {
        "id": material_lot.id,
        "tracking_id": material_lot.tracking_id,
        "lot_type": material_lot.lot_type,
        "quantity": float(material_lot.quantity or 0),
        "unit": material_lot.unit,
        "inventory_status": material_lot.inventory_status,
        "workflow_status": material_lot.workflow_status,
        "origin_confidence": material_lot.origin_confidence,
        "source_purchase_lot_id": material_lot.source_purchase_lot_id,
        "parent_run_id": material_lot.parent_run_id,
        "source_purchase_id": source_purchase_lot.purchase_id if source_purchase_lot else None,
        "batch_id": source_purchase_lot.purchase.batch_id if source_purchase_lot and source_purchase_lot.purchase else None,
        "reactor_number": parent_run.reactor_number if parent_run else None,
        "run_date": iso_date(parent_run.run_date) if parent_run else None,
    }


def serialize_material_reconciliation_issue(issue):
    return {
        "id": issue.id,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "status": issue.status,
        "material_lot_id": issue.material_lot_id,
        "transformation_id": issue.transformation_id,
        "run_id": issue.run_id,
        "detected_at": iso_dt(issue.detected_at),
        "assignee_user_id": issue.assignee_user_id,
        "assigned_at": iso_dt(issue.assigned_at),
        "assigned_by_user_id": issue.assigned_by_user_id,
        "working_note": issue.working_note,
        "resolution_note": issue.resolution_note,
        "resolved_at": iso_dt(issue.resolved_at),
        "resolved_by_user_id": issue.resolved_by_user_id,
        "reopened_at": iso_dt(issue.reopened_at),
        "reopened_by_user_id": issue.reopened_by_user_id,
        "reminder_count": int(issue.reminder_count or 0),
        "last_reminded_at": iso_dt(issue.last_reminded_at),
        "next_reminder_due_at": iso_dt(issue.next_reminder_due_at),
    }


def serialize_inventory_lot(lot):
    payload = serialize_lot_summary(lot)
    payload["label"] = lot.display_label
    return payload


def serialize_scan_event(event):
    user = getattr(event, "user", None)
    return {
        "id": event.id,
        "lot_id": event.lot_id,
        "tracking_id": event.tracking_id_snapshot,
        "action": event.action,
        "user_id": event.user_id,
        "user_display_name": getattr(user, "display_name", None),
        "context": getattr(event, "context", {}),
        "created_at": iso_dt(event.created_at),
    }


def serialize_scale_device(device):
    return {
        "id": device.id,
        "name": device.name,
        "location": device.location,
        "make_model": device.make_model,
        "interface_type": device.interface_type,
        "protocol_type": device.protocol_type,
        "connection_target": device.connection_target,
        "is_active": bool(device.is_active),
        "notes": device.notes,
        "created_at": iso_dt(device.created_at),
        "updated_at": iso_dt(device.updated_at),
    }


def serialize_weight_capture(capture):
    return {
        "id": capture.id,
        "capture_type": capture.capture_type,
        "source_mode": capture.source_mode,
        "measured_weight": float(capture.measured_weight or 0),
        "unit": capture.unit,
        "gross_weight": float(capture.gross_weight or 0) if capture.gross_weight is not None else None,
        "tare_weight": float(capture.tare_weight or 0) if capture.tare_weight is not None else None,
        "net_weight": float(capture.net_weight or 0) if capture.net_weight is not None else None,
        "is_stable": capture.is_stable,
        "accepted_at": iso_dt(capture.accepted_at),
        "rejected_at": iso_dt(capture.rejected_at),
        "device_id": capture.device_id,
        "device_name": capture.device.name if capture.device else None,
        "purchase_id": capture.purchase_id,
        "purchase_lot_id": capture.purchase_lot_id,
        "run_id": capture.run_id,
        "notes": capture.notes,
        "raw_payload": capture.raw_payload,
        "created_at": iso_dt(capture.created_at),
    }


def serialize_run_summary(run):
    input_lots = []
    for inp in run.inputs.order_by(RunInput.id.asc()).all():
        lot = inp.lot
        input_lots.append(
            {
                "run_input_id": inp.id,
                "lot_id": inp.lot_id,
                "tracking_id": getattr(lot, "tracking_id", None) if lot else None,
                "supplier": serialize_supplier_stub(lot.purchase.supplier if lot and lot.purchase else None),
                "strain_name": lot.strain_name if lot else None,
                "weight_lbs": float(inp.weight_lbs or 0),
                "allocation_source": getattr(inp, "allocation_source", None),
                "allocation_confidence": getattr(inp, "allocation_confidence", None),
            }
        )
    return {
        "id": run.id,
        "run_date": iso_date(run.run_date),
        "reactor_number": run.reactor_number,
        "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0) if run.bio_in_reactor_lbs is not None else None,
        "dry_hte_g": float(run.dry_hte_g or 0) if run.dry_hte_g is not None else None,
        "dry_thca_g": float(run.dry_thca_g or 0) if run.dry_thca_g is not None else None,
        "overall_yield_pct": float(run.overall_yield_pct or 0) if run.overall_yield_pct is not None else None,
        "thca_yield_pct": float(run.thca_yield_pct or 0) if run.thca_yield_pct is not None else None,
        "hte_yield_pct": float(run.hte_yield_pct or 0) if run.hte_yield_pct is not None else None,
        "cost_per_gram_combined": float(run.cost_per_gram_combined or 0) if run.cost_per_gram_combined is not None else None,
        "slack_channel_id": run.slack_channel_id,
        "slack_message_ts": run.slack_message_ts,
        "hte_pipeline_stage": run.hte_pipeline_stage,
        "input_lots": input_lots,
    }


def serialize_run_detail(run):
    payload = serialize_run_summary(run)
    payload.update(
        {
            "bio_in_house_lbs": float(run.bio_in_house_lbs or 0) if run.bio_in_house_lbs is not None else None,
            "grams_ran": float(run.grams_ran or 0) if run.grams_ran is not None else None,
            "cost_per_gram_thca": float(run.cost_per_gram_thca or 0) if run.cost_per_gram_thca is not None else None,
            "cost_per_gram_hte": float(run.cost_per_gram_hte or 0) if run.cost_per_gram_hte is not None else None,
            "notes": run.notes,
            "created_at": iso_dt(run.created_at),
            "slack_import_applied_at": iso_dt(run.slack_import_applied_at),
        }
    )
    return payload


def serialize_slack_import_summary(row, *, derived=None, coverage=None, linked_run_ids=None):
    derived = derived or {}
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "message_ts": row.message_ts,
        "slack_user_id": row.slack_user_id,
        "message_kind": row.message_kind,
        "derived_message_kind": derived.get("message_kind") or row.message_kind,
        "raw_text": row.raw_text,
        "source": derived.get("source"),
        "strain": derived.get("strain"),
        "hidden_from_imports": bool(getattr(row, "hidden_from_imports", False)),
        "coverage": coverage,
        "linked_run_ids": linked_run_ids or [],
        "promotion_status": "linked" if linked_run_ids else "not_linked",
        "ingested_at": iso_dt(row.ingested_at),
    }


def serialize_slack_import_detail(
    row,
    *,
    derived=None,
    preview=None,
    coverage=None,
    linked_run_ids=None,
    needs_resolution_ui: bool = False,
):
    payload = serialize_slack_import_summary(
        row,
        derived=derived,
        coverage=coverage,
        linked_run_ids=linked_run_ids,
    )
    payload.update(
        {
            "derived": derived or {},
            "preview": preview or {},
            "needs_resolution_ui": bool(needs_resolution_ui),
        }
    )
    return payload


def serialize_exception_item(*, category, entity_type, entity_id, label, detail, level="warning", context=None):
    return {
        "category": category,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "level": level,
        "label": label,
        "detail": detail,
        "context": context or {},
    }


def serialize_supplier_performance_row(*, supplier, profile_incomplete, all_time, ninety_day, last_batch):
    return {
        "supplier": serialize_supplier_stub(supplier),
        "profile_incomplete": bool(profile_incomplete),
        "all_time": all_time,
        "ninety_day": ninety_day,
        "last_batch": last_batch,
    }


def serialize_strain_performance_row(
    *,
    strain_name,
    supplier_name,
    avg_yield,
    avg_thca,
    avg_hte,
    avg_cpg,
    run_count,
    total_lbs,
    total_thca_g,
    total_hte_g,
    view,
):
    return {
        "strain_name": strain_name,
        "supplier_name": supplier_name,
        "view": view,
        "avg_yield": float(avg_yield or 0) if avg_yield is not None else None,
        "avg_thca": float(avg_thca or 0) if avg_thca is not None else None,
        "avg_hte": float(avg_hte or 0) if avg_hte is not None else None,
        "avg_cpg": float(avg_cpg or 0) if avg_cpg is not None else None,
        "run_count": int(run_count or 0),
        "total_lbs": float(total_lbs or 0),
        "total_thca_g": float(total_thca_g or 0),
        "total_hte_g": float(total_hte_g or 0),
    }


def serialize_search_result(*, entity_type, entity_id, label, subtitle=None, match_fields=None, context=None):
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "label": label,
        "subtitle": subtitle,
        "match_fields": match_fields or [],
        "context": context or {},
    }
