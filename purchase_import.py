"""Spreadsheet -> Purchase import: field metadata, header mapping, and staging helpers."""
from __future__ import annotations

from services.import_framework import (
    detect_header_row,
    load_tabular_upload,
    normalize_header_key,
    rows_from_mapping,
)


PURCHASE_IMPORT_FIELDS: dict[str, dict[str, str | bool]] = {
    "supplier": {"label": "Supplier", "section": "Purchase", "description": "Supplier or farm name.", "required": True},
    "purchase_date": {"label": "Purchase date", "section": "Purchase", "description": "Order or purchase date.", "required": True},
    "paid_date": {"label": "Paid date", "section": "Purchase", "description": "Fallback date if purchase date is blank."},
    "purchase_week": {"label": "Purchase week", "section": "Purchase", "description": "Accounting or reporting week label."},
    "payment_method": {"label": "Payment method", "section": "Purchase", "description": "ACH, wire, check, or other payment label."},
    "total_cost": {"label": "Total cost", "section": "Purchase", "description": "Invoice total or amount paid."},
    "stated_weight_lbs": {"label": "Stated weight (lbs)", "section": "Purchase", "description": "Invoice or stated biomass weight.", "required": True},
    "actual_weight_lbs": {"label": "Actual weight (lbs)", "section": "Purchase", "description": "Actual delivered weight."},
    "batch_id": {"label": "Batch ID", "section": "Purchase", "description": "Batch, manifest, or lot identifier."},
    "delivery_date": {"label": "Delivery date", "section": "Purchase", "description": "Expected or actual delivery date."},
    "status": {"label": "Status", "section": "Purchase", "description": "Purchase status such as ordered or delivered."},
    "stated_potency_pct": {"label": "Stated potency %", "section": "Purchase", "description": "Declared potency percentage."},
    "tested_potency_pct": {"label": "Tested potency %", "section": "Purchase", "description": "Lab-tested potency percentage."},
    "price_per_lb": {"label": "Price per lb", "section": "Purchase", "description": "Purchase price per pound."},
    "harvest_date": {"label": "Harvest date", "section": "Purchase", "description": "Harvest date if known."},
    "storage_note": {"label": "Storage note", "section": "Purchase", "description": "Storage or handling note."},
    "license_info": {"label": "License info", "section": "Purchase", "description": "License or compliance text."},
    "coa_status_text": {"label": "Testing / COA status", "section": "Purchase", "description": "Testing or COA status text."},
    "notes": {"label": "General notes", "section": "Purchase", "description": "General purchase notes."},
    "testing_notes": {"label": "Testing notes", "section": "Purchase", "description": "Detailed testing notes."},
    "delivery_notes": {"label": "Delivery notes", "section": "Purchase", "description": "Delivery-specific notes."},
    "queue_placement": {"label": "Queue placement", "section": "Purchase", "description": "Aggregate, indoor, or outdoor."},
    "clean_or_dirty": {"label": "Clean or dirty", "section": "Purchase", "description": "Clean or dirty classification."},
    "indoor_outdoor": {"label": "Indoor / outdoor", "section": "Purchase", "description": "Indoor, outdoor, mixed light, or greenhouse."},
    "availability_date": {"label": "Availability date", "section": "Pipeline", "description": "Date biomass first became available."},
    "declared_weight_lbs": {"label": "Declared weight (lbs)", "section": "Pipeline", "description": "Initial supplier-declared biomass weight."},
    "declared_price_per_lb": {"label": "Declared price per lb", "section": "Pipeline", "description": "Initial quoted price per pound."},
    "testing_timing": {"label": "Testing timing", "section": "Pipeline", "description": "before_delivery or after_delivery."},
    "testing_status": {"label": "Testing status", "section": "Pipeline", "description": "pending, completed, or not_needed."},
    "testing_date": {"label": "Testing date", "section": "Pipeline", "description": "Date biomass testing completed."},
    "strain": {"label": "Lot strain", "section": "Lot", "description": "Strain name for the lot created from this purchase."},
    "lot_weight_lbs": {"label": "Lot weight (lbs)", "section": "Lot", "description": "Optional explicit lot weight; defaults to purchase weight."},
    "lot_potency_pct": {"label": "Lot potency %", "section": "Lot", "description": "Lot-specific potency percentage."},
    "lot_milled": {"label": "Lot milled", "section": "Lot", "description": "Whether the lot is already milled."},
    "lot_floor_state": {"label": "Lot floor state", "section": "Lot", "description": "Inventory, reactor_staging, in_reactor, or another floor state."},
    "lot_location": {"label": "Lot location", "section": "Lot", "description": "Physical lot location."},
    "lot_notes": {"label": "Lot notes", "section": "Lot", "description": "Lot-level notes."},
}
PURCHASE_IMPORT_FIELD_ORDER = list(PURCHASE_IMPORT_FIELDS.keys())


