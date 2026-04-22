"""Spreadsheet -> Supplier import: field metadata, header mapping, and staging helpers."""
from __future__ import annotations

from services.import_framework import (
    detect_header_row,
    load_tabular_upload,
    normalize_header_key,
    rows_from_mapping,
)


SUPPLIER_IMPORT_FIELDS: dict[str, dict[str, str | bool]] = {
    "name": {"label": "Supplier name", "section": "Supplier", "description": "Farm or supplier name.", "required": True},
    "contact_name": {"label": "Contact name", "section": "Supplier", "description": "Primary supplier contact."},
    "contact_phone": {"label": "Contact phone", "section": "Supplier", "description": "Primary supplier phone number."},
    "contact_email": {"label": "Contact email", "section": "Supplier", "description": "Primary supplier email address."},
    "location": {"label": "Location", "section": "Supplier", "description": "City, region, or site location."},
    "notes": {"label": "Notes", "section": "Supplier", "description": "General supplier notes."},
    "is_active": {"label": "Active", "section": "Supplier", "description": "yes/no or true/false active flag."},
}
SUPPLIER_IMPORT_FIELD_ORDER = list(SUPPLIER_IMPORT_FIELDS.keys())


SUPPLIER_IMPORT_HEADER_ALIASES: dict[str, str] = {}
_aliases_groups: dict[str, list[str]] = {
    "name": ["supplier", "supplier_name", "farm", "farm_name", "vendor", "grower", "source", "name"],
    "contact_name": ["contact_name", "contact", "contact_person", "buyer", "rep"],
    "contact_phone": ["contact_phone", "phone", "phone_number", "mobile"],
    "contact_email": ["contact_email", "email", "email_address"],
    "location": ["location", "city", "region", "county", "site"],
    "notes": ["notes", "note", "comments", "comment", "description"],
    "is_active": ["is_active", "active", "enabled", "status_active"],
}
for _canon, _labels in _aliases_groups.items():
    for _lbl in _labels:
        SUPPLIER_IMPORT_HEADER_ALIASES[_lbl] = _canon


def header_to_canonical(header: str | None) -> str | None:
    key = normalize_header_key(header)
    if not key:
        return None
    if key in SUPPLIER_IMPORT_HEADER_ALIASES:
        return SUPPLIER_IMPORT_HEADER_ALIASES[key]
    if key in SUPPLIER_IMPORT_FIELDS:
        return key
    return None


def supplier_import_field_choices() -> list[dict[str, str]]:
    out = [{"value": "", "label": "Ignore this column"}]
    for key in SUPPLIER_IMPORT_FIELD_ORDER:
        meta = SUPPLIER_IMPORT_FIELDS[key]
        out.append({"value": key, "label": f"{meta['section']} - {meta['label']} ({key})"})
    return out


def _serialize_grid_row(row: list) -> list[str]:
    return ["" if cell is None else str(cell).strip() for cell in row]


def parse_supplier_spreadsheet_upload_for_mapping(filename: str, raw: bytes) -> dict:
    warnings: list[str] = []
    grid = load_tabular_upload(filename, raw)
    if not grid:
        raise ValueError("The file appears to be empty.")

    header_idx, mapped_headers = detect_header_row(grid, header_mapper=header_to_canonical, min_matches=1)
    if header_idx is None:
        raise ValueError("Could not detect a header row with recognizable supplier columns.")

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
        headers.append({"index": ci, "header": raw_header, "normalized": normalized, "suggested": suggested})
        if suggested:
            mapping[str(ci)] = suggested

    mapped_fields = {field for field in mapping.values() if field}
    if "name" not in mapped_fields:
        raise ValueError("A supplier name column is required (header such as Supplier, Farm, Vendor, or Name).")

    data_rows = [_serialize_grid_row(row) for row in grid[header_idx + 1 :]]
    preview_rows = supplier_import_rows_from_mapping(data_rows, mapping, header_idx)
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


def supplier_import_rows_from_mapping(data_rows: list[list[str]], mapping: dict[str, str], header_row_index: int) -> list[dict[str, str]]:
    indexed_mapping = {int(ci): field for ci, field in mapping.items() if field}
    return rows_from_mapping(
        data_rows,
        indexed_mapping,
        min_required_field="name",
        header_row_index=header_row_index,
    )
