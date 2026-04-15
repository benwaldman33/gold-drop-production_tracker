from __future__ import annotations

import json
from datetime import date, datetime, timezone

import app as app_module
from models import LotScanEvent, Purchase, PurchaseLot, RemoteSite, Run, RunInput, Supplier, db, gen_uuid
from scripts.mcp_server import handle_request
from services.mcp_tools import execute_mcp_tool, list_mcp_tools


def test_mcp_tools_registry_exposes_core_tools():
    names = {tool["name"] for tool in list_mcp_tools()}
    assert "inventory_snapshot" in names
    assert "journey_resolve" in names
    assert "search_entities" in names
    assert "cross_site_summary" in names
    assert "scanner_summary" in names
    assert "lot_scan_history" in names
    assert "scale_devices" in names
    assert "weight_capture_summary" in names


def test_mcp_server_handles_initialize_and_tools_list():
    init_response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_response["result"]["serverInfo"]["name"] == "gold-drop-mcp"

    list_response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
    assert "open_lots" in tool_names
    assert "run_journey" in tool_names


def test_mcp_tool_execution_returns_inventory_and_journey_payloads():
    app = app_module.app
    supplier = Supplier(name=f"MCP Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        delivery_date=date(2026, 4, 13),
        status="delivered",
        stated_weight_lbs=90,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"MCP-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="MCP Dream", weight_lbs=90, remaining_weight_lbs=50)
    run = Run(
        run_date=date(2026, 4, 14),
        reactor_number=7,
        bio_in_reactor_lbs=40,
        dry_hte_g=9,
        dry_thca_g=17,
        notes="mcp run",
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.flush()
        db.session.add(run)
        db.session.flush()
        run_input = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40, allocation_source="manual")
        db.session.add(run_input)
        scan_event = LotScanEvent(lot_id=lot.id, tracking_id_snapshot=lot.tracking_id, action="scan_open")
        scale_device = app_module.ScaleDevice(
            name=f"MCP Scale {gen_uuid()[:8]}",
            location="Lab",
            interface_type="rs232",
            protocol_type="ascii",
            connection_target="COM11",
            is_active=True,
        )
        db.session.add(scale_device)
        db.session.flush()
        weight_capture = app_module.WeightCapture(
            capture_type="allocation",
            source_mode="device",
            measured_weight=40,
            unit="lb",
            net_weight=40,
            device_id=scale_device.id,
            raw_payload="ST,GS, 40.0 lb",
        )
        db.session.add(scan_event)
        db.session.add(weight_capture)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id
        scan_event_id = scan_event.id
        scale_device_id = scale_device.id
        weight_capture_id = weight_capture.id

    try:
        inventory_payload = execute_mcp_tool("inventory_snapshot", {"supplier_id": supplier_id, "limit": 10})
        assert inventory_payload["summary"]["open_lot_count"] >= 1
        assert any(item["id"] == lot_id for item in inventory_payload["lots"])

        journey_payload = execute_mcp_tool("journey_resolve", {"entity_type": "run", "entity_id": run_id})
        assert journey_payload["entity_type"] == "run"
        assert journey_payload["journey"]["run_id"] == run_id

        search_payload = execute_mcp_tool("search_entities", {"q": "mcp", "types": ["purchases", "runs"], "limit": 10})
        entity_types = {item["entity_type"] for item in search_payload["results"]}
        assert "purchase" in entity_types
        assert "run" in entity_types

        scanner_summary = execute_mcp_tool("scanner_summary", {})
        assert scanner_summary["total_events"] >= 1
        assert scanner_summary["action_counts"]["scan_open"] >= 1

        scan_history = execute_mcp_tool("lot_scan_history", {"lot_id": lot_id, "limit": 10})
        assert scan_history["results"][0]["lot_id"] == lot_id
        assert scan_history["results"][0]["action"] == "scan_open"

        scales_payload = execute_mcp_tool("scale_devices", {"limit": 10})
        assert any(item["id"] == scale_device_id for item in scales_payload["results"])

        captures_payload = execute_mcp_tool("weight_capture_summary", {"device_id": scale_device_id, "limit": 10})
        assert captures_payload["summary"]["device_capture_count"] >= 1
        assert captures_payload["results"][0]["id"] == weight_capture_id

        call_response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "lot_journey", "arguments": {"lot_id": lot_id}},
            }
        )
        assert call_response["result"]["isError"] is False
        structured = call_response["result"]["structuredContent"]
        assert structured["lot_id"] == lot_id
        assert json.loads(call_response["result"]["content"][0]["text"])["lot_id"] == lot_id
    finally:
        with app.app_context():
            run_input = db.session.get(RunInput, run_input_id)
            if run_input:
                db.session.delete(run_input)
            run_obj = db.session.get(Run, run_id)
            if run_obj:
                db.session.delete(run_obj)
            scan_event = db.session.get(LotScanEvent, scan_event_id)
            if scan_event:
                db.session.delete(scan_event)
            weight_capture = db.session.get(app_module.WeightCapture, weight_capture_id)
            if weight_capture:
                db.session.delete(weight_capture)
            scale_device = db.session.get(app_module.ScaleDevice, scale_device_id)
            if scale_device:
                db.session.delete(scale_device)
            lot_obj = db.session.get(PurchaseLot, lot_id)
            if lot_obj:
                db.session.delete(lot_obj)
            purchase_obj = db.session.get(Purchase, purchase_id)
            if purchase_obj:
                db.session.delete(purchase_obj)
            supplier_obj = db.session.get(Supplier, supplier_id)
            if supplier_obj:
                db.session.delete(supplier_obj)
            db.session.commit()


