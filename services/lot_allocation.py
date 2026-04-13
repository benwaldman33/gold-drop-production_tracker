from __future__ import annotations

from datetime import datetime, timezone

from models import gen_tracking_id


def ensure_lot_tracking_fields(lot) -> bool:
    if lot is None:
        return False

    changed = False
    if not getattr(lot, "tracking_id", None):
        lot.tracking_id = gen_tracking_id("LOT")
        changed = True
    if not getattr(lot, "barcode_value", None):
        lot.barcode_value = lot.tracking_id
        changed = True
    if not getattr(lot, "qr_value", None):
        lot.qr_value = f"/scan/lot/{lot.tracking_id}"
        changed = True
    if getattr(lot, "label_generated_at", None) is None:
        lot.label_generated_at = datetime.now(timezone.utc)
        changed = True
    if getattr(lot, "label_version", None) is None:
        lot.label_version = 1
        changed = True
    return changed


def ensure_purchase_lot_tracking(purchase) -> bool:
    if purchase is None:
        return False

    changed = False
    for lot in purchase.lots:
        if getattr(lot, "deleted_at", None) is not None:
            continue
        if ensure_lot_tracking_fields(lot):
            changed = True
    return changed


def collect_run_allocations_from_form(root) -> list[dict]:
    merged: dict[str, float] = {}
    lot_ids = root.request.form.getlist("lot_ids[]")
    lot_weights = root.request.form.getlist("lot_weights[]")

    for raw_lot_id, raw_weight in zip(lot_ids, lot_weights):
        lot_id = (raw_lot_id or "").strip()
        weight_text = (raw_weight or "").strip()
        if not lot_id and not weight_text:
            continue
        if not lot_id:
            raise ValueError("Each source material row needs a selected lot.")
        if not weight_text:
            raise ValueError("Each selected source lot needs an allocated weight.")
        weight = float(weight_text)
        if weight <= 0:
            raise ValueError("Allocated lot weight must be greater than zero.")
        merged[lot_id] = merged.get(lot_id, 0.0) + weight

    return [
        {"lot_id": lot_id, "weight_lbs": weight_lbs}
        for lot_id, weight_lbs in merged.items()
    ]


def release_run_allocations(root, run) -> None:
    for inp in run.inputs:
        lot = root.db.session.get(root.PurchaseLot, inp.lot_id)
        if lot is None:
            continue
        restored = float(lot.remaining_weight_lbs or 0) + float(inp.weight_lbs or 0)
        lot.remaining_weight_lbs = min(float(lot.weight_lbs or 0), restored)


def apply_run_allocations(
    root,
    run,
    allocations: list[dict],
    *,
    allocation_source: str = "manual",
    allocation_confidence: float | None = None,
    allocation_notes: str | None = None,
    slack_ingested_message_id: str | None = None,
) -> float:
    if not allocations:
        raise ValueError("At least one source lot allocation is required for a run.")

    total_allocated = 0.0
    for allocation in allocations:
        lot_id = allocation["lot_id"]
        weight = float(allocation["weight_lbs"] or 0)
        lot = root.db.session.get(root.PurchaseLot, lot_id)
        if not lot or lot.deleted_at is not None:
            raise ValueError("A selected source lot could not be found.")
        if not lot.purchase or lot.purchase.deleted_at is not None:
            raise ValueError("A selected source lot belongs to a deleted purchase.")
        if not lot.purchase.is_approved:
            raise ValueError(
                f'Lot "{lot.strain_name}" belongs to an unapproved purchase '
                f"(Batch {lot.purchase.batch_id or lot.purchase.id}). "
                "The purchase must be approved before its material can be used in a run."
            )

        ensure_lot_tracking_fields(lot)

        remaining = float(lot.remaining_weight_lbs or 0)
        if weight > remaining + 1e-9:
            raise ValueError(
                f'Lot "{lot.strain_name}" only has {remaining:.1f} lbs remaining; '
                f"cannot allocate {weight:.1f} lbs."
            )

        root.db.session.add(
            root.RunInput(
                run_id=run.id,
                lot_id=lot.id,
                weight_lbs=weight,
                allocation_source=allocation_source,
                allocation_confidence=allocation_confidence,
                allocation_notes=allocation_notes,
                slack_ingested_message_id=slack_ingested_message_id,
            )
        )
        lot.remaining_weight_lbs = remaining - weight
        total_allocated += weight

    return total_allocated


