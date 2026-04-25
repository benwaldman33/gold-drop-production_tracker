from __future__ import annotations

from collections.abc import Iterable


def _material_tracking_id(root, lot_type: str, source_tracking_id: str | None, source_id: str) -> str:
    base = (source_tracking_id or source_id or "")[-8:].upper()
    prefix = {
        "biomass": "BIO",
        "dry_hte": "HTE",
        "dry_thca": "THCA",
        "golddrop": "GD",
        "liquid_diamonds": "LD",
        "wholesale_thca": "WTHCA",
        "terp_strip_output": "CDT",
        "liquid_loud": "LL",
        "distillate": "DIST",
        "hp_base_oil": "HPBO",
    }.get((lot_type or "").strip(), "MAT")
    if not base:
        base = root.gen_uuid()[:8].upper()
    return f"{prefix}-{base}"


def ensure_biomass_material_lot(root, purchase_lot):
    if purchase_lot is None:
        return None
    existing = getattr(purchase_lot, "material_lot", None)
    if existing is not None:
        existing.tracking_id = purchase_lot.tracking_id or existing.tracking_id
        existing.quantity = float(purchase_lot.weight_lbs or 0)
        existing.unit = "lb"
        existing.strain_name_snapshot = purchase_lot.strain_name
        existing.supplier_name_snapshot = purchase_lot.supplier_name
        existing.inventory_status = _inventory_status_for_purchase_lot(purchase_lot)
        existing.workflow_status = "new"
        existing.origin_confidence = existing.origin_confidence or "backfilled"
        return existing

    material_lot = root.MaterialLot(
        tracking_id=purchase_lot.tracking_id or _material_tracking_id(root, "biomass", purchase_lot.tracking_id, purchase_lot.id),
        lot_type="biomass",
        quantity=float(purchase_lot.weight_lbs or 0),
        unit="lb",
        strain_name_snapshot=purchase_lot.strain_name,
        supplier_name_snapshot=purchase_lot.supplier_name,
        source_purchase_lot_id=purchase_lot.id,
        inventory_status=_inventory_status_for_purchase_lot(purchase_lot),
        workflow_status="new",
        origin_confidence="backfilled",
        notes="Backfilled from PurchaseLot.",
    )
    root.db.session.add(material_lot)
    root.db.session.flush()
    purchase_lot.material_lot_id = material_lot.id
    return material_lot


def _inventory_status_for_purchase_lot(purchase_lot) -> str:
    total = float(purchase_lot.weight_lbs or 0)
    remaining = float(purchase_lot.remaining_weight_lbs or 0)
    if remaining <= 0:
        return "fully_consumed"
    if remaining < total:
        return "partially_consumed"
    return "open"


def backfill_biomass_material_lots(root, *, include_archived: bool = False) -> int:
    query = root.PurchaseLot.query
    if not include_archived:
        query = query.filter(root.PurchaseLot.deleted_at.is_(None))
    lots = query.all()
    created_or_updated = 0
    for lot in lots:
        before = getattr(lot, "material_lot_id", None)
        material_lot = ensure_biomass_material_lot(root, lot)
        if material_lot is None:
            continue
        if before != material_lot.id or before is None:
            created_or_updated += 1
        else:
            created_or_updated += 1
    if created_or_updated:
        root.db.session.flush()
    return created_or_updated


def material_lot_for_purchase_lot(root, purchase_lot):
    if purchase_lot is None:
        return None
    if getattr(purchase_lot, "material_lot", None) is None:
        return ensure_biomass_material_lot(root, purchase_lot)
    return purchase_lot.material_lot


def source_material_lots_for_run(root, run) -> list:
    if run is None:
        return []
    material_lots = []
    for allocation in run.inputs:
        lot = allocation.lot
        if lot is None:
            continue
        material_lot = material_lot_for_purchase_lot(root, lot)
        if material_lot is not None:
            material_lots.append(material_lot)
    seen = set()
    deduped = []
    for item in material_lots:
        if item.id in seen:
            continue
        seen.add(item.id)
        deduped.append(item)
    return deduped


def reconcile_run_material_genealogy(root, run) -> list:
    issues = []
    if run is None:
        return issues
    open_existing = {
        (issue.issue_type, issue.run_id, issue.material_lot_id, issue.transformation_id): issue
        for issue in run.material_reconciliation_issues.filter_by(status="open").all()
    }

    def ensure_issue(issue_type: str, severity: str, *, detail: str, material_lot=None, transformation=None):
        key = (issue_type, run.id, getattr(material_lot, "id", None), getattr(transformation, "id", None))
        existing = open_existing.get(key)
        if existing is not None:
            existing.severity = severity
            existing.resolution_note = detail
            issues.append(existing)
            return existing
        issue = root.MaterialReconciliationIssue(
            issue_type=issue_type,
            severity=severity,
            run_id=run.id,
            material_lot_id=getattr(material_lot, "id", None),
            transformation_id=getattr(transformation, "id", None),
            resolution_note=detail,
            detected_by=getattr(root.current_user, "id", None) if getattr(root, "current_user", None) is not None else None,
        )
        root.db.session.add(issue)
        issues.append(issue)
        return issue

    source_material_lots = source_material_lots_for_run(root, run)
    if run.inputs.count() == 0:
        ensure_issue(
            "missing_input_link",
            "warning",
            detail="Run has no source lot allocations, so genealogy cannot trace biomass ancestry.",
        )
        return issues

    if not source_material_lots:
        ensure_issue(
            "missing_input_link",
            "warning",
            detail="Run has source allocations but no bridged biomass material lots.",
        )

    for allocation in run.inputs:
        if allocation.lot is None:
            continue
        remaining = float(allocation.lot.remaining_weight_lbs or 0)
        total = float(allocation.lot.weight_lbs or 0)
        allocated = float(allocation.weight_lbs or 0)
        if allocated - total > 1e-9:
            ensure_issue(
                "quantity_mismatch",
                "critical",
                detail=f"Allocation {allocated:.2f} lbs exceeds source lot total {total:.2f} lbs.",
                material_lot=material_lot_for_purchase_lot(root, allocation.lot),
            )
        if remaining < 0:
            ensure_issue(
                "negative_balance",
                "critical",
                detail=f"Source lot {allocation.lot.tracking_id or allocation.lot.id} is below zero remaining weight.",
                material_lot=material_lot_for_purchase_lot(root, allocation.lot),
            )

    return issues


def first_open_reconciliation_issues(root, *, limit: int = 100) -> Iterable:
    return (
        root.MaterialReconciliationIssue.query.filter_by(status="open")
        .order_by(root.MaterialReconciliationIssue.detected_at.desc())
        .limit(limit)
        .all()
    )
