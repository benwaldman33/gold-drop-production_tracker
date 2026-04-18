from __future__ import annotations

from io import BytesIO

from models import AuditLog, PhotoAsset, Purchase, Supplier, SystemSetting, db, gen_uuid
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


def test_mobile_supplier_reads_hide_inactive_and_merged_suppliers():
    app = app_module.create_app()
    active_id = _create_supplier(app, f"Active Supplier {gen_uuid()[:6]}")
    hidden_id = _create_supplier(app, f"Hidden Supplier {gen_uuid()[:6]}")
    try:
        with app.app_context():
            hidden = db.session.get(Supplier, hidden_id)
            hidden.is_active = False
            hidden.merged_into_supplier_id = active_id
            db.session.commit()

        with app.test_client() as client:
            _login_mobile(client)
            listing = client.get("/api/mobile/v1/suppliers")
            assert listing.status_code == 200
            rows = listing.get_json()["data"]
            ids = {row["id"] for row in rows}
            assert active_id in ids
            assert hidden_id not in ids

            detail = client.get(f"/api/mobile/v1/suppliers/{hidden_id}")
            assert detail.status_code == 404
    finally:
        with app.app_context():
            for supplier_id in (hidden_id, active_id):
                supplier = db.session.get(Supplier, supplier_id)
                if supplier:
                    db.session.delete(supplier)
            db.session.commit()


def test_mobile_supplier_create_accepts_standalone_form_shape():
    app = app_module.create_app()
    created_supplier_id = None
    try:
        with app.test_client() as client:
            _login_mobile(client)
            response = client.post(
                "/api/mobile/v1/suppliers",
                json={
                    "name": f"Standalone Supplier {gen_uuid()[:6]}",
                    "contact_name": "Buyer Contact",
                    "phone": "555-0101",
                    "email": "buyer@example.com",
                    "location": "Salinas",
                    "notes": "created from standalone form",
                    "confirm_new_supplier": True,
                },
            )
            assert response.status_code == 201
            payload = response.get_json()["data"]["supplier"]
            created_supplier_id = payload["id"]
            assert payload["name"].startswith("Standalone Supplier")

        with app.app_context():
            supplier = db.session.get(Supplier, created_supplier_id)
            assert supplier is not None
            assert supplier.contact_name == "Buyer Contact"
            assert supplier.contact_phone == "555-0101"
            assert supplier.contact_email == "buyer@example.com"
            assert supplier.location == "Salinas"
            assert supplier.notes == "created from standalone form"
    finally:
        with app.app_context():
            supplier = db.session.get(Supplier, created_supplier_id) if created_supplier_id else None
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


