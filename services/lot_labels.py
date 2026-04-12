from __future__ import annotations

from urllib.parse import quote


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
    }


def build_purchase_label_payloads(purchase, *, external_scan_base: str | None = None) -> list[dict]:
    labels: list[dict] = []
    for lot in purchase.lots:
        if getattr(lot, "deleted_at", None) is not None:
            continue
        labels.append(build_lot_label_payload(lot, external_scan_base=external_scan_base))
    return labels