PURCHASE_IMPORT_HEADER_ALIASES: dict[str, str] = {}
_aliases_groups: dict[str, list[str]] = {
    "supplier": [
        "supplier", "farm", "source", "vendor", "grower", "supplier_name", "producer", "seller", "farm_name",
    ],
    "purchase_date": ["purchase_date", "date", "order_date", "po_date", "purchase", "buy_date"],
    "paid_date": ["paid_date", "pay_date", "date_paid", "payment_date"],
    "purchase_week": ["week", "fiscal_week", "report_week", "budget_week", "purchase_week"],
    "payment_method": ["payment_method", "pay_method", "payment_type"],
    "total_cost": [
        "total_cost", "amount", "total_amount", "invoice_amount", "paid_amount", "cost", "payment_total",
    ],
    "stated_weight_lbs": [
        "stated_weight_lbs", "weight_lbs", "lbs", "stated_lbs", "quantity_lbs", "weight", "est_weight_lbs",
        "biomass_lbs", "total_lbs", "pounds", "qty_lbs", "invoice_weight",
    ],
    "actual_weight_lbs": [
        "actual_weight_lbs", "actual_lbs", "received_lbs", "received_weight_lbs", "net_weight_lbs", "actual_weight",
    ],
    "batch_id": ["batch_id", "batch", "batchid", "manifest", "manifest_id", "lot_id", "tag"],
    "delivery_date": ["delivery_date", "expected_delivery", "ship_date", "eta", "delivery", "expected_delivery_date"],
    "status": ["status", "purchase_status", "order_status"],
    "stated_potency_pct": [
        "stated_potency_pct", "potency", "thc_pct", "stated_potency", "pct_potency", "estimated_potency",
        "est_potency", "potency_pct", "thca_pct",
    ],
    "tested_potency_pct": ["tested_potency_pct", "tested_potency", "lab_potency", "coa_potency"],
    "price_per_lb": ["price_per_lb", "price_lb", "cost_per_lb", "pp_lb", "per_lb"],
    "harvest_date": ["harvest_date", "harvest"],
    "storage_note": ["storage_note", "storage", "warehouse_note"],
    "license_info": ["license_info", "license", "licence", "license_number"],
    "coa_status_text": ["coa_status_text", "coa_status", "coa", "testing_status_text"],
    "notes": ["notes", "note", "comment", "comments", "description"],
    "testing_notes": ["testing_notes", "lab_notes", "coa_notes"],
    "delivery_notes": ["delivery_notes", "dock_notes", "receiving_notes"],
    "queue_placement": ["queue_placement", "queue", "placement"],
    "clean_or_dirty": ["clean_or_dirty", "clean_dirty"],
    "indoor_outdoor": ["indoor_outdoor", "grow_type", "cultivation"],
    "availability_date": ["availability_date", "available_date"],
    "declared_weight_lbs": ["declared_weight_lbs", "declared_lbs", "declared_weight"],
    "declared_price_per_lb": ["declared_price_per_lb", "declared_pp_lb", "quoted_price_per_lb", "quoted_pp_lb"],
    "testing_timing": ["testing_timing"],
    "testing_status": ["testing_status"],
    "testing_date": ["testing_date", "lab_date", "coa_date"],
    "strain": ["strain", "strain_name", "variety", "cultivar", "strain_s"],
    "lot_weight_lbs": ["lot_weight_lbs", "lot_lbs", "strain_weight_lbs"],
    "lot_potency_pct": ["lot_potency_pct", "lot_potency"],
    "lot_milled": ["lot_milled", "milled"],
    "lot_floor_state": ["lot_floor_state", "floor_state"],
    "lot_location": ["lot_location", "location"],
    "lot_notes": ["lot_notes", "inventory_notes"],
}
for _canon, _labels in _aliases_groups.items():
    for _lbl in _labels:
        PURCHASE_IMPORT_HEADER_ALIASES[_lbl] = _canon


