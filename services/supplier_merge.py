from __future__ import annotations

import json
from datetime import datetime, timezone


def _count(query) -> int:
    return int(query.count())


def supplier_merge_preview(root, source_supplier, target_supplier) -> dict:
    if not source_supplier or not target_supplier:
        raise ValueError("Source and target suppliers are required.")
    if source_supplier.id == target_supplier.id:
        raise ValueError("Source and target suppliers must be different.")
    if getattr(source_supplier, "merged_into_supplier_id", None):
        merged_into = root.db.session.get(root.Supplier, source_supplier.merged_into_supplier_id)
        raise ValueError(
            f"Source supplier is already merged into {merged_into.name if merged_into else 'another supplier'}."
        )
    if not bool(source_supplier.is_active):
        raise ValueError("Source supplier is inactive. Reactivate it or choose a different source supplier.")
    if not bool(target_supplier.is_active):
        raise ValueError("Target supplier must be active.")
    if getattr(target_supplier, "merged_into_supplier_id", None):
        merged_into = root.db.session.get(root.Supplier, target_supplier.merged_into_supplier_id)
        raise ValueError(
            f"Target supplier is already merged into {merged_into.name if merged_into else 'another supplier'}."
        )

    purchase_count = _count(root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.supplier_id == source_supplier.id,
    ))
    purchase_lot_count = _count(root.PurchaseLot.query.join(
        root.Purchase,
        root.PurchaseLot.purchase_id == root.Purchase.id,
    ).filter(
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.supplier_id == source_supplier.id,
    ))
    biomass_count = _count(root.BiomassAvailability.query.filter(
        root.BiomassAvailability.deleted_at.is_(None),
        root.BiomassAvailability.supplier_id == source_supplier.id,
    ))
    field_submission_count = _count(root.FieldPurchaseSubmission.query.filter(
        root.FieldPurchaseSubmission.supplier_id == source_supplier.id,
    ))
    lab_test_count = _count(root.LabTest.query.filter(
        root.LabTest.supplier_id == source_supplier.id,
    ))
    attachment_count = _count(root.SupplierAttachment.query.filter(
        root.SupplierAttachment.supplier_id == source_supplier.id,
    ))
    photo_count = _count(root.PhotoAsset.query.filter(
        root.PhotoAsset.supplier_id == source_supplier.id,
    ))

    return {
        "source": {
            "id": source_supplier.id,
            "name": source_supplier.name,
            "is_active": bool(source_supplier.is_active),
            "merged_into_supplier_id": source_supplier.merged_into_supplier_id,
            "merged_into_supplier_name": source_supplier.merged_into_supplier.name if getattr(source_supplier, "merged_into_supplier", None) else None,
        },
        "target": {
            "id": target_supplier.id,
            "name": target_supplier.name,
            "is_active": bool(target_supplier.is_active),
        },
        "counts": {
            "purchases": purchase_count,
            "purchase_lots": purchase_lot_count,
            "biomass_availabilities": biomass_count,
            "field_purchase_submissions": field_submission_count,
            "lab_tests": lab_test_count,
            "supplier_attachments": attachment_count,
            "photo_assets": photo_count,
        },
        "will_move": [
            "purchases (and their linked lots)",
            "biomass availability rows",
            "field purchase submissions",
            "lab tests",
            "supplier attachments",
            "supplier-linked photo assets",
        ],
    }


def execute_supplier_merge(root, source_supplier, target_supplier, *, merged_by_user_id: str, merge_notes: str | None = None) -> dict:
    preview = supplier_merge_preview(root, source_supplier, target_supplier)

    for purchase in root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.supplier_id == source_supplier.id,
    ).all():
        purchase.supplier_id = target_supplier.id

    for biomass in root.BiomassAvailability.query.filter(
        root.BiomassAvailability.deleted_at.is_(None),
        root.BiomassAvailability.supplier_id == source_supplier.id,
    ).all():
        biomass.supplier_id = target_supplier.id

    for submission in root.FieldPurchaseSubmission.query.filter(
        root.FieldPurchaseSubmission.supplier_id == source_supplier.id,
    ).all():
        submission.supplier_id = target_supplier.id

    for test in root.LabTest.query.filter(
        root.LabTest.supplier_id == source_supplier.id,
    ).all():
        test.supplier_id = target_supplier.id

    for attachment in root.SupplierAttachment.query.filter(
        root.SupplierAttachment.supplier_id == source_supplier.id,
    ).all():
        attachment.supplier_id = target_supplier.id

    for asset in root.PhotoAsset.query.filter(
        root.PhotoAsset.supplier_id == source_supplier.id,
    ).all():
        asset.supplier_id = target_supplier.id

    source_supplier.is_active = False
    source_supplier.merged_into_supplier_id = target_supplier.id
    source_supplier.merged_at = datetime.now(timezone.utc)
    source_supplier.merged_by_user_id = merged_by_user_id
    source_supplier.merge_notes = (merge_notes or "").strip() or None

    summary = {
        **preview,
        "merged_at": source_supplier.merged_at.isoformat(),
        "merged_by_user_id": merged_by_user_id,
        "merge_notes": source_supplier.merge_notes,
    }
    root.log_audit("merge", "supplier", source_supplier.id, details=json.dumps(summary))
    root.db.session.commit()
    return summary
