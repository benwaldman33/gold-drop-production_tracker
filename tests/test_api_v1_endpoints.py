from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import ApiClient, ApiClientRequestLog, LotScanEvent, MaterialLot, MaterialReconciliationIssue, MaterialTransformation, Purchase, PurchaseLot, RemoteSite, Run, RunInput, SlackIngestedMessage, Supplier, SystemSetting, db, gen_uuid
from services.api_auth import hash_api_token
from services.api_registry import API_V1_ENDPOINTS, API_V1_SCOPES
from services.material_genealogy import ensure_biomass_material_lot, ensure_extraction_output_genealogy


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
            assert payload["scopes"] == API_V1_SCOPES
            assert payload["endpoints"] == API_V1_ENDPOINTS
            assert "read:dashboard" in payload["scopes"]
            assert "read:aggregation" in payload["scopes"]
            assert "read:scanner" in payload["scopes"]
            assert "read:scales" in payload["scopes"]
            paths = {item["path"] for item in payload["endpoints"]}
            assert "/api/v1/site" in paths
            assert "/api/v1/summary/dashboard" in paths
            assert "/api/v1/summary/exceptions" in paths
            assert "/api/v1/scan-events" in paths
            assert "/api/v1/summary/scanner" in paths
            assert "/api/v1/scale-devices" in paths
            assert "/api/v1/summary/scales" in paths
            assert "/api/v1/aggregation/summary" in paths
            assert "/api/v1/aggregation/suppliers" in paths
            assert "/api/v1/aggregation/strains" in paths
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            db.session.commit()


def test_api_v1_registry_covers_registered_routes():
    app = app_module.app
    with app.app_context():
        registered_paths = {
            rule.rule
            for rule in app.url_map.iter_rules()
            if rule.rule.startswith("/api/v1/")
        }
    registry_paths = {endpoint["path"] for endpoint in API_V1_ENDPOINTS}
    assert registered_paths == registry_paths
    assert sorted({endpoint["scope"] for endpoint in API_V1_ENDPOINTS}) == sorted(API_V1_SCOPES)


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
            search_json = response.get_json()
            assert search_json["meta"]["sort"] == "relevance"
            assert search_json["meta"]["filters"]["q"] == "alpha"
            payload = search_json["data"]
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
        message_ts=f"1710000200.{gen_uuid().replace('-', '')[:6]}",
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
        original_region = SystemSetting.get("site_region")
        original_environment = SystemSetting.get("site_environment")
        db.session.get(SystemSetting, "site_code").value = "SAC"
        db.session.get(SystemSetting, "site_name").value = "Gold Drop Sacramento"
        db.session.get(SystemSetting, "site_timezone").value = "America/New_York"
        db.session.get(SystemSetting, "site_region").value = "California"
        db.session.get(SystemSetting, "site_environment").value = "staging"
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
        assert payload["meta"]["site_region"] == "California"
        assert payload["meta"]["site_environment"] == "staging"
        assert payload["data"]["site_code"] == "SAC"
        assert payload["data"]["site_name"] == "Gold Drop Sacramento"
        assert payload["data"]["site_timezone"] == "America/New_York"
        assert payload["data"]["site_region"] == "California"
        assert payload["data"]["site_environment"] == "staging"
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            assert api_client.last_used_scope == "read:site"
            assert api_client.last_used_endpoint == "/api/v1/site"
            request_log = ApiClientRequestLog.query.filter_by(api_client_id=client_id).order_by(ApiClientRequestLog.created_at.desc()).first()
            assert request_log is not None
            assert request_log.request_path == "/api/v1/site"
            assert request_log.scope_used == "read:site"
    finally:
        with app.app_context():
            db.session.get(SystemSetting, "site_code").value = original_code
            db.session.get(SystemSetting, "site_name").value = original_name
            db.session.get(SystemSetting, "site_timezone").value = original_timezone
            db.session.get(SystemSetting, "site_region").value = original_region
            db.session.get(SystemSetting, "site_environment").value = original_environment
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            db.session.commit()


