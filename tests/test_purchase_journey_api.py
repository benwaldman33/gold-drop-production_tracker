"""Integration tests for Batch Journey API payload."""

from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import Purchase, PurchaseLot, Run, RunInput, Supplier, db, gen_uuid


def _login_admin(client) -> None:
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "golddrop2026"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_purchase_journey_api_includes_extraction_and_post_processing():
    app = app_module.app
    supplier = Supplier(name=f"Journey Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 1),
        delivery_date=date(2026, 4, 2),
        status="delivered",
        stated_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
    )
    lot = PurchaseLot(strain_name="Journey Strain", weight_lbs=100, remaining_weight_lbs=60)
    run = Run(run_date=date(2026, 4, 3), reactor_number=1, dry_hte_g=10, dry_thca_g=20, hte_pipeline_stage="awaiting_lab")
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

        purchase_id = purchase.id
        run_id = run.id
        lot_id = lot.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login_admin(client)
            res = client.get(f"/api/purchases/{purchase_id}/journey")
            assert res.status_code == 200
            payload = res.get_json()
            assert payload["purchase_id"] == purchase_id
            stages = {e["stage_key"]: e for e in payload["events"]}
            assert stages["extraction"]["metrics"]["run_count"] == 1
            assert stages["post_processing"]["state"] == "in_progress"
            assert stages["inventory"]["metrics"]["remaining_lbs"] == 60.0
            assert payload["lots"][0]["tracking_id"].startswith("LOT-")
            assert payload["lots"][0]["allocated_weight_lbs"] == 40.0
            assert payload["allocations"][0]["weight_lbs"] == 40.0
            assert payload["runs"][0]["run_id"] == run_id
    finally:
        with app.app_context():
            ri = RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
            if ri:
                db.session.delete(ri)
            r = db.session.get(Run, run_id)
            if r:
                db.session.delete(r)
            l = db.session.get(PurchaseLot, lot_id)
            if l:
                db.session.delete(l)
            p = db.session.get(Purchase, purchase_id)
            if p:
                db.session.delete(p)
            s = db.session.get(Supplier, supplier_id)
            if s:
                db.session.delete(s)
            db.session.commit()


def test_purchase_journey_api_include_archived_flag_for_admin():
    app = app_module.app
    supplier = Supplier(name=f"Journey Archive {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 1),
        status="ordered",
        stated_weight_lbs=50,
    )
    active_lot = PurchaseLot(strain_name="Active", weight_lbs=30, remaining_weight_lbs=30)
    archived_lot = PurchaseLot(
        strain_name="Archived",
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
        active_lot.purchase_id = purchase.id
        archived_lot.purchase_id = purchase.id
        db.session.add(active_lot)
        db.session.add(archived_lot)
        db.session.commit()
        purchase_id = purchase.id
        active_lot_id = active_lot.id
        archived_lot_id = archived_lot.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login_admin(client)
            res_default = client.get(f"/api/purchases/{purchase_id}/journey")
            assert res_default.status_code == 200
            inv_default = next(e for e in res_default.get_json()["events"] if e["stage_key"] == "inventory")
            assert inv_default["metrics"]["lot_count"] == 1

            res_arch = client.get(f"/api/purchases/{purchase_id}/journey?include_archived=1")
            assert res_arch.status_code == 200
            inv_arch = next(e for e in res_arch.get_json()["events"] if e["stage_key"] == "inventory")
            assert inv_arch["metrics"]["lot_count"] == 2
    finally:
        with app.app_context():
            for lot_id in (active_lot_id, archived_lot_id):
                l = db.session.get(PurchaseLot, lot_id)
                if l:
                    db.session.delete(l)
            p = db.session.get(Purchase, purchase_id)
            if p:
                db.session.delete(p)
            s = db.session.get(Supplier, supplier_id)
            if s:
                db.session.delete(s)
            db.session.commit()


def test_purchase_journey_page_renders_for_logged_in_user():
    app = app_module.app
    supplier = Supplier(name=f"Journey Page {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 1),
        status="declared",
        stated_weight_lbs=25,
        batch_id=f"JOURN-{gen_uuid()[:6]}",
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login_admin(client)
            res = client.get(f"/purchases/{purchase_id}/journey")
            assert res.status_code == 200
            html = res.get_data(as_text=True)
            assert "Progress timeline" in html
            assert "Declared" in html
            assert "Edit Purchase" in html
            assert "Export JSON" in html
            assert "Export CSV" in html
            assert "Print Labels" in html
            assert "Barcode Only" in html

            json_export = client.get(f"/purchases/{purchase_id}/journey/export?format=json")
            assert json_export.status_code == 200
            assert "application/json" in (json_export.content_type or "")
            assert "\"events\"" in json_export.get_data(as_text=True)

            csv_export = client.get(f"/purchases/{purchase_id}/journey/export?format=csv")
            assert csv_export.status_code == 200
            assert "text/csv" in (csv_export.content_type or "")
            csv_text = csv_export.get_data(as_text=True)
            assert "stage_key,state,started_at,completed_at" in csv_text
    finally:
        with app.app_context():
            p = db.session.get(Purchase, purchase_id)
            if p:
                db.session.delete(p)
            s = db.session.get(Supplier, supplier_id)
            if s:
                db.session.delete(s)
            db.session.commit()


def test_archived_purchase_journey_requires_include_archived_flag():
    app = app_module.app
    supplier = Supplier(name=f"Journey Deleted {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 1),
        status="cancelled",
        stated_weight_lbs=10,
        deleted_at=datetime.now(timezone.utc),
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login_admin(client)

            api_missing = client.get(f"/api/purchases/{purchase_id}/journey")
            assert api_missing.status_code == 404

            api_archived = client.get(f"/api/purchases/{purchase_id}/journey?include_archived=1")
            assert api_archived.status_code == 200

            page_missing = client.get(f"/purchases/{purchase_id}/journey")
            assert page_missing.status_code in (302, 303)

            page_archived = client.get(f"/purchases/{purchase_id}/journey?include_archived=1")
            assert page_archived.status_code == 200
    finally:
        with app.app_context():
            p = db.session.get(Purchase, purchase_id)
            if p:
                db.session.delete(p)
            s = db.session.get(Supplier, supplier_id)
            if s:
                db.session.delete(s)
            db.session.commit()


def test_purchase_journey_export_rejects_unknown_format():
    app = app_module.app
    supplier = Supplier(name=f"Journey Format {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 1),
        status="declared",
        stated_weight_lbs=10,
    )
    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login_admin(client)
            res = client.get(f"/purchases/{purchase_id}/journey/export?format=xml")
            assert res.status_code == 400
            payload = res.get_json()
            assert payload["error"] == "Unsupported export format"
            assert payload["supported_formats"] == ["csv", "json"]
    finally:
        with app.app_context():
            p = db.session.get(Purchase, purchase_id)
            if p:
                db.session.delete(p)
            s = db.session.get(Supplier, supplier_id)
            if s:
                db.session.delete(s)
            db.session.commit()

