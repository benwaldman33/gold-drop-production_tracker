from __future__ import annotations

from datetime import date, datetime

from models import PhotoAsset, Purchase, PurchaseLot, db

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


def parse_sheet_date(value: str):
    """Parse the loose date formats used by spreadsheet imports."""
    text = (value or "").strip().replace("_", "/")
    if not text:
        return None
    for fmt in ("%m/%d", "%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            if parsed.year == 1900:
                parsed = parsed.replace(year=2025)
            return parsed
        except ValueError:
            continue
    return None


def supplier_prefix(name: str, length: int = 5) -> str:
    cleaned = "".join(ch for ch in (name or "").upper() if ch.isalnum())
    return (cleaned[:length] or "BATCH")


def generate_batch_id(supplier_name: str, batch_date: date | None, weight_lbs: float | None) -> str:
    batch_dt = batch_date or date.today()
    rounded_weight = int(round(weight_lbs or 0))
    return f"{supplier_prefix(supplier_name)}-{batch_dt.strftime('%d%b%y').upper()}-{rounded_weight}"[:80]


def ensure_unique_batch_id(candidate: str, *, exclude_purchase_id: str | None = None) -> str:
    """Ensure uniqueness by suffixing -2, -3, ... when needed."""
    base = (candidate or "").strip().upper() or "BATCH"
    batch_id = base
    suffix = 2
    max_attempts = 100
    for _ in range(max_attempts):
        query = Purchase.query.filter(Purchase.batch_id == batch_id)
        if exclude_purchase_id:
            query = query.filter(Purchase.id != exclude_purchase_id)
        if not query.first():
            return batch_id
        batch_id = f"{base}-{suffix}"
        suffix += 1
    raise ValueError(f"Could not generate a unique batch ID for base '{base}' after {max_attempts} attempts.")


def maintain_purchase_inventory_lots(purchase: Purchase, inventory_on_hand_statuses: tuple[str, ...]) -> None:
    """
    Keep default inventory lots in sync with purchase status.

    On-hand purchases need at least one active lot so remaining inventory exists.
    Complete / cancelled purchases should have no remaining inventory.
    """
    status = (purchase.status or "").strip()
    if status in ("complete", "cancelled"):
        for lot in PurchaseLot.query.filter_by(purchase_id=purchase.id).filter(PurchaseLot.deleted_at.is_(None)).all():
            if (lot.remaining_weight_lbs or 0) > 0:
                lot.remaining_weight_lbs = 0.0
        return

    if status not in inventory_on_hand_statuses:
        return

    active_lots = PurchaseLot.query.filter_by(purchase_id=purchase.id).filter(PurchaseLot.deleted_at.is_(None)).all()
    if active_lots:
        return

    weight = float(purchase.actual_weight_lbs) if purchase.actual_weight_lbs is not None else float(purchase.stated_weight_lbs or 0)
    if weight <= 0:
        return

    db.session.add(PurchaseLot(
        purchase_id=purchase.id,
        strain_name="Purchase total",
        weight_lbs=weight,
        remaining_weight_lbs=weight,
        potency_pct=purchase.tested_potency_pct or purchase.stated_potency_pct,
    ))


def normalize_photo_category(raw: str, *, fallback: str = "other") -> str:
    category = (raw or "").strip().lower().replace(" ", "_")
    return category if category in ALLOWED_PHOTO_CATEGORIES else fallback


def photo_asset_exists(
    *,
    file_path: str,
    source_type: str,
    category: str,
    photo_context: str | None = None,
    submission_id: str | None = None,
    supplier_id: str | None = None,
    purchase_id: str | None = None,
) -> bool:
    query = PhotoAsset.query.filter(
        PhotoAsset.file_path == file_path,
        PhotoAsset.source_type == source_type,
        PhotoAsset.category == category,
    )
    if photo_context:
        query = query.filter(PhotoAsset.photo_context == photo_context)
    if submission_id:
        query = query.filter(PhotoAsset.submission_id == submission_id)
    if supplier_id:
        query = query.filter(PhotoAsset.supplier_id == supplier_id)
    if purchase_id:
        query = query.filter(PhotoAsset.purchase_id == purchase_id)
    return query.first() is not None


def create_photo_asset(
    file_path: str,
    *,
    source_type: str,
    category: str,
    photo_context: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    supplier_id: str | None = None,
    purchase_id: str | None = None,
    submission_id: str | None = None,
    uploaded_by: str | None = None,
) -> None:
    db.session.add(PhotoAsset(
        file_path=file_path,
        photo_context=(photo_context or "").strip() or None,
        source_type=source_type,
        category=category,
        tags=",".join([tag.strip().lower() for tag in (tags or []) if tag and tag.strip()]) or None,
        title=title,
        supplier_id=supplier_id,
        purchase_id=purchase_id,
        submission_id=submission_id,
        uploaded_by=uploaded_by,
    ))
