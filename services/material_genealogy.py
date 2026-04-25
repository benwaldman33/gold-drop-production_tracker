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


def _material_lot_sort_key(material_lot):
    return (
        getattr(material_lot, "created_at", None) or "",
        getattr(material_lot, "tracking_id", "") or "",
        getattr(material_lot, "id", "") or "",
    )


def _purchase_lot_payload(root, purchase_lot):
    if purchase_lot is None:
        return None
    purchase = purchase_lot.purchase
    return {
        "purchase_lot_id": purchase_lot.id,
        "tracking_id": purchase_lot.tracking_id,
        "purchase_id": purchase.id if purchase else None,
        "batch_id": purchase.batch_id if purchase else None,
        "supplier_name": purchase_lot.supplier_name,
        "strain_name": purchase_lot.strain_name,
        "weight_lbs": float(purchase_lot.weight_lbs or 0),
        "remaining_weight_lbs": float(purchase_lot.remaining_weight_lbs or 0),
        "purchase_url": root.url_for("purchase_edit", purchase_id=purchase.id) if purchase else None,
    }


def serialize_material_lot(root, material_lot, *, include_links: bool = True) -> dict:
    source_purchase_lot = getattr(material_lot, "source_purchase_lot", None)
    parent_run = getattr(material_lot, "parent_run", None)
    payload = {
        "material_lot_id": material_lot.id,
        "tracking_id": material_lot.tracking_id,
        "lot_type": material_lot.lot_type,
        "quantity": float(material_lot.quantity or 0),
        "unit": material_lot.unit,
        "inventory_status": material_lot.inventory_status,
        "workflow_status": material_lot.workflow_status,
        "active_queue_key": material_lot.active_queue_key,
        "origin_confidence": material_lot.origin_confidence,
        "correction_state": material_lot.correction_state,
        "cost_basis_total": float(material_lot.cost_basis_total or 0) if material_lot.cost_basis_total is not None else None,
        "cost_basis_per_unit": float(material_lot.cost_basis_per_unit or 0) if material_lot.cost_basis_per_unit is not None else None,
        "supplier_name_snapshot": material_lot.supplier_name_snapshot,
        "strain_name_snapshot": material_lot.strain_name_snapshot,
        "source_purchase_lot_id": material_lot.source_purchase_lot_id,
        "parent_run_id": material_lot.parent_run_id,
        "notes": material_lot.notes,
        "created_at": material_lot.created_at.isoformat() if material_lot.created_at else None,
        "updated_at": material_lot.updated_at.isoformat() if material_lot.updated_at else None,
        "closed_at": material_lot.closed_at.isoformat() if material_lot.closed_at else None,
        "closed_reason": material_lot.closed_reason,
        "source_purchase_lot": _purchase_lot_payload(root, source_purchase_lot),
        "parent_run": {
            "run_id": parent_run.id,
            "reactor_number": parent_run.reactor_number,
            "run_date": parent_run.run_date.isoformat() if parent_run and parent_run.run_date else None,
        }
        if parent_run is not None
        else None,
    }
    if include_links:
        payload["links"] = {
            "run_url": root.url_for("run_edit", run_id=parent_run.id) if parent_run is not None else None,
            "purchase_url": root.url_for("purchase_edit", purchase_id=source_purchase_lot.purchase_id)
            if source_purchase_lot is not None and source_purchase_lot.purchase_id
            else None,
            "material_lot_detail": f"/api/v1/material-lots/{material_lot.id}",
            "material_lot_journey": f"/api/v1/material-lots/{material_lot.id}/journey",
            "material_lot_ancestry": f"/api/v1/material-lots/{material_lot.id}/ancestry",
            "material_lot_descendants": f"/api/v1/material-lots/{material_lot.id}/descendants",
        }
    return payload


def serialize_material_transformation(root, transformation) -> dict:
    return {
        "transformation_id": transformation.id,
        "transformation_type": transformation.transformation_type,
        "run_id": transformation.run_id,
        "source_record_type": transformation.source_record_type,
        "source_record_id": transformation.source_record_id,
        "status": transformation.status,
        "performed_at": transformation.performed_at.isoformat() if transformation.performed_at else None,
        "performed_by_user_id": transformation.performed_by_user_id,
        "notes": transformation.notes,
        "run_url": root.url_for("run_edit", run_id=transformation.run_id) if transformation.run_id else None,
    }


