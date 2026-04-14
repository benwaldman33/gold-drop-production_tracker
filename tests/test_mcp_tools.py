from __future__ import annotations

import json
from datetime import date, datetime, timezone

import app as app_module
from models import Purchase, PurchaseLot, Run, RunInput, Supplier, db, gen_uuid
from scripts.mcp_server import handle_request
from services.mcp_tools import execute_mcp_tool, list_mcp_tools


def test_mcp_tools_registry_exposes_core_tools():
    names = {tool["name"] for tool in list_mcp_tools()}
    assert "inventory_snapshot" in names
    assert "journey_resolve" in names
    assert "search_entities" in names


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
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id

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