def test_mobile_opportunity_create_enriches_existing_supplier_blank_fields():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Existing Supplier {gen_uuid()[:6]}")
    purchase_id = None
    try:
        with app.app_context():
            supplier = db.session.get(Supplier, supplier_id)
            supplier.contact_name = None
            supplier.contact_phone = None
            supplier.contact_email = None
            supplier.location = None
            db.session.commit()

        with app.test_client() as client:
            _login_mobile(client)
            create_res = client.post(
                "/api/mobile/v1/opportunities",
                json={
                    "supplier_id": supplier_id,
                    "new_supplier_contact_name": "Maya Ortiz",
                    "new_supplier_phone": "555-2000",
                    "new_supplier_email": "maya@example.com",
                    "new_supplier_location": "Salinas",
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
            purchase_id = create_res.get_json()["data"]["opportunity"]["id"]

        with app.app_context():
            supplier = db.session.get(Supplier, supplier_id)
            assert supplier is not None
            assert supplier.contact_name == "Maya Ortiz"
            assert supplier.contact_phone == "555-2000"
            assert supplier.contact_email == "maya@example.com"
            assert supplier.location == "Salinas"
    finally:
        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                for photo in PhotoAsset.query.filter_by(purchase_id=purchase.id).all():
                    db.session.delete(photo)
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
            ("get", "/api/mobile/v1/capabilities"),
            ("get", "/api/mobile/v1/opportunities/mine"),
            ("post", "/api/mobile/v1/opportunities"),
            ("post", "/api/mobile/v1/suppliers"),
            ("get", "/api/mobile/v1/receiving/queue"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 401


def test_mobile_receiving_queue_and_receive_flow():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Receiving Supplier {gen_uuid()[:6]}")
    receiver_id = None
    receiver_username = f"receiver_{gen_uuid()[:6]}"
    purchase_id = None
    try:
        with app.app_context():
            receiver = app_module.User(
                username=receiver_username,
                display_name="Receiving User",
                role="user",
            )
            receiver.set_password("receiver-pass")
            db.session.add(receiver)
            db.session.flush()
            receiver_id = receiver.id

            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 15),
                availability_date=app_module.date(2026, 4, 15),
                status="ordered",
                stated_weight_lbs=95,
                declared_weight_lbs=95,
                price_per_lb=245,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id

            lot = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="MAC 1",
                weight_lbs=95,
                remaining_weight_lbs=95,
            )
            db.session.add(lot)
            db.session.commit()

        with app.test_client() as client:
            login = client.post("/api/mobile/v1/auth/login", json={"username": receiver_username, "password": "receiver-pass"})
            assert login.status_code == 200
            permissions = login.get_json()["data"]["permissions"]
            assert permissions["can_receive_intake"] is True

            listing = client.get("/api/mobile/v1/receiving/queue")
            assert listing.status_code == 200
            rows = listing.get_json()["data"]
            assert any(row["id"] == purchase_id for row in rows)

            detail = client.get(f"/api/mobile/v1/receiving/queue/{purchase_id}")
            assert detail.status_code == 200
            detail_payload = detail.get_json()["data"]
            assert detail_payload["receiving"]["queue_state"] == "ready"
            assert detail_payload["receiving"]["receiving_editable"] is True

            receive = client.post(
                f"/api/mobile/v1/receiving/queue/{purchase_id}/receive",
                json={
                    "delivered_weight_lbs": 92.5,
                    "delivery_date": "2026-04-16",
                    "testing_status": "pending",
                    "clean_or_dirty": "clean",
                    "delivery_notes": "Received by intake team",
                    "location": "Receiving Vault",
                    "floor_state": "receiving",
                },
            )
            assert receive.status_code == 200
            receive_payload = receive.get_json()["data"]["receiving"]
            assert receive_payload["status"] == "delivered"
            assert receive_payload["receiving"]["location"] == "Receiving Vault"
            assert receive_payload["receiving"]["receiving_editable"] is True

            photo = client.post(
                f"/api/mobile/v1/receiving/queue/{purchase_id}/photos",
                data={
                    "photo_context": "delivery",
                    "photo": (BytesIO(b"receipt-image"), "receiving.jpg"),
                },
                content_type="multipart/form-data",
            )
            assert photo.status_code == 201
            assert photo.get_json()["data"]["photo_context"] == "delivery"

        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id)
            assert purchase.status == "delivered"
            assert purchase.delivery_recorded_by_user_id == receiver_id
            lot = purchase.lots.first()
            assert lot.location == "Receiving Vault"
            assert lot.floor_state == "receiving"
    finally:
        with app.app_context():
            if purchase_id:
                PhotoAsset.query.filter(PhotoAsset.purchase_id == purchase_id).delete(synchronize_session=False)
                purchase = db.session.get(Purchase, purchase_id)
                if purchase:
                    db.session.delete(purchase)
            if receiver_id:
                receiver = db.session.get(app_module.User, receiver_id)
                if receiver:
                    db.session.delete(receiver)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_receiving_edit_flow_and_lock_after_downstream_usage():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Receiving Edit Supplier {gen_uuid()[:6]}")
    receiver_id = None
    receiver_username = f"receiver_edit_{gen_uuid()[:6]}"
    purchase_id = None
    lot_id = None
    run_id = None
    try:
        with app.app_context():
            receiver = app_module.User(
                username=receiver_username,
                display_name="Receiving Editor",
                role="user",
            )
            receiver.set_password("receiver-pass")
            db.session.add(receiver)
            db.session.flush()
            receiver_id = receiver.id

            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 15),
                availability_date=app_module.date(2026, 4, 15),
                status="ordered",
                stated_weight_lbs=95,
                declared_weight_lbs=95,
                price_per_lb=245,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id

            lot = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="MAC 1",
                weight_lbs=95,
                remaining_weight_lbs=95,
                floor_state="receiving",
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id

        with app.test_client() as client:
            login = client.post("/api/mobile/v1/auth/login", json={"username": receiver_username, "password": "receiver-pass"})
            assert login.status_code == 200

            receive = client.post(
                f"/api/mobile/v1/receiving/queue/{purchase_id}/receive",
                json={
                    "delivered_weight_lbs": 92.5,
                    "delivery_date": "2026-04-16",
                    "testing_status": "pending",
                    "clean_or_dirty": "clean",
                    "delivery_notes": "Received by intake team",
                    "location": "Receiving Vault",
                    "floor_state": "receiving",
                },
            )
            assert receive.status_code == 200

            edit = client.patch(
                f"/api/mobile/v1/receiving/queue/{purchase_id}",
                json={
                    "delivered_weight_lbs": 91.0,
                    "delivery_date": "2026-04-17",
                    "testing_status": "completed",
                    "actual_potency_pct": 24.1,
                    "clean_or_dirty": "clean",
                    "delivery_notes": "Adjusted after final dock count",
                    "location": "Vault B",
                    "floor_state": "inventory",
                    "lot_notes": "Moved after recount",
                },
            )
            assert edit.status_code == 200
            edit_payload = edit.get_json()["data"]["receiving"]
            assert edit_payload["delivery"]["delivered_weight_lbs"] == 91.0
            assert edit_payload["receiving"]["location"] == "Vault B"
            assert edit_payload["receiving"]["last_receiving_edit_by"] == "Receiving Editor"

        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id)
            lot = db.session.get(app_module.PurchaseLot, lot_id)
            assert purchase.delivery_recorded_by_user_id == receiver_id
            assert purchase.actual_weight_lbs == 91.0
            assert purchase.delivery_notes == "Adjusted after final dock count"
            assert lot.location == "Vault B"
            assert lot.floor_state == "inventory"
            assert lot.notes == "Moved after recount"
            audit_rows = AuditLog.query.filter_by(entity_type="purchase", entity_id=purchase_id, action="receive_edit").all()
            assert len(audit_rows) == 1
            assert '"delivered_weight_lbs"' in (audit_rows[0].details or "")

            run = app_module.Run(
                run_date=app_module.date(2026, 4, 18),
                reactor_number=1,
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot_id, weight_lbs=15))
            db.session.commit()

        with app.test_client() as client:
            login = client.post("/api/mobile/v1/auth/login", json={"username": receiver_username, "password": "receiver-pass"})
            assert login.status_code == 200
            detail = client.get(f"/api/mobile/v1/receiving/queue/{purchase_id}")
            assert detail.status_code == 200
            assert detail.get_json()["data"]["receiving"]["receiving_editable"] is False
            assert "downstream processing" in (detail.get_json()["data"]["receiving"]["locked_reason"] or "").lower()

            locked = client.patch(
                f"/api/mobile/v1/receiving/queue/{purchase_id}",
                json={
                    "delivered_weight_lbs": 90.0,
                    "delivery_date": "2026-04-17",
                },
            )
            assert locked.status_code == 409
            assert locked.get_json()["error"]["code"] == "receiving_locked"
    finally:
        with app.app_context():
            PhotoAsset.query.filter(PhotoAsset.purchase_id == purchase_id).delete(synchronize_session=False)
            if run_id:
                run_input = app_module.RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
                if run_input:
                    db.session.delete(run_input)
                run = db.session.get(app_module.Run, run_id)
                if run:
                    db.session.delete(run)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            if receiver_id:
                receiver = db.session.get(app_module.User, receiver_id)
                if receiver:
                    db.session.delete(receiver)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_capabilities_and_workflow_toggles():
    app = app_module.create_app()
    with app.app_context():
        setting = db.session.get(SystemSetting, "standalone_receiving_enabled")
        setting.value = "0"
        db.session.commit()
    try:
        with app.test_client() as client:
            _login_mobile(client)
            caps = client.get("/api/mobile/v1/capabilities")
            assert caps.status_code == 200
            payload = caps.get_json()["data"]
            assert payload["write_workflows"]["buying"]["enabled"] is True
            assert payload["write_workflows"]["receiving"]["enabled"] is False

            denied = client.get("/api/mobile/v1/receiving/queue")
            assert denied.status_code == 403
            assert denied.get_json()["error"]["code"] == "workflow_disabled"
    finally:
        with app.app_context():
            setting = db.session.get(SystemSetting, "standalone_receiving_enabled")
            setting.value = "1"
            db.session.commit()