def serialize_reconciliation_issue(root, issue) -> dict:
    return {
        "issue_id": issue.id,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "status": issue.status,
        "material_lot_id": issue.material_lot_id,
        "transformation_id": issue.transformation_id,
        "run_id": issue.run_id,
        "detected_at": issue.detected_at.isoformat() if issue.detected_at else None,
        "detected_by": issue.detected_by,
        "resolution_note": issue.resolution_note,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "resolved_by_user_id": issue.resolved_by_user_id,
        "run_url": root.url_for("run_edit", run_id=issue.run_id) if issue.run_id else None,
    }


def _resolve_open_issues_for_material_lot(root, material_lot, *, note: str, resolved_by_user_id: str | None = None) -> None:
    if material_lot is None:
        return
    for issue in material_lot.reconciliation_issues.filter_by(status="open").all():
        issue.status = "resolved"
        issue.resolution_note = note
        issue.resolved_at = root.datetime.now(root.timezone.utc)
        issue.resolved_by_user_id = resolved_by_user_id


def _correction_tracking_id(root, material_lot, *, suffix: str) -> str:
    base = material_lot.tracking_id or _material_tracking_id(root, material_lot.lot_type, None, material_lot.id)
    return f"{base}-{suffix}"


def _clone_material_lot_for_correction(root, material_lot, *, quantity: float, reason: str):
    replacement = root.MaterialLot(
        tracking_id=_correction_tracking_id(root, material_lot, suffix="R1"),
        lot_type=material_lot.lot_type,
        quantity=float(quantity or 0),
        unit=material_lot.unit,
        strain_name_snapshot=material_lot.strain_name_snapshot,
        supplier_name_snapshot=material_lot.supplier_name_snapshot,
        source_purchase_lot_id=material_lot.source_purchase_lot_id,
        parent_run_id=material_lot.parent_run_id,
        active_queue_key=material_lot.active_queue_key,
        inventory_status="open" if float(quantity or 0) > 0 else "closed",
        workflow_status=material_lot.workflow_status,
        cost_basis_total=None,
        cost_basis_per_unit=material_lot.cost_basis_per_unit,
        origin_confidence="corrected",
        correction_state="replacement",
        notes=f"Correction replacement for {material_lot.tracking_id or material_lot.id}. Reason: {reason}",
    )
    if material_lot.cost_basis_per_unit is not None:
        replacement.cost_basis_total = float(material_lot.cost_basis_per_unit) * float(quantity or 0)
    elif material_lot.cost_basis_total is not None and float(material_lot.quantity or 0) > 0:
        replacement.cost_basis_total = float(material_lot.cost_basis_total)
    root.db.session.add(replacement)
    root.db.session.flush()
    return replacement


