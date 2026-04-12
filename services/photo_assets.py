from __future__ import annotations

from models import PhotoAsset, SupplierAttachment, db


ALLOWED_PHOTO_CATEGORIES = frozenset({
    "other",
    "supporting_doc",
    "contract",
    "invoice",
    "coa",
    "lab_result",
    "supplier_doc",
    "supplier_license",
    "biomass",
})


def create_photo_asset(
    file_path: str,
    *,
    source_type: str,
    category: str,
    tags: list[str] | None = None,
    title: str | None = None,
    supplier_id: str | None = None,
    purchase_id: str | None = None,
    submission_id: str | None = None,
    uploaded_by: str | None = None,
) -> None:
    db.session.add(PhotoAsset(
        file_path=file_path,
        source_type=source_type,
        category=category,
        tags=",".join([t.strip().lower() for t in (tags or []) if t and t.strip()]) or None,
        title=title,
        supplier_id=supplier_id,
        purchase_id=purchase_id,
        submission_id=submission_id,
        uploaded_by=uploaded_by,
    ))


def normalize_photo_category(raw: str, *, fallback: str = "other") -> str:
    category = (raw or "").strip().lower().replace(" ", "_")
    return category if category in ALLOWED_PHOTO_CATEGORIES else fallback


def photo_asset_exists(
    *,
    file_path: str,
    source_type: str,
    category: str,
    submission_id: str | None = None,
    supplier_id: str | None = None,
    purchase_id: str | None = None,
) -> bool:
    query = PhotoAsset.query.filter(
        PhotoAsset.file_path == file_path,
        PhotoAsset.source_type == source_type,
        PhotoAsset.category == category,
    )
    if submission_id:
        query = query.filter(PhotoAsset.submission_id == submission_id)
    if supplier_id:
        query = query.filter(PhotoAsset.supplier_id == supplier_id)
    if purchase_id:
        query = query.filter(PhotoAsset.purchase_id == purchase_id)
    return query.first() is not None


def supplier_attachment_exists(*, supplier_id: str, file_path: str) -> bool:
    return SupplierAttachment.query.filter(
        SupplierAttachment.supplier_id == supplier_id,
        SupplierAttachment.file_path == file_path,
    ).first() is not None
