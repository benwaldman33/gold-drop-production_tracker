from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import ApiClient, Purchase, PurchaseLot, Run, RunInput, SlackIngestedMessage, Supplier, SystemSetting, db, gen_uuid
from services.api_auth import hash_api_token


def _make_api_headers(*scopes: str):
    token = f"tok-{gen_uuid()}"
    app = app_module.app
    with app.app_context():
        client = ApiClient(name=f"test-{gen_uuid()[:8]}", token_hash=hash_api_token(token))
        client.set_scopes(list(scopes))
        db.session.add(client)
        db.session.commit()
        client_id = client.id
    return {"Authorization": f"Bearer {token}"}, client_id


def test_api_v1_site_requires_token():
    app = app_module.app
    with app.test_client() as client:
        response = client.get("/api/v1/site")
    assert response.status_code == 401
    payload = response.get_json()
    assert payload["error"]["code"] == "unauthorized"


def test_api_v1_capabilities_requires_site_scope_and_returns_discovery_payload():
    app = app_module.app
    bad_headers, bad_client_id = _make_api_headers("read:lots")
    good_headers, good_client_id = _make_api_headers("read:site")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/capabilities", headers=bad_headers)
            assert forbidden.status_code == 403

            response = client.get("/api/v1/capabilities", headers=good_headers)
            assert response.status_code == 200
            payload = response.get_json()["data"]
            assert payload["authentication"]["scheme"] == "bearer"
            assert "read:dashboard" in payload["scopes"]
            paths = {item["path"] for item in payload["endpoints"]}
            assert "/api/v1/site" in paths
            assert "/api/v1/summary/dashboard" in paths
            assert "/api/v1/summary/exceptions" in paths
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            db.session.commit()


def test_api_v1_dashboard_summary_requires_scope_and_returns_payload():
    app = app_module.app
    bad_headers, bad_client_id = _make_api_headers("read:site")
    good_headers, good_client_id = _make_api_headers("read:dashboard")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/summary/dashboard?period=30", headers=bad_headers)
            assert forbidden.status_code == 403

            response = client.get("/api/v1/summary/dashboard?period=30", headers=good_headers)
            assert response.status_code == 200
            payload = response.get_json()["data"]
            assert payload["period"] == "30"
            assert "totals" in payload
            assert "kpis" in payload
            assert "weekly_finance" in payload

            bad_period = client.get("/api/v1/summary/dashboard?period=bad", headers=good_headers)
            assert bad_period.status_code == 400
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            db.session.commit()


