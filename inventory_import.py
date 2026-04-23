"""Spreadsheet -> Inventory lot update import: field metadata, header mapping, and staging helpers."""
from __future__ import annotations

from services.import_framework import (
    detect_header_row,
    load_tabular_upload,
    normalize_header_key,
    rows_from_mapping,
)


INVENTORY_IMPORT_FIELDS: dict[str, dict[str, str | bool]] = {
    "tracking_id": {"label": "Tracking ID", "section": "Match", "description": "Existing lot tracking ID.", "required": True},
    "strain_name": {"label": "Lot strain", "section": "Update", "description": "Replacement strain label for the lot."},
    "potency_pct": {"label": "Potency %", "section": "Update", "description": "Lot potency percentage."},
    "location": {"label": "Location", "section": "Update", "description": "Physical lot location."},
    "floor_state": {"label": "Floor state", "section": "Update", "description": "inventory, vault, reactor_staging, quarantine, or custom."},
    "milled": {"label": "Milled", "section": "Update", "description": "yes/no or milled/unmilled."},
    "notes": {"label": "Notes", "section": "Update", "description": "Lot-level notes."},
}
INVENTORY_IMPORT_FIELD_ORDER = list(INVENTORY_IMPORT_FIELDS.keys())


INVENTORY_IMPORT_HEADER_ALIASES: dict[str, str] = {}
_aliases_groups: dict[str, list[str]] = {
    "tracking_id": ["tracking_id", "tracking", "lot_tracking_id", "lot_id", "lot_tracking", "tag"],
    "strain_name": ["strain", "strain_name", "lot_strain", "cultivar", "variety"],
    "potency_pct": ["potency", "potency_pct", "lot_potency", "thca_pct"],
    "location": ["location", "lot_location", "bin", "storage_location"],
    "floor_state": ["floor_state", "lot_floor_state", "state", "movement_state"],
    "milled": ["milled", "prep_state", "milled_state", "prepared"],
    "notes": ["notes", "lot_notes", "inventory_notes", "comment", "comments"],
}
for _canon, _labels in _aliases_groups.items():
    for _lbl in _labels:
        INVENTORY_IMPORT_HEADER_ALIASES[_lbl] = _canon


def header_to_canonical(header: str | None) -> str | None:
    key = normalize_header_key(header)
    if not key:
        return None
    if key in INVENTORY_IMPORT_HEADER_ALIASES:
        return INVENTORY_IMPORT_HEADER_ALIASES[key]
    if key in INVENTORY_IMPORT_FIELDS:
        return key
    return None


def inventory_import_field_choices() -> list[dict[str, str]]:
    out = [{"value": "", "label": "Ignore this column"}]
    for key in INVENTORY_IMPORT_FIELD_ORDER:
        meta = INVENTORY_IMPORT_FIELDS[key]
        out.append({"value": key, "label": f"{meta['section']} - {meta['label']} ({key})"})
    return out


def _serialize_grid_row(row: list) -> list[str]:
    return ["" if cell is None else str(cell).strip() for cell in row]


def parse_inventory_spreadsheet_upload_for_mapping(filename: str, raw: bytes) -> dict:
    warnings: list[str] = []
    grid = load_tabular_upload(filename, raw)
    if not grid:
        raise ValueError("The file appears to be empty.")

    header_idx, mapped_headers = detect_header_row(grid, header_mapper=header_to_canonical, min_matches=2)
    if header_idx is None:
        raise ValueError("Could not detect a header row with recognizable inventory lot columns.")

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
    if "tracking_id" not in mapped_fields:
        raise ValueError("A tracking ID column is required (header such as Tracking ID, Lot ID, or Tag).")

    data_rows = [_serialize_grid_row(row) for row in grid[header_idx + 1 :]]
    preview_rows = inventory_import_rows_from_mapping(data_rows, mapping, header_idx)
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


def inventory_import_rows_from_mapping(data_rows: list[list[str]], mapping: dict[str, str], header_row_index: int) -> list[dict[str, str]]:
    indexed_mapping = {int(ci): field for ci, field in mapping.items() if field}
    return rows_from_mapping(
        data_rows,
        indexed_mapping,
        min_required_field="tracking_id",
        header_row_index=header_row_index,
    )
