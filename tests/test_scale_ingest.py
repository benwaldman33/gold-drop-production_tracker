"""Scale ingest guardrail tests."""

from __future__ import annotations

import pytest

from services.scale_ingest import SCALE_INTERFACE_TYPES, SCALE_PROTOCOL_TYPES, parse_scale_payload


def test_scale_interface_types_exclude_unimplemented_transport_options():
    assert "rs232" in SCALE_INTERFACE_TYPES
    assert "usb_serial" in SCALE_INTERFACE_TYPES
    assert "tcp" not in SCALE_INTERFACE_TYPES
    assert "modbus_rtu" not in SCALE_INTERFACE_TYPES
    assert "modbus_tcp" not in SCALE_INTERFACE_TYPES


@pytest.mark.parametrize("protocol_type", SCALE_PROTOCOL_TYPES)
def test_parse_scale_payload_accepts_supported_protocol_types(protocol_type: str):
    parsed = parse_scale_payload(protocol_type=protocol_type, raw_payload="ST,GS, 10.5 lb")
    assert float(parsed["measured_weight"]) == 10.5
    assert parsed["unit"] == "lb"


def test_parse_scale_payload_rejects_unsupported_protocol_type():
    with pytest.raises(ValueError, match="Unsupported scale protocol"):
        parse_scale_payload(protocol_type="modbus_tcp", raw_payload="10.0")
