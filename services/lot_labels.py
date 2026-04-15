from __future__ import annotations

from urllib.parse import quote


CODE39_PATTERNS = {
    "0": "nnnwwnwnn",
    "1": "wnnwnnnnw",
    "2": "nnwwnnnnw",
    "3": "wnwwnnnnn",
    "4": "nnnwwnnnw",
    "5": "wnnwwnnnn",
    "6": "nnwwwnnnn",
    "7": "nnnwnnwnw",
    "8": "wnnwnnwnn",
    "9": "nnwwnnwnn",
    "A": "wnnnnwnnw",
    "B": "nnwnnwnnw",
    "C": "wnwnnwnnn",
    "D": "nnnnwwnnw",
    "E": "wnnnwwnnn",
    "F": "nnwnwwnnn",
    "G": "nnnnnwwnw",
    "H": "wnnnnwwnn",
    "I": "nnwnnwwnn",
    "J": "nnnnwwwnn",
    "K": "wnnnnnnww",
    "L": "nnwnnnnww",
    "M": "wnwnnnnwn",
    "N": "nnnnwnnww",
    "O": "wnnnwnnwn",
    "P": "nnwnwnnwn",
    "Q": "nnnnnnwww",
    "R": "wnnnnnwwn",
    "S": "nnwnnnwwn",
    "T": "nnnnwnwwn",
    "U": "wwnnnnnnw",
    "V": "nwwnnnnnw",
    "W": "wwwnnnnnn",
    "X": "nwnnwnnnw",
    "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn",
    "-": "nwnnnnwnw",
    ".": "wwnnnnwnn",
    " ": "nwwnnnwnn",
    "$": "nwnwnwnnn",
    "/": "nwnwnnnwn",
    "+": "nwnnnwnwn",
    "%": "nnnwnwnwn",
    "*": "nwnnwnwnn",
}


def _normalize_code39_value(value: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        return "LOT"
    safe_chars: list[str] = []
    for char in normalized:
        safe_chars.append(char if char in CODE39_PATTERNS and char != "*" else "-")
    return "".join(safe_chars)


def render_code39_svg(value: str, *, height: int = 88, include_text: bool = True) -> str:
    encoded = f"*{_normalize_code39_value(value)}*"
    narrow = 3
    wide = 7
    gap = narrow
    quiet_zone = 12
    text_space = 24 if include_text else 0
    bar_height = height
    parts: list[str] = []
    cursor = quiet_zone

    for char_index, char in enumerate(encoded):
        pattern = CODE39_PATTERNS[char]
        for idx, width_flag in enumerate(pattern):
            width = wide if width_flag == "w" else narrow
            if idx % 2 == 0:
                parts.append(
                    f'<rect x="{cursor}" y="0" width="{width}" height="{bar_height}" fill="#111111" />'
                )
            cursor += width
        if char_index < len(encoded) - 1:
            cursor += gap

    total_width = cursor + quiet_zone
    text_y = bar_height + 16
    text_markup = ""
    if include_text:
        human_value = _normalize_code39_value(value)
        text_markup = (
            f'<text x="{total_width / 2:.1f}" y="{text_y}" text-anchor="middle" '
            'font-family="IBM Plex Mono, monospace" font-size="14" fill="#111111">'
            f"{human_value}</text>"
        )
    total_height = bar_height + text_space
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width} {total_height}" '
        f'role="img" aria-label="Code 39 barcode for {_normalize_code39_value(value)}">'
        '<rect width="100%" height="100%" fill="#ffffff" />'
        f'{"".join(parts)}'
        f"{text_markup}"
        "</svg>"
    )


def build_lot_label_payload(lot, *, external_scan_base: str | None = None) -> dict:
    tracking_id = getattr(lot, "tracking_id", None) or getattr(lot, "id", "")
    scan_path = f"/scan/lot/{quote(tracking_id)}"
    scan_url = f"{external_scan_base.rstrip('/')}{scan_path}" if external_scan_base else scan_path
    return {
        "lot_id": getattr(lot, "id", None),
        "tracking_id": tracking_id,
        "barcode_value": getattr(lot, "barcode_value", None) or tracking_id,
        "qr_value": getattr(lot, "qr_value", None) or scan_path,
        "scan_path": scan_path,
        "scan_url": scan_url,
        "batch_id": getattr(getattr(lot, "purchase", None), "batch_id", None),
        "supplier_name": getattr(lot, "supplier_name", None),
        "strain_name": getattr(lot, "strain_name", None),
        "weight_lbs": float(getattr(lot, "weight_lbs", 0) or 0),
        "remaining_weight_lbs": float(getattr(lot, "remaining_weight_lbs", 0) or 0),
        "potency_pct": getattr(lot, "potency_pct", None),
        "clean_or_dirty": getattr(getattr(lot, "purchase", None), "clean_or_dirty", None),
        "testing_status": getattr(getattr(lot, "purchase", None), "testing_status", None),
        "label_version": getattr(lot, "label_version", None),
        "barcode_format": "code39",
        "barcode_svg": render_code39_svg(getattr(lot, "barcode_value", None) or tracking_id),
    }


def build_purchase_label_payloads(purchase, *, external_scan_base: str | None = None) -> list[dict]:
    labels: list[dict] = []
    for lot in purchase.lots:
        if getattr(lot, "deleted_at", None) is not None:
            continue
        labels.append(build_lot_label_payload(lot, external_scan_base=external_scan_base))
    return labels