def test_api_v1_sync_manifest_returns_dataset_metadata():
    app = app_module.app
    headers, client_id = _make_api_headers("read:site")
    try:
        with app.test_client() as client:
            response = client.get("/api/v1/sync/manifest", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()["data"]
        assert "site" in payload
        assert "datasets" in payload
        assert "purchases" in payload["datasets"]
        assert "runs" in payload["datasets"]
        assert payload["capabilities_endpoint"] == "/api/v1/capabilities"
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            db.session.commit()


def test_api_v1_aggregation_sites_and_summary_use_cached_remote_payloads():
    app = app_module.app
    headers, client_id = _make_api_headers("read:aggregation")
    with app.app_context():
        remote_host = f"https://gamma-{gen_uuid()[:8]}.example.com"
        site = RemoteSite(
            name="Remote Gamma",
            base_url=remote_host,
            site_code="GAM",
            site_name="Gamma Site",
            site_region="Nevada",
            site_environment="production",
            is_active=True,
            last_pull_status="success",
        )
        site.set_payload("last_dashboard_payload_json", {"totals": {"total_runs": 4, "total_lbs": 220.0, "total_dry_output_g": 33.0}})
        site.set_payload("last_inventory_payload_json", {"total_on_hand_lbs": 150.0})
        site.set_payload("last_exceptions_payload_json", {"total_exceptions": 2})
        site.set_payload("last_slack_payload_json", {"total_messages": 9})
        db.session.add(site)
        db.session.commit()
        site_id = site.id
    try:
        with app.test_client() as client:
            list_res = client.get("/api/v1/aggregation/sites", headers=headers)
            assert list_res.status_code == 200
            list_payload = list_res.get_json()
            assert list_payload["meta"]["sort"] == "name_ascending"
            items = list_payload["data"]
            assert any(item["id"] == site_id for item in items)

            detail_res = client.get(f"/api/v1/aggregation/sites/{site_id}", headers=headers)
            assert detail_res.status_code == 200
            detail = detail_res.get_json()["data"]
            assert detail["cached_payloads"]["dashboard"]["totals"]["total_runs"] == 4

            summary_res = client.get("/api/v1/aggregation/summary?period=30", headers=headers)
            assert summary_res.status_code == 200
            summary = summary_res.get_json()["data"]
            assert summary["sites_total"] >= 2
            assert summary["remote_sites_active"] >= 1
            assert summary["totals"]["total_runs"] >= 4

            bad_period = client.get("/api/v1/aggregation/summary?period=bad", headers=headers)
            assert bad_period.status_code == 400
    finally:
        with app.app_context():
            site = db.session.get(RemoteSite, site_id)
            if site:
                db.session.delete(site)
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            db.session.commit()


def test_api_v1_aggregation_supplier_and_strain_comparison():
    app = app_module.app
    headers, client_id = _make_api_headers("read:aggregation")
    supplier = Supplier(name=f"Compare Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 9),
        delivery_date=date(2026, 4, 10),
        status="delivered",
        stated_weight_lbs=70,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"COMPARE-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Compare Dream", weight_lbs=70, remaining_weight_lbs=20)
    run = Run(
        run_date=date(2026, 4, 11),
        reactor_number=5,
        bio_in_reactor_lbs=50,
        dry_hte_g=8,
        dry_thca_g=18,
    )
    remote_base_url = f"https://compare-{gen_uuid()[:8]}.example.com"
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
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=50, allocation_source="manual"))
        remote_site = RemoteSite(
            name="Remote Compare",
            base_url=remote_base_url,
            site_code="CMP",
            site_name="Compare Remote",
            is_active=True,
            last_pull_status="success",
        )
        remote_site.set_payload("last_suppliers_payload_json", [{
            "supplier": {"id": "remote-supplier-1", "name": "Remote Compare Supplier"},
            "profile_incomplete": False,
            "all_time": {"yield": 11.5, "thca": 6.2, "hte": 5.3, "cpg": 4.4, "runs": 3, "lbs": 180.0, "total_thca": 320.0, "total_hte": 140.0},
            "ninety_day": {"yield": 10.8, "thca": 5.9, "hte": 4.9, "cpg": 4.6, "runs": 2},
            "last_batch": {"yield": 12.1, "thca": 6.5, "hte": 5.6, "cpg": 4.2, "date": "2026-04-10"},
        }])
        remote_site.set_payload("last_strains_payload_json", [{
            "strain_name": "Remote Compare Dream",
            "supplier_name": "Remote Compare Supplier",
            "view": "all",
            "avg_yield": 11.5,
            "avg_thca": 6.2,
            "avg_hte": 5.3,
            "avg_cpg": 4.4,
            "run_count": 3,
            "total_lbs": 180.0,
            "total_thca_g": 320.0,
            "total_hte_g": 140.0,
        }])
        db.session.add(remote_site)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id
        remote_site_id = remote_site.id
    try:
        with app.test_client() as client:
            supplier_res = client.get("/api/v1/aggregation/suppliers?q=compare", headers=headers)
            assert supplier_res.status_code == 200
            supplier_payload = supplier_res.get_json()
            assert supplier_payload["meta"]["sort"] == "supplier_name_ascending"
            assert supplier_payload["meta"]["filters"]["q"] == "compare"
            supplier_rows = supplier_payload["data"]
            assert any(row["site"]["source"] == "local" for row in supplier_rows)
            assert any(row["site"]["source"] == "remote_cache" for row in supplier_rows)

            strain_res = client.get("/api/v1/aggregation/strains?q=compare", headers=headers)
            assert strain_res.status_code == 200
            strain_payload = strain_res.get_json()
            assert strain_payload["meta"]["sort"] == "avg_yield_desc"
            assert strain_payload["meta"]["filters"]["q"] == "compare"
            strain_rows = strain_payload["data"]
            assert any(row["site"]["source"] == "local" for row in strain_rows)
            assert any(row["site"]["source"] == "remote_cache" for row in strain_rows)
    finally:
        with app.app_context():
            remote_site = db.session.get(RemoteSite, remote_site_id)
            if remote_site:
                db.session.delete(remote_site)
            run_input = RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
            if run_input:
                db.session.delete(run_input)
            run = db.session.get(Run, run_id)
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id)
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
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
            assert lots_payload["meta"]["sort"] == "purchase_date_desc"
            assert lots_payload["meta"]["filters"]["open_only"] is True
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
            assert inv_payload["meta"]["sort"] == "purchase_date_desc"
            assert inv_payload["meta"]["filters"]["supplier_id"] == supplier_id
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