def header_to_canonical(header: str | None) -> str | None:
    key = normalize_header_key(header)
    if not key:
        return None
    if key in PURCHASE_IMPORT_HEADER_ALIASES:
        return PURCHASE_IMPORT_HEADER_ALIASES[key]
    if key in PURCHASE_IMPORT_FIELDS:
        return key
    return None


def purchase_import_field_choices() -> list[dict[str, str]]:
    out = [{"value": "", "label": "Ignore this column"}]
    for key in PURCHASE_IMPORT_FIELD_ORDER:
        meta = PURCHASE_IMPORT_FIELDS[key]
        out.append(
            {
                "value": key,
                "label": f"{meta['section']} - {meta['label']} ({key})",
            }
        )
    return out


def _serialize_grid_row(row: list) -> list[str]:
    return ["" if cell is None else str(cell).strip() for cell in row]


def parse_purchase_spreadsheet_upload(filename: str, raw: bytes) -> tuple[list[dict[str, str]], list[str]]:
    staged = parse_purchase_spreadsheet_upload_for_mapping(filename, raw)
    rows = purchase_import_rows_from_mapping(staged["data_rows"], staged["mapping"], staged["header_row_index"])
    return rows, staged["warnings"]


def parse_purchase_spreadsheet_upload_for_mapping(filename: str, raw: bytes) -> dict:
    warnings: list[str] = []
    grid = load_tabular_upload(filename, raw)
    if not grid:
        raise ValueError("The file appears to be empty.")

    header_idx, mapped_headers = detect_header_row(grid, header_mapper=header_to_canonical, min_matches=2)
    if header_idx is None:
        raise ValueError(
            "Could not detect a header row with recognizable columns. "
            "Include at least columns for supplier (or Farm/Source) and purchase date or weight."
        )

    header_row = grid[header_idx]
    headers: list[dict[str, object]] = []
    mapping: dict[str, str] = {}
    mapped_by_index = {int(item["index"]): str(item["suggested"]) for item in mapped_headers}
    for ci, cell in enumerate(header_row):
        raw_header = "" if cell is None else str(cell).strip()
        if not raw_header:
            continue
        normalized = normalize_header_key(raw_header)
        suggested = mapped_by_index.get(ci) or ""
        headers.append(
            {
                "index": ci,
                "header": raw_header,
                "normalized": normalized,
                "suggested": suggested,
            }
        )
        if suggested:
            mapping[str(ci)] = suggested

    mapped_fields = {field for field in mapping.values() if field}
    if "supplier" not in mapped_fields:
        raise ValueError("A supplier column is required (header such as Supplier, Farm, or Source).")
    if "purchase_date" not in mapped_fields and "stated_weight_lbs" not in mapped_fields and "actual_weight_lbs" not in mapped_fields:
        warnings.append("No purchase date or weight column detected; rows may fail validation.")

    data_rows = [_serialize_grid_row(row) for row in grid[header_idx + 1 :]]
    preview_rows = purchase_import_rows_from_mapping(data_rows, mapping, header_idx)
    if not preview_rows:
        raise ValueError("No data rows found below the header.")
    if len(preview_rows) > 2000:
        raise ValueError("Maximum 2000 data rows per upload; split the file and try again.")

    return {
        "filename": filename,
        "warnings": warnings,
        "header_row_index": header_idx,
        "headers": headers,
        "mapping": mapping,
        "data_rows": data_rows,
    }


def purchase_import_rows_from_mapping(data_rows: list[list[str]], mapping: dict[str, str], header_row_index: int) -> list[dict[str, str]]:
    indexed_mapping = {int(ci): field for ci, field in mapping.items() if field}
    return rows_from_mapping(
        data_rows,
        indexed_mapping,
        min_required_field="supplier",
        header_row_index=header_row_index,
    )
