from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import ApiClient, Purchase, PurchaseLot, Run, RunInput, Supplier, db, gen_uuid
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


def test_api_v1_site_returns_site_meta_and_data():
    app = app_module.app
    headers, client_id = _make_api_headers("read:site")
    try:
        with app.test_client() as client:
            response = client.get("/api/v1/site", headers=headers)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["meta"]["api_version"] == "v1"
        assert payload["data"]["site_code"]
        assert payload["data"]["site_name"]
    finally:
        with app.app_context():
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