def test_mobile_write_origin_enforcement_and_audit_log():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Audit Supplier {gen_uuid()[:6]}")
    purchase_id = None
    try:
        with app.test_client() as client:
            _login_mobile(client)
            blocked = client.post(
                "/api/mobile/v1/opportunities",
                json={
                    "supplier_id": supplier_id,
                    "strain_name": "Blue Dream",
                    "expected_weight_lbs": 40,
                },
                headers={"Origin": "https://evil.example"},
            )
            assert blocked.status_code == 403

            created = client.post(
                "/api/mobile/v1/opportunities",
                json={
                    "supplier_id": supplier_id,
                    "strain_name": "Blue Dream",
                    "expected_weight_lbs": 40,
                },
            )
            assert created.status_code == 201
            purchase_id = created.get_json()["data"]["opportunity"]["id"]

        with app.app_context():
            audit_rows = AuditLog.query.filter(
                AuditLog.entity_type == "purchase",
                AuditLog.entity_id == purchase_id,
            ).all()
            assert any('"source": "mobile_api"' in (row.details or "") for row in audit_rows)
    finally:
        with app.app_context():
            PhotoAsset.query.filter(PhotoAsset.purchase_id == purchase_id).delete(synchronize_session=False)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_delivery_photo_upload_limit_enforced():
    app = app_module.create_app()
    supplier_id = _create_supplier(app, f"Limit Supplier {gen_uuid()[:6]}")
    purchase_id = None
    old_limit = app.config.get("MOBILE_UPLOAD_MAX_FILES_PER_REQUEST")
    app.config["MOBILE_UPLOAD_MAX_FILES_PER_REQUEST"] = 1
    try:
        with app.app_context():
            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 15),
                availability_date=app_module.date(2026, 4, 15),
                status="committed",
                stated_weight_lbs=50,
                declared_weight_lbs=50,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                created_by_user_id=app_module.User.query.filter_by(username="ops").first().id,
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            db.session.add(app_module.PurchaseLot(purchase_id=purchase.id, strain_name="MAC 1", weight_lbs=50, remaining_weight_lbs=50))
            db.session.commit()

        with app.test_client() as client:
            _login_mobile(client)
            res = client.post(
                f"/api/mobile/v1/receiving/queue/{purchase_id}/photos",
                data={
                    "photo_context": "delivery",
                    "photo": [
                        (BytesIO(b"a"), "one.jpg"),
                        (BytesIO(b"b"), "two.jpg"),
                    ],
                },
                content_type="multipart/form-data",
            )
            assert res.status_code == 400
            assert "at most 1 files" in res.get_json()["error"]["message"]
    finally:
        app.config["MOBILE_UPLOAD_MAX_FILES_PER_REQUEST"] = old_limit
        with app.app_context():
            PhotoAsset.query.filter(PhotoAsset.purchase_id == purchase_id).delete(synchronize_session=False)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()
