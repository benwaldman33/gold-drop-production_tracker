from __future__ import annotations

import json

from models import SupplierAttachment, db
from services.photo_assets import (
    create_photo_asset,
    photo_asset_exists,
    supplier_attachment_exists,
)


def decorate_submission_rows(submissions) -> None:
    for submission in submissions:
        try:
            lot_rows = json.loads(submission.lots_json or "[]")
            submission.lots_count = len(lot_rows)
            total_weight = 0.0
            for row in lot_rows:
                weight = row.get("weight_lbs")
                if weight is None:
                    continue
                try:
                    total_weight += float(weight)
                except (TypeError, ValueError):
                    continue
            submission.total_weight_lbs = total_weight
        except Exception:
            submission.lots_count = 0
            submission.total_weight_lbs = 0.0

        submission.photo_paths = _load_paths(submission.photos_json)
        submission.supplier_photo_paths = _load_paths(submission.supplier_photos_json)
        submission.biomass_photo_paths = _load_paths(submission.biomass_photos_json)
        submission.coa_photo_paths = _load_paths(submission.coa_photos_json)


def field_submission_error_redirect(root):
    return_to = (root.request.form.get("return_to") or "").strip()
    if return_to == "biomass-purchasing":
        return root.redirect(root.url_for("biomass_purchasing_dashboard"))
    if root.current_user.is_super_admin:
        return root._settings_redirect()
    return root.redirect(root.url_for("field_approvals"))


def field_approval_return_redirect(root):
    return_to = (root.request.form.get("return_to") or "").strip()
    if return_to == "biomass-purchasing":
        return root.redirect(root.url_for("biomass_purchasing_dashboard"))
    if return_to.startswith("#") and root.current_user.is_super_admin:
        return root.redirect(root.url_for("settings") + return_to)
    return root.redirect(root.url_for("field_approvals"))


def promote_submission_photos(submission, purchase_id: str, uploaded_by: str | None) -> dict[str, int]:
    supplier_photo_paths = _load_paths(submission.supplier_photos_json)
    biomass_photo_paths = _load_paths(submission.biomass_photos_json)
    coa_photo_paths = _load_paths(submission.coa_photos_json)
    if not supplier_photo_paths and not biomass_photo_paths and not coa_photo_paths:
        biomass_photo_paths = _load_paths(submission.photos_json)

    supplier_attachments_added = 0
    assets_added = 0

    for path in supplier_photo_paths:
        if not supplier_attachment_exists(supplier_id=submission.supplier_id, file_path=path):
            db.session.add(SupplierAttachment(
                supplier_id=submission.supplier_id,
                document_type="license",
                title=f"Field submission {submission.id} supplier doc",
                file_path=path,
                uploaded_by=uploaded_by,
            ))
            supplier_attachments_added += 1
        if not photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="supplier_license",
            submission_id=submission.id,
            supplier_id=submission.supplier_id,
            purchase_id=purchase_id,
        ):
            create_photo_asset(
                path,
                source_type="field_submission",
                category="supplier_license",
                tags=["field", "supplier", "license"],
                title=f"Field submission {submission.id}",
                supplier_id=submission.supplier_id,
                purchase_id=purchase_id,
                submission_id=submission.id,
                uploaded_by=uploaded_by,
            )
            assets_added += 1

    for path in biomass_photo_paths:
        if not photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="biomass",
            submission_id=submission.id,
            supplier_id=submission.supplier_id,
            purchase_id=purchase_id,
        ):
            create_photo_asset(
                path,
                source_type="field_submission",
                category="biomass",
                tags=["field", "purchase", "biomass", "audit"],
                title=f"Purchase audit biomass photo ({submission.id})",
                supplier_id=submission.supplier_id,
                purchase_id=purchase_id,
                submission_id=submission.id,
                uploaded_by=uploaded_by,
            )
            assets_added += 1

    for path in coa_photo_paths:
        if not photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="coa",
            submission_id=submission.id,
            supplier_id=submission.supplier_id,
            purchase_id=purchase_id,
        ):
            create_photo_asset(
                path,
                source_type="field_submission",
                category="coa",
                tags=["field", "purchase", "coa", "audit"],
                title=f"Purchase audit COA photo ({submission.id})",
                supplier_id=submission.supplier_id,
                purchase_id=purchase_id,
                submission_id=submission.id,
                uploaded_by=uploaded_by,
            )
            assets_added += 1

    return {
        "supplier_attachments_added": supplier_attachments_added,
        "assets_added": assets_added,
    }


def submission_total_weight(lots) -> float:
    return sum(float(row.get("weight_lbs") or 0) for row in lots if row.get("weight_lbs") is not None)


def load_lots(value: str | None) -> list:
    try:
        loaded = json.loads(value or "[]")
    except Exception:
        return []
    return loaded if isinstance(loaded, list) else []


def _load_paths(value: str | None) -> list[str]:
    try:
        paths = json.loads(value or "[]")
    except Exception:
        return []
    return [path for path in paths if isinstance(path, str) and path.strip()]