def rank_lot_candidates(
    root,
    *,
    supplier_ids: list[str] | tuple[str, ...],
    strain_name: str | None = None,
    requested_weight_lbs: float | None = None,
    limit: int = 8,
) -> list[dict]:
    supplier_ids = [sid for sid in supplier_ids if sid]
    if not supplier_ids:
        return []

    strain_norm = " ".join((strain_name or "").strip().lower().split())
    supplier_rank = {sid: idx for idx, sid in enumerate(supplier_ids)}
    lots = (
        root.PurchaseLot.query.join(root.Purchase)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.Purchase.purchase_approved_at.isnot(None),
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.Purchase.supplier_id.in_(supplier_ids),
        )
        .all()
    )

    candidates: list[dict] = []
    for lot in lots:
        purchase = lot.purchase
        score = 100 - (supplier_rank.get(purchase.supplier_id, 99) * 10)
        reasons: list[str] = []
        if supplier_rank.get(purchase.supplier_id, 99) == 0:
            reasons.append("best supplier match")
        else:
            reasons.append("supplier match")

        lot_strain = " ".join((lot.strain_name or "").strip().lower().split())
        if strain_norm:
            if lot_strain == strain_norm:
                score += 30
                reasons.append("exact strain")
            elif strain_norm in lot_strain or lot_strain in strain_norm:
                score += 18
                reasons.append("near strain")
            else:
                score -= 15
                reasons.append("strain differs")

        remaining = float(lot.remaining_weight_lbs or 0)
        sufficient_weight = requested_weight_lbs is None or remaining >= float(requested_weight_lbs)
        if requested_weight_lbs is not None:
            if sufficient_weight:
                score += 20
                reasons.append("enough remaining")
            else:
                score -= 25
                reasons.append("insufficient remaining")

        received_date = purchase.delivery_date or purchase.purchase_date or purchase.availability_date
        candidates.append(
            {
                "lot_id": lot.id,
                "tracking_id": getattr(lot, "tracking_id", None),
                "purchase_id": purchase.id if purchase else None,
                "batch_id": purchase.batch_id if purchase else None,
                "supplier_id": purchase.supplier_id if purchase else None,
                "supplier_name": lot.supplier_name,
                "strain_name": lot.strain_name,
                "weight_lbs": float(lot.weight_lbs or 0),
                "remaining_weight_lbs": remaining,
                "allocated_weight_lbs": float(getattr(lot, "allocated_weight_lbs", 0) or 0),
                "potency_pct": float(lot.potency_pct or 0) if lot.potency_pct is not None else None,
                "clean_or_dirty": getattr(purchase, "clean_or_dirty", None),
                "testing_status": getattr(purchase, "testing_status", None),
                "received_date": received_date.isoformat() if received_date else None,
                "location": getattr(lot, "location", None),
                "sufficient_weight": sufficient_weight,
                "score": score,
                "match_reason": ", ".join(reasons),
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            0 if item["received_date"] else 1,
            item["received_date"] or "",
            item["lot_id"],
        )
    )
    return candidates[:limit]


def choose_default_lot_allocation(candidates: list[dict], requested_weight_lbs: float | None) -> list[dict]:
    if not candidates or requested_weight_lbs is None or requested_weight_lbs <= 0:
        return []
    top = candidates[0]
    if not top.get("sufficient_weight"):
        return []
    next_score = candidates[1]["score"] if len(candidates) > 1 else None
    if len(candidates) == 1 or next_score is None or top["score"] - next_score >= 15:
        return [{"lot_id": top["lot_id"], "weight_lbs": float(requested_weight_lbs)}]
    return []
