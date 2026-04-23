"""Spreadsheet -> Strain rename import built on purchase lots."""
from __future__ import annotations

from services.import_framework import (
    detect_header_row,
    load_tabular_upload,
    normalize_header_key,
    rows_from_mapping,
)


STRAIN_IMPORT_FIELDS: dict[str, dict[str, str | bool]] = {
    "supplier_name": {"label": "Supplier name", "section": "Match", "description": "Supplier / farm name for the existing strain rows.", "required": True},
    "current_strain_name": {"label": "Current strain name", "section": "Match", "description": "Existing strain name to match on purchase lots.", "required": True},
    "new_strain_name": {"label": "New strain name", "section": "Rename", "description": "Replacement strain name to apply to matching lots.", "required": True},
    "notes": {"label": "Notes", "section": "Context", "description": "Optional import note for review only."},
}
STRAIN_IMPORT_FIELD_ORDER = list(STRAIN_IMPORT_FIELDS.keys())


STRAIN_IMPORT_HEADER_ALIASES: dict[str, str] = {}
_aliases_groups: dict[str, list[str]] = {
    "supplier_name": ["supplier", "supplier_name", "farm", "farm_name", "vendor", "source"],
    "current_strain_name": ["current_strain", "strain", "strain_name", "old_strain", "existing_strain"],
    "new_strain_name": ["new_strain", "new_strain_name", "rename_to", "target_strain", "updated_strain"],
    "notes": ["notes", "note", "comments", "comment"],
}
for _canon, _labels in _aliases_groups.items():
    for _lbl in _labels:
        STRAIN_IMPORT_HEADER_ALIASES[_lbl] = _canon


def header_to_canonical(header: str | None) -> str | None:
    key = normalize_header_key(header)
    if not key:
        return None
    if key in STRAIN_IMPORT_HEADER_ALIASES:
        return STRAIN_IMPORT_HEADER_ALIASES[key]
    if key in STRAIN_IMPORT_FIELDS:
        return key
    return None


def strain_import_field_choices() -> list[dict[str, str]]:
    out = [{"value": "", "label": "Ignore this column"}]
    for key in STRAIN_IMPORT_FIELD_ORDER:
        meta = STRAIN_IMPORT_FIELDS[key]
        out.append({"value": key, "label": f"{meta['section']} - {meta['label']} ({key})"})
    return out


def _serialize_grid_row(row: list) -> list[str]:
    return ["" if cell is None else str(cell).strip() for cell in row]


def parse_strain_spreadsheet_upload_for_mapping(filename: str, raw: bytes) -> dict:
    warnings: list[str] = []
    grid = load_tabular_upload(filename, raw)
    if not grid:
        raise ValueError("The file appears to be empty.")

    header_idx, mapped_headers = detect_header_row(grid, header_mapper=header_to_canonical, min_matches=2)
    if header_idx is None:
        raise ValueError("Could not detect a header row with recognizable strain rename columns.")

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
    if not {"supplier_name", "current_strain_name", "new_strain_name"}.issubset(mapped_fields):
        raise ValueError("Supplier name, current strain name, and new strain name columns are required.")

    data_rows = [_serialize_grid_row(row) for row in grid[header_idx + 1 :]]
    preview_rows = strain_import_rows_from_mapping(data_rows, mapping, header_idx)
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


def strain_import_rows_from_mapping(data_rows: list[list[str]], mapping: dict[str, str], header_row_index: int) -> list[dict[str, str]]:
    indexed_mapping = {int(ci): field for ci, field in mapping.items() if field}
    return rows_from_mapping(
        data_rows,
        indexed_mapping,
        min_required_field="supplier_name",
        header_row_index=header_row_index,
    )