def test_api_v1_scanner_endpoints_return_scan_activity():
    app = app_module.app
    supplier = Supplier(name=f"API Scanner {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        delivery_date=date(2026, 4, 13),
        status="delivered",
        stated_weight_lbs=35,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"APISC-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(strain_name="Scanner Lot", weight_lbs=35, remaining_weight_lbs=20)
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.flush()
        open_event = LotScanEvent(
            lot_id=lot.id,
            tracking_id_snapshot=lot.tracking_id,
            action="scan_open",
        )
        move_event = LotScanEvent(
            lot_id=lot.id,
            tracking_id_snapshot=lot.tracking_id,
            action="confirm_movement",
        )
        db.session.add(open_event)
        db.session.add(move_event)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        tracking_id = lot.tracking_id
        event_ids = [open_event.id, move_event.id]

    bad_headers, bad_client_id = _make_api_headers("read:lots")
    good_headers, good_client_id = _make_api_headers("read:scanner")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/scan-events", headers=bad_headers)
            assert forbidden.status_code == 403

            events_res = client.get(f"/api/v1/scan-events?tracking_id={tracking_id}", headers=good_headers)
            assert events_res.status_code == 200
            events_json = events_res.get_json()
            assert events_json["meta"]["sort"] == "created_at_desc"
            assert events_json["meta"]["filters"]["tracking_id"] == tracking_id
            returned_ids = {item["id"] for item in events_json["data"]}
            assert returned_ids == set(event_ids)

            lot_res = client.get(f"/api/v1/lots/{lot_id}/scans", headers=good_headers)
            assert lot_res.status_code == 200
            lot_json = lot_res.get_json()
            assert lot_json["meta"]["filters"]["lot_id"] == lot_id
            assert len(lot_json["data"]) == 2

            summary_res = client.get("/api/v1/summary/scanner", headers=good_headers)
            assert summary_res.status_code == 200
            summary_payload = summary_res.get_json()["data"]
            assert summary_payload["total_events"] >= 2
            assert summary_payload["action_counts"]["scan_open"] >= 1
            assert summary_payload["action_counts"]["confirm_movement"] >= 1
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            for event_id in event_ids:
                event = db.session.get(LotScanEvent, event_id)
                if event:
                    db.session.delete(event)
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


def test_api_v1_scale_endpoints_return_devices_and_captures():
    app = app_module.app
    with app.app_context():
        device = app_module.ScaleDevice(
            name=f"API Scale {gen_uuid()[:8]}",
            location="Receiving",
            interface_type="rs232",
            protocol_type="ascii",
            connection_target="COM7",
            is_active=True,
        )
        db.session.add(device)
        db.session.flush()
        capture = app_module.WeightCapture(
            capture_type="allocation",
            source_mode="device",
            measured_weight=111.4,
            unit="lb",
            net_weight=111.4,
            device_id=device.id,
            raw_payload="ST,GS, 111.4 lb",
        )
        db.session.add(capture)
        db.session.commit()
        device_id = device.id
        capture_id = capture.id

    bad_headers, bad_client_id = _make_api_headers("read:inventory")
    good_headers, good_client_id = _make_api_headers("read:scales")
    try:
        with app.test_client() as client:
            forbidden = client.get("/api/v1/scale-devices", headers=bad_headers)
            assert forbidden.status_code == 403

            devices_res = client.get("/api/v1/scale-devices", headers=good_headers)
            assert devices_res.status_code == 200
            devices_json = devices_res.get_json()
            assert devices_json["meta"]["sort"] == "created_at_desc"
            assert {item["id"] for item in devices_json["data"]} >= {device_id}

            captures_res = client.get(f"/api/v1/weight-captures?device_id={device_id}", headers=good_headers)
            assert captures_res.status_code == 200
            captures_json = captures_res.get_json()
            assert captures_json["meta"]["filters"]["device_id"] == device_id
            assert {item["id"] for item in captures_json["data"]} >= {capture_id}

            summary_res = client.get("/api/v1/summary/scales", headers=good_headers)
            assert summary_res.status_code == 200
            summary_payload = summary_res.get_json()["data"]
            assert summary_payload["device_count"] >= 1
            assert summary_payload["capture_count"] >= 1
            assert summary_payload["capture_type_counts"]["allocation"] >= 1
    finally:
        with app.app_context():
            for client_id in (bad_client_id, good_client_id):
                api_client = db.session.get(ApiClient, client_id)
                if api_client:
                    db.session.delete(api_client)
            capture_obj = db.session.get(app_module.WeightCapture, capture_id)
            if capture_obj:
                db.session.delete(capture_obj)
            device_obj = db.session.get(app_module.ScaleDevice, device_id)
            if device_obj:
                db.session.delete(device_obj)
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
            assert list_payload["meta"]["sort"] == "purchase_date_desc"
            assert list_payload["meta"]["filters"]["supplier_id"] == supplier_id
            assert list_payload["meta"]["filters"]["approved"] is True
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
            assert list_payload["meta"]["sort"] == "run_date_desc"
            assert list_payload["meta"]["filters"]["reactor_number"] == 2
            assert list_payload["meta"]["filters"]["slack_linked"] is True
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


def test_api_v1_material_lot_endpoints_and_run_journey_include_derivatives():
    app = app_module.app
    supplier = Supplier(name=f"API Material Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 6),
        delivery_date=date(2026, 4, 7),
        status="delivered",
        stated_weight_lbs=120,
        purchase_approved_at=datetime.now(timezone.utc),
        batch_id=f"MAT-{gen_uuid()[:6]}",
    )
    lot = PurchaseLot(
        strain_name="Material Dream",
        weight_lbs=120,
        remaining_weight_lbs=70,
        tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
    )
    run = Run(
        run_date=date(2026, 4, 10),
        reactor_number=7,
        bio_in_reactor_lbs=50,
        dry_hte_g=12,
        dry_thca_g=28,
        cost_per_gram_hte=3.2,
        cost_per_gram_thca=4.1,
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
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=50, allocation_source="manual"))
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        run_id = run.id

        ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot_id))
        ensure_extraction_output_genealogy(app_module, db.session.get(Run, run_id))
        db.session.commit()
        derivative_lot = db.session.get(Run, run_id).material_lots.filter_by(lot_type="dry_hte").first()
        derivative_lot_id = derivative_lot.id
        source_material_lot_id = db.session.get(PurchaseLot, lot_id).material_lot_id

    headers, client_id = _make_api_headers("read:journey", "read:tools", "read:inventory")
    try:
        with app.test_client() as client:
            run_journey = client.get(f"/api/v1/runs/{run_id}/journey", headers=headers)
            assert run_journey.status_code == 200
            run_payload = run_journey.get_json()["data"]
            assert run_payload["summary"]["derivative_lot_count"] == 2
            assert {item["lot_type"] for item in run_payload["material_lots"]} == {"dry_hte", "dry_thca"}

            detail_res = client.get(f"/api/v1/material-lots/{derivative_lot_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_payload = detail_res.get_json()["data"]
            assert detail_payload["material_lot"]["material_lot_id"] == derivative_lot_id
            assert detail_payload["material_lot"]["lot_type"] == "dry_hte"

            ancestry_res = client.get(f"/api/v1/material-lots/{derivative_lot_id}/ancestry", headers=headers)
            assert ancestry_res.status_code == 200
            ancestry_payload = ancestry_res.get_json()["data"]
            assert ancestry_payload["ancestry"][0]["inputs"][0]["material_lot"]["lot_type"] == "biomass"

            descendants_res = client.get(f"/api/v1/material-lots/{source_material_lot_id}/descendants", headers=headers)
            assert descendants_res.status_code == 200
            descendants_payload = descendants_res.get_json()["data"]
            descendant_output_types = {
                output["material_lot"]["lot_type"]
                for node in descendants_payload["descendants"]
                for output in node["outputs"]
            }
            assert {"dry_hte", "dry_thca"}.issubset(descendant_output_types)

            resolve_res = client.get(
                f"/api/v1/tools/journey-resolve?entity_type=material_lot&entity_id={derivative_lot_id}",
                headers=headers,
            )
            assert resolve_res.status_code == 200
            resolve_payload = resolve_res.get_json()["data"]
            assert resolve_payload["journey_endpoint"] == f"/api/v1/material-lots/{derivative_lot_id}/journey"

            overview = client.get("/api/v1/tools/reconciliation-overview", headers=headers)
            assert overview.status_code == 200
            overview_payload = overview.get_json()["data"]
            assert "material_genealogy" in overview_payload

            cost_summary = client.get("/api/v1/summary/material-costs", headers=headers)
            assert cost_summary.status_code == 200
            cost_payload = cost_summary.get_json()["data"]
            grouped = {item["lot_type"]: item for item in cost_payload["groups"]}
            assert grouped["dry_hte"]["cost_basis_total"] >= 38.4
            assert grouped["dry_thca"]["cost_basis_total"] >= 114.8

            genealogy_summary = client.get("/api/v1/summary/material-genealogy", headers=headers)
            assert genealogy_summary.status_code == 200
            genealogy_payload = genealogy_summary.get_json()["data"]
            assert "open_inventory_groups" in genealogy_payload
            assert "recent_derivative_lots" in genealogy_payload
    finally:
        with app.app_context():
            api_client = db.session.get(ApiClient, client_id)
            if api_client:
                db.session.delete(api_client)
            MaterialReconciliationIssue.query.filter_by(run_id=run_id).delete()
            MaterialTransformation.query.filter_by(run_id=run_id).delete()
            for material_lot in MaterialLot.query.filter(MaterialLot.parent_run_id == run_id).all():
                db.session.delete(material_lot)
            source_material = MaterialLot.query.filter_by(source_purchase_lot_id=lot_id).first()
            if source_material:
                db.session.delete(source_material)
            run_inputs = RunInput.query.filter_by(run_id=run_id).all()
            for run_input in run_inputs:
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
            assert list_payload["meta"]["sort"] == "name_ascending"
            assert list_payload["meta"]["filters"]["q"] == supplier.name
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
            assert payload["meta"]["sort"] == "avg_yield_desc"
            assert payload["meta"]["filters"]["view"] == "all"
            assert payload["meta"]["filters"]["supplier_id"] == supplier_id
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
            assert list_payload["meta"]["sort"] == "message_ts_desc"
            assert list_payload["meta"]["filters"]["channel_id"] == "C-SLACK-API"
            assert list_payload["meta"]["filters"]["promotion"] == "not_linked"
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
        assert purchase_payload["meta"]["sort"] == "category_then_label"
        assert purchase_payload["meta"]["filters"]["category"] == "purchases"
        assert inventory_payload["meta"]["filters"]["category"] == "inventory"
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