def test_api_v1_departments_list_and_detail():
    app = app_module.app
    headers, client_id = _make_api_headers("read:dashboard")
    try:
        with app.test_client() as client:
            list_res = client.get("/api/v1/departments", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()["data"]
            slugs = {item["slug"] for item in list_payload}
            assert {"operations", "purchasing", "quality"}.issubset(slugs)

            detail_res = client.get("/api/v1/departments/operations", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["slug"] == "operations"
            assert detail_payload["title"] == "Operations"
            assert detail_payload["sections"]

            missing_res = client.get("/api/v1/departments/missing", headers=headers)
            assert missing_res.status_code == 404
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            db.session.commit()


def test_api_v1_search_requires_scope_and_returns_entity_matches():
    app = app_module.app
    supplier = Supplier(name=f"Searchable Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 5),
        delivery_date=date(2026, 4, 6),
        status="delivered",
        stated_weight_lbs=80,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"SEARCH-{gen_uuid()[:6]}",
        notes="search alpha batch",
    )
    lot = PurchaseLot(strain_name="Search Dream", weight_lbs=80, remaining_weight_lbs=40)
    run = Run(
        run_date=date(2026, 4, 8),
        reactor_number=3,
        bio_in_reactor_lbs=40,
        notes="search alpha run",
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
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id

    bad_headers, bad_client_id = _make_api_headers("read:site")
    good_headers, good_client_id = _make_api_headers("read:search")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/search?q=alpha", headers=bad_headers)
            assert forbidden.status_code == 403

            response = client.get("/api/v1/search?q=alpha", headers=good_headers)
            assert response.status_code == 200
            payload = response.get_json()["data"]
            entity_types = {item["entity_type"] for item in payload["results"]}
            assert "purchase" in entity_types
            assert "run" in entity_types

            supplier_res = client.get("/api/v1/search?q=Searchable&types=suppliers", headers=good_headers)
            assert supplier_res.status_code == 200
            supplier_payload = supplier_res.get_json()["data"]
            assert supplier_payload["results"][0]["entity_type"] == "supplier"

            lot_res = client.get("/api/v1/search?q=Search&types=lots", headers=good_headers)
            assert lot_res.status_code == 200
            lot_payload = lot_res.get_json()["data"]
            lot_ids = {item["entity_id"] for item in lot_payload["results"]}
            assert lot_id in lot_ids

            missing_q = client.get("/api/v1/search", headers=good_headers)
            assert missing_q.status_code == 400
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
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


def test_api_v1_tools_scope_and_semantic_endpoints():
    app = app_module.app
    supplier = Supplier(name=f"Tool Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 5),
        delivery_date=date(2026, 4, 6),
        status="delivered",
        stated_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"TOOL-{gen_uuid()[:6]}",
        notes="tool layer purchase",
    )
    lot = PurchaseLot(strain_name="Tool Dream", weight_lbs=100, remaining_weight_lbs=55)
    run = Run(
        run_date=date(2026, 4, 8),
        reactor_number=8,
        bio_in_reactor_lbs=45,
        dry_hte_g=11,
        dry_thca_g=22,
        notes="tool layer run",
    )
    slack_row = SlackIngestedMessage(
        channel_id="C-TOOLS",
        message_ts="1710000200.000100",
        raw_text="Reactor: 8\nStrain: Tool Dream\nSource: Tool Supplier\nBio wt: 45",
        message_kind="production_log",
        derived_json="{}",
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
        run_input = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=45, allocation_source="manual")
        db.session.add(run_input)
        db.session.add(slack_row)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id
        slack_row_id = slack_row.id

    bad_headers, bad_client_id = _make_api_headers("read:search")
    good_headers, good_client_id = _make_api_headers("read:tools")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/tools/inventory-snapshot", headers=bad_headers)
            assert forbidden.status_code == 403

            snapshot = client.get(f"/api/v1/tools/inventory-snapshot?supplier_id={supplier_id}", headers=good_headers)
            assert snapshot.status_code == 200
            snapshot_payload = snapshot.get_json()["data"]
            assert snapshot_payload["summary"]["open_lot_count"] >= 1
            assert snapshot_payload["lots"][0]["id"] == lot_id

            open_lots = client.get(
                f"/api/v1/tools/open-lots?supplier_id={supplier_id}&strain=Tool&min_remaining_lbs=50",
                headers=good_headers,
            )
            assert open_lots.status_code == 200
            open_payload = open_lots.get_json()["data"]
            assert open_payload["results"][0]["id"] == lot_id

            journey = client.get(
                f"/api/v1/tools/journey-resolve?entity_type=run&entity_id={run_id}",
                headers=good_headers,
            )
            assert journey.status_code == 200
            journey_payload = journey.get_json()["data"]
            assert journey_payload["journey_endpoint"] == f"/api/v1/runs/{run_id}/journey"
            assert journey_payload["journey"]["run_id"] == run_id

            overview = client.get("/api/v1/tools/reconciliation-overview", headers=good_headers)
            assert overview.status_code == 200
            overview_payload = overview.get_json()["data"]
            assert "slack_imports" in overview_payload
            assert "exceptions" in overview_payload
            assert overview_payload["slack_imports"]["total_messages"] >= 1

            bad_min = client.get("/api/v1/tools/open-lots?min_remaining_lbs=abc", headers=good_headers)
            assert bad_min.status_code == 400
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            slack_obj = db.session.get(SlackIngestedMessage, slack_row_id)
            if slack_obj:
                db.session.delete(slack_obj)
            run_input_obj = db.session.get(RunInput, run_input_id)
            if run_input_obj:
                db.session.delete(run_input_obj)
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


def test_api_v1_site_returns_site_meta_and_data():
    app = app_module.app
    headers, client_id = _make_api_headers("read:site")
    with app.app_context():
        original_code = SystemSetting.get("site_code")
        original_name = SystemSetting.get("site_name")
        original_timezone = SystemSetting.get("site_timezone")
        db.session.get(SystemSetting, "site_code").value = "SAC"
        db.session.get(SystemSetting, "site_name").value = "Gold Drop Sacramento"
        db.session.get(SystemSetting, "site_timezone").value = "America/New_York"
        db.session.commit()
    try:
        with app.test_client() as client:
            response = client.get("/api/v1/site", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["meta"]["api_version"] == "v1"
        assert payload["meta"]["site_code"] == "SAC"
        assert payload["meta"]["site_name"] == "Gold Drop Sacramento"
        assert payload["meta"]["site_timezone"] == "America/New_York"
        assert payload["data"]["site_code"] == "SAC"
        assert payload["data"]["site_name"] == "Gold Drop Sacramento"
        assert payload["data"]["site_timezone"] == "America/New_York"
    finally:
        with app.app_context():
            db.session.get(SystemSetting, "site_code").value = original_code
            db.session.get(SystemSetting, "site_name").value = original_name
            db.session.get(SystemSetting, "site_timezone").value = original_timezone
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            db.session.commit()


def test_api_v1_lots_and_inventory_match_operational_rules():
    app = app_module.app
    supplier = Supplier(name=f"API Lots {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 10),
        delivery_date=date(2026, 4, 11),
        status="delivered",
        stated_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
    )
    open_lot = PurchaseLot(strain_name="Blue Dream", weight_lbs=100, remaining_weight_lbs=40)
    spent_lot = PurchaseLot(strain_name="Blue Dream", weight_lbs=30, remaining_weight_lbs=0)
    archived_lot = PurchaseLot(
        strain_name="Blue Dream",
        weight_lbs=20,
        remaining_weight_lbs=20,
        deleted_at=datetime.now(timezone.utc),
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        for lot in (open_lot, spent_lot, archived_lot):
            lot.purchase_id = purchase.id
            db.session.add(lot)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        open_lot_id = open_lot.id
        spent_lot_id = spent_lot.id
        archived_lot_id = archived_lot.id

    headers, client_id = _make_api_headers("read:lots", "read:inventory")
    try:
        with app.test_client() as client:
            lots_res = client.get(f"/api/v1/lots?open_only=1&supplier_id={supplier_id}", headers=headers)
            assert lots_res.status_code == 200
            lots_payload = lots_res.get_json()
            lot_ids = {item["id"] for item in lots_payload["data"]}
            assert open_lot_id in lot_ids
            assert spent_lot_id not in lot_ids
            assert archived_lot_id not in lot_ids

            detail_res = client.get(f"/api/v1/lots/{open_lot_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["purchase_id"] == purchase_id
            assert detail_payload["remaining_weight_lbs"] == 40.0

            inv_res = client.get(f"/api/v1/inventory/on-hand?supplier_id={supplier_id}", headers=headers)
            assert inv_res.status_code == 200
            inv_payload = inv_res.get_json()
            inv_ids = {item["id"] for item in inv_payload["data"]}
            assert inv_ids == {open_lot_id}

            summary_res = client.get(f"/api/v1/summary/inventory?supplier_id={supplier_id}", headers=headers)
            assert summary_res.status_code == 200
            summary_payload = summary_res.get_json()["data"]
            assert summary_payload["open_lot_count"] == 1
            assert summary_payload["total_on_hand_lbs"] == 40.0
            assert summary_payload["partially_allocated_count"] == 1
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            for lot_id in (open_lot_id, spent_lot_id, archived_lot_id):
                lot = db.session.get(PurchaseLot, lot_id)
                if lot:
                    db.session.delete(lot)
            purchase_obj = db.session.get(Purchase, purchase_id)
            if purchase_obj:
                db.session.delete(purchase_obj)
            supplier_obj = db.session.get(Supplier, supplier_id)
            if supplier_obj:
                db.session.delete(supplier_obj)
            db.session.commit()


def test_api_v1_purchase_journey_is_wrapped_in_envelope():
    app = app_module.app
    supplier = Supplier(name=f"API Journey {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        status="declared",
        stated_weight_lbs=25,
        batch_id=f"APIJ-{gen_uuid()[:6]}",
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    headers, client_id = _make_api_headers("read:journey")
    try:
        with app.test_client() as client:
            response = client.get(f"/api/v1/purchases/{purchase_id}/journey", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["meta"]["api_version"] == "v1"
        assert payload["data"]["purchase_id"] == purchase_id
        assert "events" in payload["data"]
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            purchase_obj = db.session.get(Purchase, purchase_id)
            if purchase_obj:
                db.session.delete(purchase_obj)
            supplier_obj = db.session.get(Supplier, supplier_id)
            if supplier_obj:
                db.session.delete(supplier_obj)
            db.session.commit()


def test_api_v1_lot_journey_is_wrapped_in_envelope():
    app = app_module.app
    supplier = Supplier(name=f"API Lot Journey {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        delivery_date=date(2026, 4, 13),
        status="delivered",
        stated_weight_lbs=25,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"APIL-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Lot Journey", weight_lbs=25, remaining_weight_lbs=10)
    run = Run(
        run_date=date(2026, 4, 14),
        reactor_number=5,
        bio_in_reactor_lbs=15,
        dry_hte_g=4,
        dry_thca_g=6,
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
        run_input = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=15)
        db.session.add(run_input)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id

    headers, client_id = _make_api_headers("read:journey")
    try:
        with app.test_client() as client:
            response = client.get(f"/api/v1/lots/{lot_id}/journey", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["meta"]["api_version"] == "v1"
        assert payload["data"]["lot_id"] == lot_id
        assert payload["data"]["purchase_id"] == purchase_id
        assert payload["data"]["summary"]["allocated_lbs"] == 15.0
        assert payload["data"]["runs"][0]["run_id"] == run_id
        assert payload["data"]["allocations"][0]["run_input_id"] == run_input_id
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            run_input_obj = db.session.get(RunInput, run_input_id)
            if run_input_obj:
                db.session.delete(run_input_obj)
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


def test_api_v1_purchases_list_and_detail():
    app = app_module.app
    supplier = Supplier(name=f"API Purchases {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 8),
        delivery_date=date(2026, 4, 9),
        status="delivered",
        stated_weight_lbs=80,
        actual_weight_lbs=78,
        price_per_lb=200,
        total_cost=15600,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"APIP-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="GMO", weight_lbs=80, remaining_weight_lbs=60)
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id

    headers, client_id = _make_api_headers("read:purchases")
    try:
        with app.test_client() as client:
            list_res = client.get(f"/api/v1/purchases?supplier_id={supplier_id}&approved=1", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()
            assert list_payload["meta"]["count"] >= 1
            purchase_ids = {item["id"] for item in list_payload["data"]}
            assert purchase_id in purchase_ids

            detail_res = client.get(f"/api/v1/purchases/{purchase_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["id"] == purchase_id
            assert detail_payload["supplier"]["id"] == supplier_id
            assert detail_payload["lots"][0]["id"] == lot_id
            assert detail_payload["allocation_state"] == "partially_allocated"
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
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


def test_api_v1_runs_list_and_detail():
    app = app_module.app
    supplier = Supplier(name=f"API Runs {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 6),
        delivery_date=date(2026, 4, 7),
        status="delivered",
        stated_weight_lbs=120,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"APIR-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Blue Dream", weight_lbs=120, remaining_weight_lbs=70)
    run = Run(
        run_date=date(2026, 4, 10),
        reactor_number=2,
        bio_in_reactor_lbs=50,
        dry_hte_g=12,
        dry_thca_g=28,
        overall_yield_pct=8.0,
        thca_yield_pct=5.6,
        hte_yield_pct=2.4,
        cost_per_gram_combined=4.25,
        slack_channel_id="C123",
        slack_message_ts="1710000000.000100",
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
        run_input = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=50, allocation_source="slack", allocation_confidence=0.95)
        db.session.add(run_input)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id

    headers, client_id = _make_api_headers("read:runs")
    try:
        with app.test_client() as client:
            list_res = client.get(f"/api/v1/runs?supplier_id={supplier_id}&reactor_number=2&slack_linked=1", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()
            run_ids = {item["id"] for item in list_payload["data"]}
            assert run_id in run_ids

            detail_res = client.get(f"/api/v1/runs/{run_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["id"] == run_id
            assert detail_payload["input_lots"][0]["run_input_id"] == run_input_id
            assert detail_payload["input_lots"][0]["lot_id"] == lot_id
            assert detail_payload["slack_message_ts"] == "1710000000.000100"
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            run_input_obj = db.session.get(RunInput, run_input_id)
            if run_input_obj:
                db.session.delete(run_input_obj)
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


def test_api_v1_run_journey_is_wrapped_in_envelope():
    app = app_module.app
    supplier = Supplier(name=f"API Run Journey {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 6),
        delivery_date=date(2026, 4, 7),
        status="delivered",
        stated_weight_lbs=120,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"RJN-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Journey Dream", weight_lbs=120, remaining_weight_lbs=70)
    run = Run(
        run_date=date(2026, 4, 10),
        reactor_number=4,
        bio_in_reactor_lbs=50,
        dry_hte_g=12,
        dry_thca_g=28,
        hte_pipeline_stage="awaiting_lab",
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
        run_input = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=50, allocation_source="manual")
        db.session.add(run_input)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        run_input_id = run_input.id

    headers, client_id = _make_api_headers("read:journey")
    try:
        with app.test_client() as client:
            response = client.get(f"/api/v1/runs/{run_id}/journey", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["meta"]["api_version"] == "v1"
        assert payload["data"]["run_id"] == run_id
        assert payload["data"]["summary"]["input_lbs"] == 50.0
        assert payload["data"]["run"]["reactor_number"] == 4
        assert payload["data"]["lots"][0]["lot_id"] == lot_id
        assert payload["data"]["allocations"][0]["run_input_id"] == run_input_id
        assert payload["data"]["purchases"][0]["purchase_id"] == purchase_id
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            run_input_obj = db.session.get(RunInput, run_input_id)
            if run_input_obj:
                db.session.delete(run_input_obj)
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


def test_api_v1_suppliers_list_and_detail():
    app = app_module.app
    supplier = Supplier(
        name=f"API Supplier Perf {gen_uuid()[:8]}",
        contact_name="Pat Grower",
        contact_email="pat@example.com",
        location="Salinas",
        is_active=True,
    )
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 6),
        delivery_date=date(2026, 4, 7),
        status="delivered",
        stated_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"SUP-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="GMO", weight_lbs=100, remaining_weight_lbs=60)
    run = Run(
        run_date=date(2026, 4, 9),
        reactor_number=1,
        bio_in_reactor_lbs=40,
        dry_hte_g=8,
        dry_thca_g=22,
        overall_yield_pct=7.5,
        thca_yield_pct=5.5,
        hte_yield_pct=2.0,
        cost_per_gram_combined=4.0,
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
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id

    headers, client_id = _make_api_headers("read:suppliers")
    try:
        with app.test_client() as client:
            list_res = client.get(f"/api/v1/suppliers?q={supplier.name}", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()
            supplier_ids = {item["supplier"]["id"] for item in list_payload["data"]}
            assert supplier_id in supplier_ids

            detail_res = client.get(f"/api/v1/suppliers/{supplier_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["supplier"]["id"] == supplier_id
            assert detail_payload["all_time"]["runs"] >= 1
            assert detail_payload["last_batch"]["date"] == "2026-04-09"
            assert detail_payload["contact_name"] == "Pat Grower"
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            run_input = RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
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


def test_api_v1_strains_list():
    app = app_module.app
    supplier = Supplier(name=f"API Strain Perf {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 5),
        delivery_date=date(2026, 4, 6),
        status="delivered",
        stated_weight_lbs=80,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"STR-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Blue Dream", weight_lbs=80, remaining_weight_lbs=40)
    run = Run(
        run_date=date(2026, 4, 8),
        reactor_number=2,
        bio_in_reactor_lbs=40,
        dry_hte_g=10,
        dry_thca_g=20,
        overall_yield_pct=7.5,
        thca_yield_pct=5.0,
        hte_yield_pct=2.5,
        cost_per_gram_combined=4.4,
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
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id

    headers, client_id = _make_api_headers("read:strains")
    try:
        with app.test_client() as client:
            list_res = client.get(f"/api/v1/strains?view=all&supplier_id={supplier_id}&strain=Blue", headers=headers)
            assert list_res.status_code == 200
            payload = list_res.get_json()
            assert payload["meta"]["count"] >= 1
            first = payload["data"][0]
            assert first["strain_name"] == "Blue Dream"
            assert first["supplier_name"] == supplier.name
            assert first["view"] == "all"
            assert first["run_count"] >= 1
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            run_input = RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
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


def test_api_v1_slack_imports_list_and_detail():
    app = app_module.app
    row = SlackIngestedMessage(
        channel_id="C-SLACK-API",
        message_ts="1710000001.000100",
        raw_text="Reactor: A\nStrain: Blue Dream\nSource: Farmlane\nBio wt: 100\nWet THCA: 10\nWet HTE: 20",
        message_kind="production_log",
        derived_json="{}",
    )
    with app.app_context():
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    headers, client_id = _make_api_headers("read:slack_imports")
    try:
        with app.test_client() as client:
            list_res = client.get("/api/v1/slack-imports?channel_id=C-SLACK-API&promotion=not_linked", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()
            row_ids = {item["id"] for item in list_payload["data"]}
            assert row_id in row_ids

            summary_res = client.get("/api/v1/summary/slack-imports?channel_id=C-SLACK-API", headers=headers)
            assert summary_res.status_code == 200
            summary_payload = summary_res.get_json()["data"]
            assert summary_payload["total_messages"] >= 1
            assert sum(summary_payload["bucket_counts"].values()) == summary_payload["total_messages"]

            detail_res = client.get(f"/api/v1/slack-imports/{row_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["id"] == row_id
            assert detail_payload["promotion_status"] == "not_linked"
            assert detail_payload["coverage"] in {"full", "partial", "none"}
            assert "preview" in detail_payload
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            row_obj = db.session.get(SlackIngestedMessage, row_id)
            if row_obj:
                db.session.delete(row_obj)
            db.session.commit()


def test_api_v1_exceptions_returns_purchase_and_inventory_signals():
    app = app_module.app
    supplier = Supplier(name=f"API Exceptions {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2099, 4, 14),
        delivery_date=date(2099, 4, 15),
        status="delivered",
        stated_weight_lbs=100,
        batch_id=f"EXC-{gen_uuid()[:6]}",
        purchase_approved_at=datetime.now(timezone.utc),
    )
    lot = PurchaseLot(strain_name="Exception Strain", weight_lbs=100, remaining_weight_lbs=10)
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id

    headers, client_id = _make_api_headers("read:exceptions")
    try:
        with app.test_client() as client:
            purchase_response = client.get("/api/v1/exceptions?category=purchases&limit=200", headers=headers)
            inventory_response = client.get("/api/v1/exceptions?category=inventory&limit=200", headers=headers)
            summary_response = client.get("/api/v1/summary/exceptions", headers=headers)
        assert purchase_response.status_code == 200
        assert inventory_response.status_code == 200
        assert summary_response.status_code == 200
        purchase_payload = purchase_response.get_json()
        inventory_payload = inventory_response.get_json()
        summary_payload = summary_response.get_json()["data"]
        purchase_categories = {(item["category"], item["entity_type"], item["entity_id"]) for item in purchase_payload["data"]}
        inventory_categories = {(item["category"], item["entity_type"], item["entity_id"]) for item in inventory_payload["data"]}
        assert ("purchases", "purchase", purchase_id) in purchase_categories
        assert ("inventory", "purchase_lot", lot_id) in inventory_categories
        assert summary_payload["total_exceptions"] >= 2
        assert summary_payload["category_counts"]["purchases"] >= 1
        assert summary_payload["category_counts"]["inventory"] >= 1
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
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
