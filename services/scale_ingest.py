from __future__ import annotations

from datetime import datetime, timezone

from flask_login import current_user
from models import ScaleDevice, WeightCapture

SCALE_INTERFACE_TYPES = ("rs232", "usb_serial", "tcp", "modbus_rtu", "modbus_tcp")
SCALE_SOURCE_MODES = ("manual", "device")
WEIGHT_CAPTURE_TYPES = ("intake", "allocation", "output", "adjustment")


def normalize_weight_unit(unit: str | None) -> str:
    value = (unit or "lb").strip().lower()
    aliases = {
        "lb": "lb",
        "lbs": "lb",
        "pound": "lb",
        "pounds": "lb",
        "g": "g",
        "gram": "g",
        "grams": "g",
        "kg": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
    }
    return aliases.get(value, "lb")


def parse_ascii_scale_payload(raw_payload: str) -> dict:
    """
    Minimal parser for common plain-text scale payloads.

    Expected examples:
    - "100.2 lb"
    - "ST,GS, 45.10 kg"
    - "WT: 23.4 lbs"
    """
    payload = (raw_payload or "").strip()
    if not payload:
        raise ValueError("Scale payload is empty.")

    pieces = payload.replace(",", " ").replace(":", " ").split()
    weight = None
    unit = "lb"
    for idx, piece in enumerate(pieces):
        try:
            weight = float(piece)
            if idx + 1 < len(pieces):
                unit = normalize_weight_unit(pieces[idx + 1])
            break
        except ValueError:
            continue
    if weight is None:
        raise ValueError("No numeric weight found in scale payload.")

    stable_tokens = {"st", "stable", "gs"}
    unstable_tokens = {"us", "motion", "unstable"}
    lowered = {part.strip().lower() for part in pieces}
    is_stable = True if lowered.intersection(stable_tokens) else (False if lowered.intersection(unstable_tokens) else None)
    return {
        "measured_weight": weight,
        "unit": unit,
        "is_stable": is_stable,
        "raw_payload": payload,
    }


def parse_scale_payload(*, protocol_type: str | None, raw_payload: str) -> dict:
    protocol = (protocol_type or "ascii").strip().lower()
    if protocol in {"ascii", "plain_text", "generic_ascii"}:
        return parse_ascii_scale_payload(raw_payload)
    raise ValueError(f"Unsupported scale protocol: {protocol}")


def create_weight_capture(
    root,
    *,
    capture_type: str,
    measured_weight: float,
    unit: str = "lb",
    source_mode: str = "manual",
    device=None,
    purchase=None,
    purchase_lot=None,
    run=None,
    raw_payload: str | None = None,
    is_stable: bool | None = None,
    notes: str | None = None,
):
    if capture_type not in WEIGHT_CAPTURE_TYPES:
        raise ValueError("Unsupported weight capture type.")
    if source_mode not in SCALE_SOURCE_MODES:
        raise ValueError("Unsupported weight source mode.")
    unit = normalize_weight_unit(unit)
    capture = WeightCapture(
        capture_type=capture_type,
        source_mode=source_mode,
        measured_weight=float(measured_weight),
        unit=unit,
        net_weight=float(measured_weight),
        raw_payload=raw_payload,
        is_stable=is_stable,
        notes=notes,
        accepted_at=datetime.now(timezone.utc),
        device_id=getattr(device, "id", None),
        purchase_id=getattr(purchase, "id", None),
        purchase_lot_id=getattr(purchase_lot, "id", None),
        run_id=getattr(run, "id", None),
        created_by=getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None,
    )
    root.db.session.add(capture)
    return capture


def capture_weight_from_device_payload(
    root,
    *,
    device: ScaleDevice,
    capture_type: str,
    raw_payload: str,
    purchase=None,
    purchase_lot=None,
    run=None,
    notes: str | None = None,
):
    parsed = parse_scale_payload(protocol_type=getattr(device, "protocol_type", None), raw_payload=raw_payload)
    capture = create_weight_capture(
        root,
        capture_type=capture_type,
        measured_weight=float(parsed["measured_weight"]),
        unit=parsed.get("unit") or "lb",
        source_mode="device",
        device=device,
        purchase=purchase,
        purchase_lot=purchase_lot,
        run=run,
        raw_payload=parsed.get("raw_payload") or raw_payload,
        is_stable=parsed.get("is_stable"),
        notes=notes,
    )
    return capture, parsed
