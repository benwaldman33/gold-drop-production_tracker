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


def envelope(data, *, count=None, limit=None, offset=None):
    return {
        "meta": build_meta(count=count, limit=limit, offset=offset),
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


def serialize_inventory_lot(lot):
    payload = serialize_lot_summary(lot)
    payload["label"] = lot.display_label
    return payload


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