def test_mcp_tool_execution_supports_dashboard_and_cross_site_reads():
    app = app_module.app
    with app.app_context():
        remote_site = RemoteSite(
            name=f"MCP Remote {gen_uuid()[:8]}",
            base_url=f"https://mcp-{gen_uuid()[:8]}.example.com",
            site_code="MCPR",
            site_name="MCP Remote Site",
            site_region="Nevada",
            site_environment="production",
            is_active=True,
            last_pull_status="success",
        )
        remote_site.set_payload("last_dashboard_payload_json", {"totals": {"total_runs": 3, "total_lbs": 120.0, "total_dry_output_g": 21.0}})
        remote_site.set_payload("last_inventory_payload_json", {"total_on_hand_lbs": 88.0})
        remote_site.set_payload("last_exceptions_payload_json", {"total_exceptions": 1})
        remote_site.set_payload("last_slack_payload_json", {"total_messages": 4})
        remote_site.set_payload("last_suppliers_payload_json", [{"supplier": {"name": "Remote Farmlane"}, "all_time": {"runs": 2}}])
        remote_site.set_payload("last_strains_payload_json", [{"strain_name": "Remote Dream", "supplier_name": "Remote Farmlane", "view": "all"}])
        db.session.add(remote_site)
        db.session.commit()
        remote_site_id = remote_site.id

    try:
        site_payload = execute_mcp_tool("site_identity", {})
        assert "site_code" in site_payload

        dashboard_payload = execute_mcp_tool("dashboard_summary", {"period": "30"})
        assert "totals" in dashboard_payload

        remote_payload = execute_mcp_tool("remote_sites", {"limit": 10})
        assert any(site["id"] == remote_site_id for site in remote_payload["sites"])

        cross_site_payload = execute_mcp_tool("cross_site_summary", {"period": "30"})
        assert cross_site_payload["sites_total"] >= 2

        supplier_compare = execute_mcp_tool("cross_site_supplier_compare", {"q": "remote", "limit": 10})
        assert any(row["site"]["source"] == "remote_cache" for row in supplier_compare["results"])

        strain_compare = execute_mcp_tool("cross_site_strain_compare", {"q": "remote", "limit": 10})
        assert any(row["site"]["source"] == "remote_cache" for row in strain_compare["results"])
    finally:
        with app.app_context():
            remote_site = db.session.get(RemoteSite, remote_site_id)
            if remote_site:
                db.session.delete(remote_site)
            db.session.commit()
