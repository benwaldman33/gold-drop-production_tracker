from __future__ import annotations

from io import BytesIO

from models import PhotoAsset, Purchase, Supplier, db, gen_uuid
import app as app_module


def _login_mobile(client, username: str = "ops", password: str = "golddrop2026"):
    return client.post(
        "/api/mobile/v1/auth/login",
        json={"username": username, "password": password},
    )


def _create_supplier(app, name: str) -> str:
    supplier = Supplier(name=name, is_active=True)
    with app.app_context():
        db.session.add(supplier)
        db.session.commit()
        return supplier.id


def test_mobile_login_me_and_logout():
    app = app_module.create_app()
    with app.test_client() as client:
        response = _login_mobile(client)
        assert response.status_code == 200
        payload = response.get_json()["data"]
        assert payload["authenticated"] is True
        assert payload["user"]["username"] == "ops"
        assert payload["site"]["site_code"]

        me = client.get("/api/mobile/v1/auth/me")
        assert me.status_code == 200
        assert me.get_json()["data"]["authenticated"] is True

        logout = client.post("/api/mobile/v1/auth/logout")
        assert logout.status_code == 200


def test_mobile_supplier_duplicate_warning_and_confirm_create():
    app = app_module.create_app()
    existing_supplier_id = _create_supplier(app, f"Acme Farms {gen_uuid()[:6]}")
    created_supplier_id = None
    # Intentional same-ish name to trigger the fuzzy warning flow.
    duplicate_name = "Acme Farms"
    try:
        with app.test_client() as client:
            _login_mobile(client)
            warning = client.post(
                "/api/mobile/v1/suppliers",
                json={"new_supplier": {"name": duplicate_name}},
            )
            assert warning.status_code == 200
            warning_payload = warning.get_json()["data"]
            assert warning_payload["requires_confirmation"] is True
            assert warning_payload["duplicate_candidates"]

            confirmed = client.post(
                "/api/mobile/v1/suppliers",
                json={
                    "new_supplier": {"name": f"{duplicate_name} North"},
                    "confirm_new_supplier": True,
                },
            )
            assert confirmed.status_code == 201
            confirmed_payload = confirmed.get_json()["data"]["supplier"]
            assert confirmed_payload["name"] == f"{duplicate_name} North"
            created_supplier_id = confirmed_payload["id"]
            logout = client.post("/api/mobile/v1/auth/logout")
            assert logout.status_code == 200
    finally:
        with app.app_context():
            if created_supplier_id:
                created = db.session.get(Supplier, created_supplier_id)
                if created:
                    db.session.delete(created)
            supplier = db.session.get(Supplier, existing_supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_supplier_reads_require_auth_and_return_searchable_rows():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Searchable Supplier {gen_uuid()[:6]}")
    try:
        with app.test_client() as client:
            unauth = client.get("/api/mobile/v1/suppliers")
            assert unauth.status_code == 401

            _login_mobile(client)
            listing = client.get("/api/mobile/v1/suppliers?q=Searchable")
            assert listing.status_code == 200
            payload = listing.get_json()["data"]
            assert payload
            assert any(row["id"] == supplier_id for row in payload)

            detail = client.get(f"/api/mobile/v1/suppliers/{supplier_id}")
            assert detail.status_code == 200
            assert detail.get_json()["data"]["id"] == supplier_id
    finally:
        with app.app_context():
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_opportunity_edit_delivery_and_photo_flow():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Mobile Supplier {gen_uuid()[:6]}")
    try:
        with app.test_client() as client:
            _login_mobile(client)

            create_res = client.post(
                "/api/mobile/v1/opportunities",
                json={
                    "supplier_id": supplier_id,
                    "strain_name": "Blue Dream",
                    "expected_weight_lbs": 120,
                    "expected_potency_pct": 23.5,
                    "offered_price_per_lb": 280,
                    "availability_date": "2026-04-15",
                    "testing_notes": "test notes",
                    "notes": "standalone opportunity",
                },
            )
            assert create_res.status_code == 201
            opportunity = create_res.get_json()["data"]["opportunity"]
            opp_id = opportunity["id"]
            assert opportunity["status"] == "submitted"
            assert opportunity["editable"] is True
            assert opportunity["supplier"]["id"] == supplier_id

            photo_res = client.post(
                f"/api/mobile/v1/opportunities/{opp_id}/photos",
                data={
                    "photo_context": "opportunity",
                    "photo": (BytesIO(b"fake-image"), "opportunity.jpg"),
                },
                content_type="multipart/form-data",
            )
            assert photo_res.status_code == 201
            assert photo_res.get_json()["data"]["photo_context"] == "opportunity"
            assert photo_res.get_json()["data"]["count"] == 1

            patch_res = client.patch(
                f"/api/mobile/v1/opportunities/{opp_id}",
                json={
                    "expected_weight_lbs": 125,
                    "notes": "updated note",
                },
            )
            assert patch_res.status_code == 200
            patch_payload = patch_res.get_json()["data"]["opportunity"]
            assert patch_payload["expected_weight_lbs"] == 125
            assert patch_payload["notes"] == "updated note"

            with app.app_context():
                purchase = db.session.get(Purchase, opp_id)
                purchase.purchase_approved_at = purchase.created_at
                purchase.status = "committed"
                db.session.commit()

            locked_patch = client.patch(
                f"/api/mobile/v1/opportunities/{opp_id}",
                json={"notes": "should fail"},
            )
            assert locked_patch.status_code == 409

            delivery_res = client.post(
                f"/api/mobile/v1/opportunities/{opp_id}/delivery",
                json={
                    "delivered_weight_lbs": 118,
                    "delivery_date": "2026-04-16",
                    "testing_status": "completed",
                    "actual_potency_pct": 23.8,
                    "clean_or_dirty": "clean",
                    "delivery_notes": "delivered from the field",
                },
            )
            assert delivery_res.status_code == 200
            delivery_payload = delivery_res.get_json()["data"]["opportunity"]
            assert delivery_payload["status"] == "delivered"
            assert delivery_payload["delivery"]["delivered_weight_lbs"] == 118
            assert delivery_payload["delivery"]["delivered_by_name"] == "VP Operations"

            detail = client.get(f"/api/mobile/v1/opportunities/{opp_id}")
            assert detail.status_code == 200
            detail_payload = detail.get_json()["data"]
            assert detail_payload["status"] == "delivered"
            assert detail_payload["editable"] is False
            assert detail_payload["delivery"]["delivery_notes"] == "delivered from the field"
            assert detail_payload["photos"]
    finally:
        with app.app_context():
            PhotoAsset.query.filter(PhotoAsset.purchase_id == opp_id).delete(synchronize_session=False)
            purchase = db.session.get(Purchase, opp_id)
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_endpoints_require_auth():
    app = app_module.create_app()
    with app.test_client() as client:
        for method, path in (
            ("get", "/api/mobile/v1/auth/me"),
            ("get", "/api/mobile/v1/opportunities/mine"),
            ("post", "/api/mobile/v1/opportunities"),
            ("post", "/api/mobile/v1/suppliers"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 401