def apply_material_lot_correction(
    root,
    material_lot,
    *,
    correction_kind: str,
    reason: str,
    new_quantity: float | None = None,
    replacement_parent_ids: list[str] | None = None,
):
    if material_lot is None:
        raise ValueError("material_lot is required")
    correction_kind = (correction_kind or "").strip().lower()
    reason = (reason or "").strip()
    if correction_kind not in {"adjust_quantity", "replace_parent", "void_lot"}:
        raise ValueError("Unsupported correction kind")
    if not reason:
        raise ValueError("Correction reason is required")
    if correction_kind == "adjust_quantity" and new_quantity is None:
        raise ValueError("new_quantity is required for adjust_quantity")
    if correction_kind == "replace_parent" and not replacement_parent_ids:
        raise ValueError("replacement_parent_ids are required for replace_parent")

    now = root.datetime.now(root.timezone.utc)
    user_id = getattr(getattr(root, "current_user", None), "id", None)
    transformation_type = {
        "adjust_quantity": "correction_quantity_adjustment",
        "replace_parent": "correction_reparent",
        "void_lot": "correction_void",
    }[correction_kind]
    transformation = root.MaterialTransformation(
        transformation_type=transformation_type,
        run_id=material_lot.parent_run_id,
        source_record_type="material_lot",
        source_record_id=material_lot.id,
        performed_at=now,
        performed_by_user_id=user_id,
        status="completed",
        notes=reason,
    )
    root.db.session.add(transformation)
    root.db.session.flush()

    root.db.session.add(
        root.MaterialTransformationInput(
            transformation_id=transformation.id,
            material_lot_id=material_lot.id,
            quantity_consumed=float(material_lot.quantity or 0),
            unit=material_lot.unit,
            notes="Corrected source lot.",
        )
    )

    replacement_lot = None
    if correction_kind == "adjust_quantity":
        replacement_lot = _clone_material_lot_for_correction(root, material_lot, quantity=float(new_quantity or 0), reason=reason)
    elif correction_kind == "replace_parent":
        replacement_lot = _clone_material_lot_for_correction(root, material_lot, quantity=float(material_lot.quantity or 0), reason=reason)
        for parent_id in replacement_parent_ids or []:
            parent_lot = root.db.session.get(root.MaterialLot, parent_id)
            if parent_lot is None:
                continue
            root.db.session.add(
                root.MaterialTransformationInput(
                    transformation_id=transformation.id,
                    material_lot_id=parent_lot.id,
                    quantity_consumed=float(parent_lot.quantity or 0),
                    unit=parent_lot.unit,
                    notes="Replacement parent material lot.",
                )
            )

    if replacement_lot is not None:
        root.db.session.add(
            root.MaterialTransformationOutput(
                transformation_id=transformation.id,
                material_lot_id=replacement_lot.id,
                quantity_produced=float(replacement_lot.quantity or 0),
                unit=replacement_lot.unit,
                notes="Corrected replacement lot.",
            )
        )

    material_lot.correction_state = {
        "adjust_quantity": "replaced",
        "replace_parent": "replaced",
        "void_lot": "voided",
    }[correction_kind]
    material_lot.inventory_status = "closed"
    material_lot.closed_at = now
    material_lot.closed_reason = reason
    material_lot.workflow_status = "corrected"
    material_lot.active_queue_key = None

    _resolve_open_issues_for_material_lot(root, material_lot, note=f"Resolved by correction: {reason}", resolved_by_user_id=user_id)

    if hasattr(root, "log_audit") and user_id is not None:
        root.log_audit(
            "correct",
            "material_lot",
            material_lot.id,
            details=root.json.dumps(
                {
                    "correction_kind": correction_kind,
                    "reason": reason,
                    "replacement_material_lot_id": replacement_lot.id if replacement_lot is not None else None,
                    "transformation_id": transformation.id,
                    "replacement_parent_ids": replacement_parent_ids or [],
                    "new_quantity": float(new_quantity) if new_quantity is not None else None,
                }
            ),
            user_id=user_id,
        )

    root.db.session.flush()
    return {
        "transformation": transformation,
        "replacement_lot": replacement_lot,
    }


