"""Derived purchase, lot, and run journey payload helpers."""

from __future__ import annotations

from flask import url_for

from models import Purchase, PurchaseLot, Run, RunInput, db
from services.material_genealogy import (
    derivative_material_lots_for_purchase,
    derivative_material_lots_for_purchase_lot,
    derivative_material_lots_for_run,
    serialize_material_lot,
)


def build_purchase_journey_payload(
    purchase: Purchase,
    *,
    include_archived: bool = False,
    inventory_on_hand_statuses: tuple[str, ...] | set[str] | frozenset[str] = (
        "delivered",
        "in_testing",
        "available",
        "processing",
    ),
) -> dict:
    """Build a derived stage timeline for one purchase batch."""
    derivative_material_lots = derivative_material_lots_for_purchase(__import__("app"), purchase)
    lots_q = PurchaseLot.query.filter(PurchaseLot.purchase_id == purchase.id)
    if not include_archived:
        lots_q = lots_q.filter(PurchaseLot.deleted_at.is_(None))
    lots = lots_q.all()

    run_id_rows = (
        db.session.query(Run.id)
        .join(RunInput, RunInput.run_id == Run.id)
        .join(PurchaseLot, PurchaseLot.id == RunInput.lot_id)
        .filter(PurchaseLot.purchase_id == purchase.id)
    )
    if not include_archived:
        run_id_rows = run_id_rows.filter(Run.deleted_at.is_(None), PurchaseLot.deleted_at.is_(None))
    run_ids = [rid for (rid,) in run_id_rows.group_by(Run.id).all()]
    runs = Run.query.filter(Run.id.in_(run_ids)).all() if run_ids else []
    run_inputs_q = (
        RunInput.query.join(PurchaseLot, PurchaseLot.id == RunInput.lot_id)
        .filter(PurchaseLot.purchase_id == purchase.id)
    )
    if not include_archived:
        run_inputs_q = run_inputs_q.join(Run, Run.id == RunInput.run_id).filter(
            PurchaseLot.deleted_at.is_(None),
            Run.deleted_at.is_(None),
        )
    run_inputs = run_inputs_q.all()

    total_lot_lbs = float(sum(l.weight_lbs or 0 for l in lots))
    total_remaining_lbs = float(sum(l.remaining_weight_lbs or 0 for l in lots))
    consumed_lbs = max(total_lot_lbs - total_remaining_lbs, 0.0)

    delivered_family = {"delivered", "available", "processing", "complete"}
    beyond_testing = {"committed", "delivered", "available", "processing", "complete", "cancelled"}
    hte_stages = {((r.hte_pipeline_stage or "").strip()) for r in runs if (r.hte_pipeline_stage or "").strip()}
    has_post_stage = bool(hte_stages)
    post_in_progress = "awaiting_lab" in hte_stages
    post_done = bool(hte_stages.intersection({"lab_clean", "lab_dirty_queued_strip", "terp_stripped"}))

    events = [
        {
            "stage_key": "declared",
            "state": "done" if purchase.availability_date else "not_started",
            "started_at": purchase.availability_date.isoformat() if purchase.availability_date else None,
            "completed_at": purchase.availability_date.isoformat() if purchase.availability_date else None,
            "metrics": {"declared_weight_lbs": float(purchase.declared_weight_lbs or 0)},
            "links": [{"label": "Purchase", "url": url_for("purchase_edit", purchase_id=purchase.id)}],
        },
        {
            "stage_key": "testing",
            "state": (
                "done"
                if (purchase.testing_status == "completed" or (purchase.status in beyond_testing and purchase.status != "in_testing"))
                else ("in_progress" if purchase.status == "in_testing" else "not_started")
            ),
            "started_at": purchase.testing_date.isoformat() if purchase.testing_date else None,
            "completed_at": purchase.testing_date.isoformat() if purchase.testing_status == "completed" and purchase.testing_date else None,
            "metrics": {"testing_status": (purchase.testing_status or "pending")},
            "links": [{"label": "Biomass Pipeline", "url": url_for("biomass_edit", item_id=purchase.id)}],
        },
        {
            "stage_key": "committed",
            "state": "done" if purchase.status in {"committed", "delivered"} or purchase.purchase_approved_at else "not_started",
            "started_at": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
            "completed_at": purchase.purchase_approved_at.isoformat() if purchase.purchase_approved_at else None,
            "metrics": {"approved": bool(purchase.purchase_approved_at)},
            "links": [{"label": "Purchase", "url": url_for("purchase_edit", purchase_id=purchase.id)}],
        },
        {
            "stage_key": "delivered",
            "state": (
                "done" if purchase.status in delivered_family else ("in_progress" if purchase.status in {"committed", "ordered", "in_transit"} else "not_started")
            ),
            "started_at": purchase.delivery_date.isoformat() if purchase.delivery_date else None,
            "completed_at": purchase.delivery_date.isoformat() if purchase.status in delivered_family and purchase.delivery_date else None,
            "metrics": {"status": purchase.status},
            "links": [{"label": "Purchase", "url": url_for("purchase_edit", purchase_id=purchase.id)}],
        },
        {
            "stage_key": "inventory",
            "state": (
                "done"
                if (purchase.status in inventory_on_hand_statuses and purchase.purchase_approved_at and total_remaining_lbs > 0)
                else ("in_progress" if total_lot_lbs > 0 else "not_started")
            ),
            "started_at": purchase.delivery_date.isoformat() if purchase.delivery_date else None,
            "completed_at": None,
            "metrics": {
                "lot_count": len(lots),
                "total_lot_lbs": total_lot_lbs,
                "remaining_lbs": total_remaining_lbs,
                "consumed_lbs": consumed_lbs,
            },
            "links": [{"label": "Inventory", "url": url_for("inventory")}],
        },
        {
            "stage_key": "extraction",
            "state": "done" if runs else ("in_progress" if consumed_lbs > 0 else "not_started"),
            "started_at": min((r.run_date for r in runs), default=None).isoformat() if runs else None,
            "completed_at": max((r.run_date for r in runs), default=None).isoformat() if runs else None,
            "metrics": {
                "run_count": len(runs),
                "dry_thca_g": float(sum(r.dry_thca_g or 0 for r in runs)),
                "dry_hte_g": float(sum(r.dry_hte_g or 0 for r in runs)),
            },
            "links": [{"label": "Runs", "url": url_for("runs_list")}],
        },
        {
            "stage_key": "post_processing",
            "state": ("done" if post_done else ("in_progress" if post_in_progress else ("not_started" if not has_post_stage else "in_progress"))),
            "started_at": None,
            "completed_at": None,
            "metrics": {"hte_pipeline_stages": sorted(hte_stages)},
            "links": [{"label": "Runs", "url": url_for("runs_list")}],
        },
        {
            "stage_key": "derivative_lots",
            "state": "done" if derivative_material_lots else "not_started",
            "started_at": min((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "completed_at": max((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "metrics": {
                "derivative_lot_count": len(derivative_material_lots),
                "lot_types": sorted({item.lot_type for item in derivative_material_lots}),
            },
            "links": [],
        },
        {
            "stage_key": "sales",
            "state": "not_started",
            "started_at": None,
            "completed_at": None,
            "metrics": {},
            "links": [],
        },
    ]

    lot_nodes = [
        {
            "lot_id": lot.id,
            "tracking_id": getattr(lot, "tracking_id", None),
            "batch_id": purchase.batch_id,
            "supplier_name": lot.supplier_name,
            "strain_name": lot.strain_name,
            "weight_lbs": float(lot.weight_lbs or 0),
            "allocated_weight_lbs": float(getattr(lot, "allocated_weight_lbs", 0) or 0),
            "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
            "remaining_pct": float(getattr(lot, "remaining_pct", 0) or 0),
            "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
            "clean_or_dirty": purchase.clean_or_dirty,
            "testing_status": purchase.testing_status,
            "location": lot.location,
            "purchase_url": url_for("purchase_edit", purchase_id=purchase.id),
        }
        for lot in lots
    ]
    allocation_edges = [
        {
            "run_input_id": inp.id,
            "run_id": inp.run_id,
            "lot_id": inp.lot_id,
            "weight_lbs": float(inp.weight_lbs or 0),
            "allocation_source": getattr(inp, "allocation_source", None),
            "allocation_confidence": getattr(inp, "allocation_confidence", None),
            "slack_ingested_message_id": getattr(inp, "slack_ingested_message_id", None),
        }
        for inp in run_inputs
    ]
    run_nodes = [
        {
            "run_id": run.id,
            "run_date": run.run_date.isoformat() if run.run_date else None,
            "reactor_number": run.reactor_number,
            "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0),
            "dry_thca_g": float(run.dry_thca_g or 0),
            "dry_hte_g": float(run.dry_hte_g or 0),
            "hte_pipeline_stage": run.hte_pipeline_stage,
            "run_url": url_for("run_edit", run_id=run.id),
        }
        for run in sorted(runs, key=lambda item: (item.run_date or "", item.id))
    ]
    derivative_nodes = [
        serialize_material_lot(__import__("app"), material_lot)
        for material_lot in derivative_material_lots
    ]

    exceptions: list[dict] = []
    if not purchase.is_approved:
        exceptions.append({
            "level": "warning",
            "label": "Approval required",
            "detail": "This purchase is not yet approved, so its material cannot be consumed in runs.",
        })
    if not lots and float(purchase.stated_weight_lbs or 0) > 0:
        exceptions.append({
            "level": "warning",
            "label": "No inventory lots",
            "detail": "This purchase has weight but no active lots to allocate from.",
        })
    for lot in lots:
        if not getattr(lot, "tracking_id", None):
            exceptions.append({
                "level": "warning",
                "label": "Missing lot tracking",
                "detail": f"Lot {lot.strain_name} does not have a tracking ID yet.",
            })
        if float(lot.remaining_weight_lbs or 0) < 0:
            exceptions.append({
                "level": "error",
                "label": "Negative remaining weight",
                "detail": f"Lot {lot.strain_name} is below zero remaining weight.",
            })

    return {
        "purchase_id": purchase.id,
        "batch_id": purchase.batch_id,
        "status": purchase.status,
        "include_archived": bool(include_archived),
        "events": events,
        "lots": lot_nodes,
        "allocations": allocation_edges,
        "runs": run_nodes,
        "material_lots": derivative_nodes,
        "exceptions": exceptions,
        "summary": {
            "lot_count": len(lot_nodes),
            "run_count": len(run_nodes),
            "derivative_lot_count": len(derivative_nodes),
            "total_lot_lbs": total_lot_lbs,
            "remaining_lbs": total_remaining_lbs,
            "allocated_lbs": consumed_lbs,
        },
    }


def build_lot_journey_payload(
    lot: PurchaseLot,
    *,
    include_archived: bool = False,
    inventory_on_hand_statuses: tuple[str, ...] | set[str] | frozenset[str] = (
        "delivered",
        "in_testing",
        "available",
        "processing",
    ),
) -> dict:
    """Build a derived journey payload for one inventory lot."""
    derivative_material_lots = derivative_material_lots_for_purchase_lot(__import__("app"), lot)
    purchase = lot.purchase

    run_inputs_q = RunInput.query.filter(RunInput.lot_id == lot.id)
    if not include_archived:
        run_inputs_q = run_inputs_q.join(Run, Run.id == RunInput.run_id).filter(Run.deleted_at.is_(None))
    run_inputs = run_inputs_q.all()

    run_ids = [inp.run_id for inp in run_inputs]
    runs_q = Run.query.filter(Run.id.in_(run_ids)) if run_ids else Run.query.filter(Run.id.is_(None))
    if not include_archived:
        runs_q = runs_q.filter(Run.deleted_at.is_(None))
    runs = runs_q.all() if run_ids else []

    total_lot_lbs = float(lot.weight_lbs or 0)
    total_remaining_lbs = float(lot.remaining_weight_lbs or 0)
    allocated_lbs = float(getattr(lot, "allocated_weight_lbs", 0) or 0)
    consumed_lbs = max(total_lot_lbs - total_remaining_lbs, 0.0)

    hte_stages = {((r.hte_pipeline_stage or "").strip()) for r in runs if (r.hte_pipeline_stage or "").strip()}
    has_post_stage = bool(hte_stages)
    post_in_progress = "awaiting_lab" in hte_stages
    post_done = bool(hte_stages.intersection({"lab_clean", "lab_dirty_queued_strip", "terp_stripped"}))

    events = [
        {
            "stage_key": "purchased",
            "state": "done" if purchase else "not_started",
            "started_at": purchase.purchase_date.isoformat() if purchase and purchase.purchase_date else None,
            "completed_at": purchase.purchase_approved_at.isoformat() if purchase and purchase.purchase_approved_at else None,
            "metrics": {
                "batch_id": purchase.batch_id if purchase else None,
                "purchase_status": purchase.status if purchase else None,
            },
            "links": [{"label": "Purchase", "url": url_for("purchase_edit", purchase_id=purchase.id)}] if purchase else [],
        },
        {
            "stage_key": "inventory",
            "state": (
                "done"
                if purchase and purchase.status in inventory_on_hand_statuses and purchase.purchase_approved_at and total_remaining_lbs > 0
                else ("in_progress" if total_lot_lbs > 0 else "not_started")
            ),
            "started_at": purchase.delivery_date.isoformat() if purchase and purchase.delivery_date else None,
            "completed_at": None,
            "metrics": {
                "weight_lbs": total_lot_lbs,
                "allocated_lbs": allocated_lbs,
                "remaining_lbs": total_remaining_lbs,
            },
            "links": [{"label": "Inventory", "url": url_for("inventory")}],
        },
        {
            "stage_key": "allocation",
            "state": "done" if run_inputs else ("in_progress" if consumed_lbs > 0 else "not_started"),
            "started_at": min((run.run_date for run in runs), default=None).isoformat() if runs else None,
            "completed_at": max((run.run_date for run in runs), default=None).isoformat() if runs else None,
            "metrics": {
                "allocation_count": len(run_inputs),
                "allocated_lbs": allocated_lbs,
            },
            "links": [{"label": "Runs", "url": url_for("runs_list")}] if run_inputs else [],
        },
        {
            "stage_key": "extraction",
            "state": "done" if runs else ("in_progress" if consumed_lbs > 0 else "not_started"),
            "started_at": min((run.run_date for run in runs), default=None).isoformat() if runs else None,
            "completed_at": max((run.run_date for run in runs), default=None).isoformat() if runs else None,
            "metrics": {
                "run_count": len(runs),
                "dry_thca_g": float(sum(run.dry_thca_g or 0 for run in runs)),
                "dry_hte_g": float(sum(run.dry_hte_g or 0 for run in runs)),
            },
            "links": [{"label": "Runs", "url": url_for("runs_list")}],
        },
        {
            "stage_key": "post_processing",
            "state": ("done" if post_done else ("in_progress" if post_in_progress else ("not_started" if not has_post_stage else "in_progress"))),
            "started_at": None,
            "completed_at": None,
            "metrics": {"hte_pipeline_stages": sorted(hte_stages)},
            "links": [{"label": "Runs", "url": url_for("runs_list")}],
        },
        {
            "stage_key": "derivative_lots",
            "state": "done" if derivative_material_lots else "not_started",
            "started_at": min((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "completed_at": max((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "metrics": {
                "derivative_lot_count": len(derivative_material_lots),
                "lot_types": sorted({item.lot_type for item in derivative_material_lots}),
            },
            "links": [],
        },
    ]

    lot_node = {
        "lot_id": lot.id,
        "tracking_id": getattr(lot, "tracking_id", None),
        "batch_id": purchase.batch_id if purchase else None,
        "supplier_name": lot.supplier_name,
        "strain_name": lot.strain_name,
        "weight_lbs": total_lot_lbs,
        "allocated_weight_lbs": allocated_lbs,
        "remaining_weight_lbs": total_remaining_lbs,
        "remaining_pct": float(getattr(lot, "remaining_pct", 0) or 0),
        "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
        "clean_or_dirty": purchase.clean_or_dirty if purchase else None,
        "testing_status": purchase.testing_status if purchase else None,
        "location": lot.location,
        "purchase_url": url_for("purchase_edit", purchase_id=purchase.id) if purchase else None,
    }
    allocation_edges = [
        {
            "run_input_id": inp.id,
            "run_id": inp.run_id,
            "lot_id": inp.lot_id,
            "weight_lbs": float(inp.weight_lbs or 0),
            "allocation_source": getattr(inp, "allocation_source", None),
            "allocation_confidence": getattr(inp, "allocation_confidence", None),
            "slack_ingested_message_id": getattr(inp, "slack_ingested_message_id", None),
        }
        for inp in run_inputs
    ]
    run_nodes = [
        {
            "run_id": run.id,
            "run_date": run.run_date.isoformat() if run.run_date else None,
            "reactor_number": run.reactor_number,
            "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0),
            "dry_thca_g": float(run.dry_thca_g or 0),
            "dry_hte_g": float(run.dry_hte_g or 0),
            "hte_pipeline_stage": run.hte_pipeline_stage,
            "run_url": url_for("run_edit", run_id=run.id),
        }
        for run in sorted(runs, key=lambda item: (item.run_date or "", item.id))
    ]
    derivative_nodes = [
        serialize_material_lot(__import__("app"), material_lot)
        for material_lot in derivative_material_lots
    ]

    exceptions: list[dict] = []
    if purchase and not purchase.is_approved:
        exceptions.append(
            {
                "level": "warning",
                "label": "Approval required",
                "detail": "This lot belongs to an unapproved purchase, so it should not be consumed in runs.",
            }
        )
    if not getattr(lot, "tracking_id", None):
        exceptions.append(
            {
                "level": "warning",
                "label": "Missing lot tracking",
                "detail": f"Lot {lot.strain_name} does not have a tracking ID yet.",
            }
        )
    if total_remaining_lbs < 0:
        exceptions.append(
            {
                "level": "error",
                "label": "Negative remaining weight",
                "detail": f"Lot {lot.strain_name} is below zero remaining weight.",
            }
        )

    return {
        "lot_id": lot.id,
        "purchase_id": purchase.id if purchase else None,
        "batch_id": purchase.batch_id if purchase else None,
        "tracking_id": getattr(lot, "tracking_id", None),
        "include_archived": bool(include_archived),
        "events": events,
        "lot": lot_node,
        "allocations": allocation_edges,
        "runs": run_nodes,
        "material_lots": derivative_nodes,
        "exceptions": exceptions,
        "summary": {
            "run_count": len(run_nodes),
            "derivative_lot_count": len(derivative_nodes),
            "weight_lbs": total_lot_lbs,
            "remaining_lbs": total_remaining_lbs,
            "allocated_lbs": allocated_lbs,
        },
    }


def build_run_journey_payload(run: Run, *, include_archived: bool = False) -> dict:
    """Build a derived journey payload for one extraction run."""
    derivative_material_lots = derivative_material_lots_for_run(__import__("app"), run)
    run_inputs_q = RunInput.query.filter(RunInput.run_id == run.id)
    if not include_archived:
        run_inputs_q = run_inputs_q.join(PurchaseLot, PurchaseLot.id == RunInput.lot_id).filter(
            PurchaseLot.deleted_at.is_(None)
        )
    run_inputs = run_inputs_q.all()

    lot_ids = [inp.lot_id for inp in run_inputs]
    lots_q = PurchaseLot.query.filter(PurchaseLot.id.in_(lot_ids)) if lot_ids else PurchaseLot.query.filter(PurchaseLot.id.is_(None))
    if not include_archived:
        lots_q = lots_q.filter(PurchaseLot.deleted_at.is_(None))
    lots = lots_q.all() if lot_ids else []

    purchase_ids = sorted({lot.purchase_id for lot in lots if lot.purchase_id})
    purchases_q = Purchase.query.filter(Purchase.id.in_(purchase_ids)) if purchase_ids else Purchase.query.filter(Purchase.id.is_(None))
    if not include_archived:
        purchases_q = purchases_q.filter(Purchase.deleted_at.is_(None))
    purchases = purchases_q.all() if purchase_ids else []
    purchase_by_id = {purchase.id: purchase for purchase in purchases}

    hte_stage = (run.hte_pipeline_stage or "").strip()
    has_post_stage = bool(hte_stage)
    post_in_progress = hte_stage == "awaiting_lab"
    post_done = hte_stage in {"lab_clean", "lab_dirty_queued_strip", "terp_stripped"}

    total_input_lbs = float(sum(float(inp.weight_lbs or 0) for inp in run_inputs))
    total_dry_thca = float(run.dry_thca_g or 0)
    total_dry_hte = float(run.dry_hte_g or 0)

    events = [
        {
            "stage_key": "source_inventory",
            "state": "done" if lots else "blocked",
            "started_at": min((purchase.purchase_date for purchase in purchases), default=None).isoformat() if purchases else None,
            "completed_at": max((purchase.delivery_date for purchase in purchases if purchase.delivery_date), default=None).isoformat() if purchases and any(purchase.delivery_date for purchase in purchases) else None,
            "metrics": {
                "purchase_count": len(purchases),
                "lot_count": len(lots),
                "input_lbs": total_input_lbs,
            },
            "links": [{"label": "Inventory", "url": url_for("inventory")}],
        },
        {
            "stage_key": "allocation",
            "state": "done" if run_inputs else "blocked",
            "started_at": run.run_date.isoformat() if run.run_date else None,
            "completed_at": run.run_date.isoformat() if run.run_date else None,
            "metrics": {
                "allocation_count": len(run_inputs),
                "input_lbs": total_input_lbs,
            },
            "links": [{"label": "Run", "url": url_for("run_edit", run_id=run.id)}],
        },
        {
            "stage_key": "extraction",
            "state": "done",
            "started_at": run.run_date.isoformat() if run.run_date else None,
            "completed_at": run.run_date.isoformat() if run.run_date else None,
            "metrics": {
                "reactor_number": run.reactor_number,
                "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0),
                "dry_thca_g": total_dry_thca,
                "dry_hte_g": total_dry_hte,
            },
            "links": [{"label": "Run", "url": url_for("run_edit", run_id=run.id)}],
        },
        {
            "stage_key": "post_processing",
            "state": ("done" if post_done else ("in_progress" if post_in_progress else ("not_started" if not has_post_stage else "in_progress"))),
            "started_at": None,
            "completed_at": None,
            "metrics": {"hte_pipeline_stage": hte_stage or None},
            "links": [{"label": "Runs", "url": url_for("runs_list")}],
        },
        {
            "stage_key": "derivative_lots",
            "state": "done" if derivative_material_lots else "not_started",
            "started_at": min((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "completed_at": max((item.created_at for item in derivative_material_lots), default=None).isoformat() if derivative_material_lots else None,
            "metrics": {
                "derivative_lot_count": len(derivative_material_lots),
                "lot_types": sorted({item.lot_type for item in derivative_material_lots}),
            },
            "links": [],
        },
    ]

    purchase_nodes = [
        {
            "purchase_id": purchase.id,
            "batch_id": purchase.batch_id,
            "status": purchase.status,
            "supplier_name": purchase.supplier.name if purchase.supplier else None,
            "purchase_url": url_for("purchase_edit", purchase_id=purchase.id),
        }
        for purchase in sorted(purchases, key=lambda item: (item.purchase_date or "", item.id))
    ]
    lot_nodes = [
        {
            "lot_id": lot.id,
            "purchase_id": lot.purchase_id,
            "tracking_id": getattr(lot, "tracking_id", None),
            "batch_id": purchase_by_id.get(lot.purchase_id).batch_id if purchase_by_id.get(lot.purchase_id) else None,
            "supplier_name": lot.supplier_name,
            "strain_name": lot.strain_name,
            "weight_lbs": float(lot.weight_lbs or 0),
            "allocated_weight_lbs": float(getattr(lot, "allocated_weight_lbs", 0) or 0),
            "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
            "remaining_pct": float(getattr(lot, "remaining_pct", 0) or 0),
            "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
            "clean_or_dirty": purchase_by_id.get(lot.purchase_id).clean_or_dirty if purchase_by_id.get(lot.purchase_id) else None,
            "testing_status": purchase_by_id.get(lot.purchase_id).testing_status if purchase_by_id.get(lot.purchase_id) else None,
            "location": lot.location,
            "purchase_url": url_for("purchase_edit", purchase_id=lot.purchase_id) if lot.purchase_id else None,
        }
        for lot in sorted(lots, key=lambda item: (item.purchase_id or "", item.id))
    ]
    allocation_edges = [
        {
            "run_input_id": inp.id,
            "run_id": inp.run_id,
            "lot_id": inp.lot_id,
            "purchase_id": inp.lot.purchase_id if inp.lot else None,
            "weight_lbs": float(inp.weight_lbs or 0),
            "allocation_source": getattr(inp, "allocation_source", None),
            "allocation_confidence": getattr(inp, "allocation_confidence", None),
            "slack_ingested_message_id": getattr(inp, "slack_ingested_message_id", None),
        }
        for inp in run_inputs
    ]
    run_node = {
        "run_id": run.id,
        "run_date": run.run_date.isoformat() if run.run_date else None,
        "reactor_number": run.reactor_number,
        "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0),
        "dry_thca_g": total_dry_thca,
        "dry_hte_g": total_dry_hte,
        "hte_pipeline_stage": run.hte_pipeline_stage,
        "run_url": url_for("run_edit", run_id=run.id),
    }
    derivative_nodes = [
        serialize_material_lot(__import__("app"), material_lot)
        for material_lot in derivative_material_lots
    ]

    exceptions: list[dict] = []
    if not run_inputs:
        exceptions.append(
            {
                "level": "warning",
                "label": "Missing source allocations",
                "detail": "This run has no explicit lot allocations.",
            }
        )
    for lot in lots:
        purchase = purchase_by_id.get(lot.purchase_id)
        if purchase and not purchase.is_approved:
            exceptions.append(
                {
                    "level": "warning",
                    "label": "Unapproved source purchase",
                    "detail": f"Lot {lot.strain_name} belongs to an unapproved purchase.",
                }
            )
        if not getattr(lot, "tracking_id", None):
            exceptions.append(
                {
                    "level": "warning",
                    "label": "Missing lot tracking",
                    "detail": f"Lot {lot.strain_name} does not have a tracking ID yet.",
                }
            )

    return {
        "run_id": run.id,
        "include_archived": bool(include_archived),
        "events": events,
        "purchases": purchase_nodes,
        "lots": lot_nodes,
        "allocations": allocation_edges,
        "run": run_node,
        "material_lots": derivative_nodes,
        "exceptions": exceptions,
        "summary": {
            "purchase_count": len(purchase_nodes),
            "lot_count": len(lot_nodes),
            "derivative_lot_count": len(derivative_nodes),
            "input_lbs": total_input_lbs,
            "dry_thca_g": total_dry_thca,
            "dry_hte_g": total_dry_hte,
        },
    }