def ensure_biomass_material_lot(root, purchase_lot):
    if purchase_lot is None:
        return None
    with root.db.session.no_autoflush:
        tracking_id = purchase_lot.tracking_id
        strain_name = purchase_lot.strain_name
        supplier_name = purchase_lot.supplier_name
        weight_lbs = float(purchase_lot.weight_lbs or 0)
        inventory_status = _inventory_status_for_purchase_lot(purchase_lot)
    existing = getattr(purchase_lot, "material_lot", None)
    if existing is not None:
        existing.tracking_id = tracking_id or existing.tracking_id
        existing.quantity = weight_lbs
        existing.unit = "lb"
        existing.strain_name_snapshot = strain_name
        existing.supplier_name_snapshot = supplier_name
        existing.inventory_status = inventory_status
        existing.workflow_status = "new"
        existing.origin_confidence = existing.origin_confidence or "backfilled"
        return existing

    material_lot = root.MaterialLot(
        tracking_id=tracking_id or _material_tracking_id(root, "biomass", tracking_id, purchase_lot.id),
        lot_type="biomass",
        quantity=weight_lbs,
        unit="lb",
        strain_name_snapshot=strain_name,
        supplier_name_snapshot=supplier_name,
        source_purchase_lot_id=purchase_lot.id,
        inventory_status=inventory_status,
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


def _run_source_tracking_id(root, run) -> str | None:
    source_lots = source_material_lots_for_run(root, run)
    if not source_lots:
        return None
    ordered = sorted(source_lots, key=_material_lot_sort_key)
    return ordered[0].tracking_id


def _run_cost_for_output(run, lot_type: str, quantity: float) -> tuple[float | None, float | None]:
    if quantity <= 0:
        return None, None
    rate = None
    if lot_type == "dry_hte":
        rate = run.cost_per_gram_hte if run.cost_per_gram_hte is not None else run.cost_per_gram_combined
    elif lot_type == "dry_thca":
        rate = run.cost_per_gram_thca if run.cost_per_gram_thca is not None else run.cost_per_gram_combined
    else:
        rate = run.cost_per_gram_combined
    if rate is None:
        return None, None
    total = float(rate) * float(quantity)
    return total, float(rate)


def _eligible_extraction_outputs(run) -> list[tuple[str, float]]:
    outputs = []
    if float(run.dry_hte_g or 0) > 0:
        outputs.append(("dry_hte", float(run.dry_hte_g or 0)))
    if float(run.dry_thca_g or 0) > 0:
        outputs.append(("dry_thca", float(run.dry_thca_g or 0)))
    return outputs


def ensure_extraction_output_genealogy(root, run):
    if run is None:
        return None

    outputs = _eligible_extraction_outputs(run)
    if not outputs:
        return None

    transformation = (
        run.material_transformations.filter_by(
            transformation_type="extraction",
            source_record_type="run",
            source_record_id=run.id,
        )
        .order_by(root.MaterialTransformation.created_at.asc())
        .first()
    )
    if transformation is None:
        transformation = root.MaterialTransformation(
            transformation_type="extraction",
            run_id=run.id,
            source_record_type="run",
            source_record_id=run.id,
            performed_at=getattr(run, "run_completed_at", None) or (
                run.run_date and root.datetime.combine(run.run_date, root.datetime.min.time(), tzinfo=root.timezone.utc)
            ) or root.datetime.now(root.timezone.utc),
            performed_by_user_id=getattr(root.current_user, "id", None) if getattr(root, "current_user", None) is not None else None,
            status="completed",
            notes="System-generated extraction genealogy transformation.",
        )
        root.db.session.add(transformation)
        root.db.session.flush()

    source_lots = source_material_lots_for_run(root, run)
    existing_inputs = {
        row.material_lot_id: row
        for row in transformation.inputs.all()
    }
    active_input_ids = set()
    for allocation in run.inputs:
        source_lot = material_lot_for_purchase_lot(root, allocation.lot) if allocation.lot is not None else None
        if source_lot is None:
            continue
        active_input_ids.add(source_lot.id)
        row = existing_inputs.get(source_lot.id)
        if row is None:
            row = root.MaterialTransformationInput(
                transformation_id=transformation.id,
                material_lot_id=source_lot.id,
                quantity_consumed=float(allocation.weight_lbs or 0),
                unit="lb",
                notes="Derived from RunInput allocation.",
            )
            root.db.session.add(row)
        else:
            row.quantity_consumed = float(allocation.weight_lbs or 0)
            row.unit = "lb"
            row.notes = "Derived from RunInput allocation."
    for material_lot_id, stale_row in existing_inputs.items():
        if material_lot_id not in active_input_ids:
            root.db.session.delete(stale_row)

    source_tracking_id = _run_source_tracking_id(root, run)
    existing_outputs = {
        row.material_lot.lot_type: row
        for row in transformation.outputs.all()
        if row.material_lot is not None
    }
    active_output_types = set()
    for lot_type, quantity in outputs:
        active_output_types.add(lot_type)
        output_row = existing_outputs.get(lot_type)
        material_lot = output_row.material_lot if output_row is not None else None
        if material_lot is None:
            material_lot = (
                run.material_lots.filter_by(lot_type=lot_type)
                .order_by(root.MaterialLot.created_at.asc())
                .first()
            )
        if material_lot is None:
            material_lot = root.MaterialLot(
                tracking_id=_material_tracking_id(root, lot_type, source_tracking_id, run.id),
                lot_type=lot_type,
                quantity=float(quantity or 0),
                unit="g",
                strain_name_snapshot=source_lots[0].strain_name_snapshot if source_lots else None,
                supplier_name_snapshot=source_lots[0].supplier_name_snapshot if source_lots else None,
                parent_run_id=run.id,
                inventory_status="open",
                workflow_status="extracted",
                origin_confidence="system_generated",
                notes=f"System-generated from extraction run {run.id}.",
            )
            root.db.session.add(material_lot)
            root.db.session.flush()
        material_lot.quantity = float(quantity or 0)
        material_lot.unit = "g"
        material_lot.parent_run_id = run.id
        material_lot.inventory_status = "open" if float(quantity or 0) > 0 else "closed"
        material_lot.workflow_status = "extracted"
        material_lot.origin_confidence = material_lot.origin_confidence or "system_generated"
        material_lot.strain_name_snapshot = material_lot.strain_name_snapshot or (source_lots[0].strain_name_snapshot if source_lots else None)
        material_lot.supplier_name_snapshot = material_lot.supplier_name_snapshot or (source_lots[0].supplier_name_snapshot if source_lots else None)
        cost_total, cost_per_unit = _run_cost_for_output(run, lot_type, float(quantity or 0))
        material_lot.cost_basis_total = cost_total
        material_lot.cost_basis_per_unit = cost_per_unit
        if output_row is None:
            output_row = root.MaterialTransformationOutput(
                transformation_id=transformation.id,
                material_lot_id=material_lot.id,
                quantity_produced=float(quantity or 0),
                unit="g",
                notes="Derived from extraction run outputs.",
            )
            root.db.session.add(output_row)
        else:
            output_row.quantity_produced = float(quantity or 0)
            output_row.unit = "g"
            output_row.notes = "Derived from extraction run outputs."

    for lot_type, stale_row in existing_outputs.items():
        if lot_type not in active_output_types:
            root.db.session.delete(stale_row)

    reconcile_run_material_genealogy(root, run)
    root.db.session.flush()
    return transformation


def backfill_extraction_output_genealogy(root, *, include_archived: bool = False) -> int:
    query = root.Run.query
    if not include_archived:
        query = query.filter(root.Run.deleted_at.is_(None))
    query = query.filter(
        root.db.or_(
            root.Run.dry_hte_g.isnot(None),
            root.Run.dry_thca_g.isnot(None),
        )
    )
    runs = query.all()
    touched = 0
    for run in runs:
        transformation = ensure_extraction_output_genealogy(root, run)
        if transformation is not None:
            touched += 1
    if touched:
        root.db.session.flush()
    return touched


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
    extraction_transformation = (
        run.material_transformations.filter_by(
            transformation_type="extraction",
            source_record_type="run",
            source_record_id=run.id,
        )
        .order_by(root.MaterialTransformation.created_at.asc())
        .first()
    )

    if run.inputs.count() == 0:
        ensure_issue(
            "missing_input_link",
            "warning",
            detail="Run has no source lot allocations, so genealogy cannot trace biomass ancestry.",
            transformation=extraction_transformation,
        )
        return issues

    if not source_material_lots:
        ensure_issue(
            "missing_input_link",
            "warning",
            detail="Run has source allocations but no bridged biomass material lots.",
            transformation=extraction_transformation,
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
                transformation=extraction_transformation,
            )
        if remaining < 0:
            ensure_issue(
                "negative_balance",
                "critical",
                detail=f"Source lot {allocation.lot.tracking_id or allocation.lot.id} is below zero remaining weight.",
                material_lot=material_lot_for_purchase_lot(root, allocation.lot),
                transformation=extraction_transformation,
            )

    if extraction_transformation is not None and extraction_transformation.outputs.count() > 0 and extraction_transformation.inputs.count() == 0:
        ensure_issue(
            "orphan_output",
            "critical",
            detail="Extraction derivative lots exist, but the extraction transformation has no source input rows.",
            transformation=extraction_transformation,
        )

    for output in extraction_transformation.outputs.all() if extraction_transformation is not None else []:
        if output.material_lot is None:
            continue
        if output.material_lot.cost_basis_total is None and output.material_lot.lot_type in {"dry_hte", "dry_thca"}:
            ensure_issue(
                "missing_cost_basis",
                "warning",
                detail=f"Derivative lot {output.material_lot.tracking_id} is missing cost basis.",
                material_lot=output.material_lot,
                transformation=extraction_transformation,
            )

    return issues


def _ancestor_chain(root, material_lot, *, seen=None):
    if material_lot is None:
        return []
    seen = set(seen or set())
    if material_lot.id in seen:
        return []
    seen.add(material_lot.id)
    rows = []
    for output_link in material_lot.transformation_outputs.order_by(root.MaterialTransformationOutput.id.asc()).all():
        transformation = output_link.transformation
        if transformation is None:
            continue
        inputs = []
        for input_link in transformation.inputs.order_by(root.MaterialTransformationInput.id.asc()).all():
            parent_lot = input_link.material_lot
            if parent_lot is None:
                continue
            inputs.append(
                {
                    "link": {
                        "quantity": float(input_link.quantity_consumed or 0),
                        "unit": input_link.unit,
                        "notes": input_link.notes,
                    },
                    "material_lot": serialize_material_lot(root, parent_lot),
                    "ancestors": _ancestor_chain(root, parent_lot, seen=seen),
                }
            )
        rows.append(
            {
                "transformation": serialize_material_transformation(root, transformation),
                "inputs": inputs,
            }
        )
    return rows


def _descendant_chain(root, material_lot, *, seen=None):
    if material_lot is None:
        return []
    seen = set(seen or set())
    if material_lot.id in seen:
        return []
    seen.add(material_lot.id)
    rows = []
    for input_link in material_lot.transformation_inputs.order_by(root.MaterialTransformationInput.id.asc()).all():
        transformation = input_link.transformation
        if transformation is None:
            continue
        outputs = []
        for output_link in transformation.outputs.order_by(root.MaterialTransformationOutput.id.asc()).all():
            child_lot = output_link.material_lot
            if child_lot is None:
                continue
            outputs.append(
                {
                    "link": {
                        "quantity": float(output_link.quantity_produced or 0),
                        "unit": output_link.unit,
                        "notes": output_link.notes,
                    },
                    "material_lot": serialize_material_lot(root, child_lot),
                    "descendants": _descendant_chain(root, child_lot, seen=seen),
                }
            )
        rows.append(
            {
                "transformation": serialize_material_transformation(root, transformation),
                "outputs": outputs,
            }
        )
    return rows


def build_material_lot_detail_payload(root, material_lot) -> dict:
    issues = [
        serialize_reconciliation_issue(root, issue)
        for issue in material_lot.reconciliation_issues.order_by(root.MaterialReconciliationIssue.detected_at.desc()).all()
    ]
    upstream_transformations = [
        serialize_material_transformation(root, row.transformation)
        for row in material_lot.transformation_outputs.order_by(root.MaterialTransformationOutput.id.asc()).all()
        if row.transformation is not None
    ]
    downstream_transformations = [
        serialize_material_transformation(root, row.transformation)
        for row in material_lot.transformation_inputs.order_by(root.MaterialTransformationInput.id.asc()).all()
        if row.transformation is not None
    ]
    return {
        "material_lot": serialize_material_lot(root, material_lot),
        "upstream_transformations": upstream_transformations,
        "downstream_transformations": downstream_transformations,
        "reconciliation_issues": issues,
    }


def build_material_lot_ancestry_payload(root, material_lot) -> dict:
    return {
        "material_lot": serialize_material_lot(root, material_lot),
        "ancestry": _ancestor_chain(root, material_lot),
    }


def build_material_lot_descendants_payload(root, material_lot) -> dict:
    return {
        "material_lot": serialize_material_lot(root, material_lot),
        "descendants": _descendant_chain(root, material_lot),
    }


def build_material_lot_journey_payload(root, material_lot) -> dict:
    root_lot = serialize_material_lot(root, material_lot)
    ancestry = build_material_lot_ancestry_payload(root, material_lot)
    descendants = build_material_lot_descendants_payload(root, material_lot)
    events = []
    if material_lot.source_purchase_lot is not None:
        purchase = material_lot.source_purchase_lot.purchase
        events.append(
            {
                "stage_key": "source_inventory",
                "state": "done",
                "started_at": purchase.purchase_date.isoformat() if purchase and purchase.purchase_date else None,
                "completed_at": purchase.delivery_date.isoformat() if purchase and purchase.delivery_date else None,
                "metrics": {
                    "purchase_id": purchase.id if purchase else None,
                    "purchase_lot_id": material_lot.source_purchase_lot_id,
                },
                "links": [{"label": "Purchase", "url": root.url_for("purchase_edit", purchase_id=purchase.id)}] if purchase else [],
            }
        )
    for node in ancestry["ancestry"]:
        events.append(
            {
                "stage_key": node["transformation"]["transformation_type"],
                "state": node["transformation"]["status"],
                "started_at": node["transformation"]["performed_at"],
                "completed_at": node["transformation"]["performed_at"],
                "metrics": {
                    "input_count": len(node["inputs"]),
                    "transformation_id": node["transformation"]["transformation_id"],
                },
                "links": [{"label": "Run", "url": node["transformation"]["run_url"]}] if node["transformation"]["run_url"] else [],
            }
        )
    if descendants["descendants"]:
        events.append(
            {
                "stage_key": "descendants",
                "state": "in_progress",
                "started_at": None,
                "completed_at": None,
                "metrics": {"descendant_transformation_count": len(descendants["descendants"])},
                "links": [],
            }
        )
    return {
        "material_lot_id": material_lot.id,
        "material_lot": root_lot,
        "events": events,
        "ancestry": ancestry["ancestry"],
        "descendants": descendants["descendants"],
        "summary": {
            "ancestor_transformation_count": len(ancestry["ancestry"]),
            "descendant_transformation_count": len(descendants["descendants"]),
            "quantity": float(material_lot.quantity or 0),
            "unit": material_lot.unit,
        },
    }


def build_material_cost_summary_payload(root) -> dict:
    material_lots = (
        root.MaterialLot.query.filter(root.MaterialLot.lot_type != "biomass")
        .filter(root.MaterialLot.inventory_status == "open")
        .order_by(root.MaterialLot.lot_type.asc(), root.MaterialLot.created_at.asc())
        .all()
    )
    grouped: dict[str, dict] = {}
    for material_lot in material_lots:
        bucket = grouped.setdefault(
            material_lot.lot_type,
            {
                "lot_type": material_lot.lot_type,
                "lot_count": 0,
                "quantity_total": 0.0,
                "cost_basis_total": 0.0,
                "unit": material_lot.unit,
            },
        )
        bucket["lot_count"] += 1
        bucket["quantity_total"] += float(material_lot.quantity or 0)
        bucket["cost_basis_total"] += float(material_lot.cost_basis_total or 0)
    for bucket in grouped.values():
        quantity_total = float(bucket["quantity_total"] or 0)
        bucket["cost_basis_per_unit_avg"] = (
            float(bucket["cost_basis_total"]) / quantity_total if quantity_total > 0 else None
        )
    return {
        "open_derivative_lot_count": len(material_lots),
        "open_derivative_cost_basis_total": float(sum(float(item.cost_basis_total or 0) for item in material_lots)),
        "groups": list(grouped.values()),
        "lots": [serialize_material_lot(root, item) for item in material_lots],
    }


def derivative_material_lots_for_run(root, run) -> list:
    if run is None:
        return []
    ensure_extraction_output_genealogy(root, run)
    material_lots = run.material_lots.order_by(root.MaterialLot.created_at.asc()).all()
    return sorted(material_lots, key=_material_lot_sort_key)


def derivative_material_lots_for_purchase(root, purchase) -> list:
    if purchase is None:
        return []
    lot_ids = [lot.id for lot in purchase.lots.filter(root.PurchaseLot.deleted_at.is_(None)).all()]
    if not lot_ids:
        return []
    run_ids = [
        row[0]
        for row in (
            root.db.session.query(root.RunInput.run_id)
            .filter(root.RunInput.lot_id.in_(lot_ids))
            .group_by(root.RunInput.run_id)
            .all()
        )
    ]
    material_lots = []
    for run in root.Run.query.filter(root.Run.id.in_(run_ids)).all() if run_ids else []:
        material_lots.extend(derivative_material_lots_for_run(root, run))
    deduped = {material_lot.id: material_lot for material_lot in material_lots}
    return sorted(deduped.values(), key=_material_lot_sort_key)


def derivative_material_lots_for_purchase_lot(root, purchase_lot) -> list:
    if purchase_lot is None:
        return []
    run_ids = [
        row[0]
        for row in (
            root.db.session.query(root.RunInput.run_id)
            .filter(root.RunInput.lot_id == purchase_lot.id)
            .group_by(root.RunInput.run_id)
            .all()
        )
    ]
    material_lots = []
    for run in root.Run.query.filter(root.Run.id.in_(run_ids)).all() if run_ids else []:
        material_lots.extend(derivative_material_lots_for_run(root, run))
    deduped = {material_lot.id: material_lot for material_lot in material_lots}
    return sorted(deduped.values(), key=_material_lot_sort_key)


def first_open_reconciliation_issues(root, *, limit: int = 100) -> Iterable:
    return (
        root.MaterialReconciliationIssue.query.filter_by(status="open")
        .order_by(root.MaterialReconciliationIssue.detected_at.desc())
        .limit(limit)
        .all()
    )
