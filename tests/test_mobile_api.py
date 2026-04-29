from __future__ import annotations

from io import BytesIO

from models import AuditLog, ExtractionCharge, PhotoAsset, Purchase, Supplier, SystemSetting, User, db, gen_uuid
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


def _set_mobile_workflows(app, *, buying: str = "1", receiving: str = "1", extraction: str = "1"):
    with app.app_context():
        for key, value in (
            ("standalone_purchasing_enabled", buying),
            ("standalone_receiving_enabled", receiving),
            ("standalone_extraction_enabled", extraction),
        ):
            setting = db.session.get(SystemSetting, key)
            if setting is None:
                setting = SystemSetting(key=key, value=value)
                db.session.add(setting)
            setting.value = value
        db.session.commit()


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
    _set_mobile_workflows(app)
    existing_supplier_id = _create_supplier(app, "Forest Farms")
    created_supplier_id = None
    try:
        with app.test_client() as client:
            _login_mobile(client)
            warning = client.post(
                "/api/mobile/v1/suppliers",
                json={"new_supplier": {"name": "Forrest Farms"}},
            )
            assert warning.status_code == 200
            warning_payload = warning.get_json()["data"]
            assert warning_payload["requires_confirmation"] is True
            assert warning_payload["duplicate_candidates"]
            assert any(candidate["name"] == "Forest Farms" for candidate in warning_payload["duplicate_candidates"])

            confirmed = client.post(
                "/api/mobile/v1/suppliers",
                json={
                    "new_supplier": {"name": "Forresst Farms"},
                    "confirm_new_supplier": True,
                },
            )
            assert confirmed.status_code == 201
            confirmed_payload = confirmed.get_json()["data"]["supplier"]
            assert confirmed_payload["name"] == "Forresst Farms"
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
    _set_mobile_workflows(app)
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


def test_mobile_extraction_run_exception_handling_loops():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    with app.app_context():
        for key, value in (
            ("extraction_policy_primary_soak", "warning"),
            ("extraction_policy_mixer", "warning"),
            ("extraction_policy_flush", "warning"),
            ("extraction_policy_final_purge", "informational"),
        ):
            row = db.session.get(SystemSetting, key)
            if row is None:
                row = SystemSetting(key=key, value=value)
                db.session.add(row)
            row.value = value
        db.session.commit()
    with app.test_client() as client:
        _login_mobile(client)
        with app.app_context():
            supplier = Supplier(name=f"Exception Flow Supplier {gen_uuid()[:6]}", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=app_module.date.today(),
                status="delivered",
                stated_weight_lbs=100,
                actual_weight_lbs=100,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            )
            db.session.add(purchase)
            db.session.flush()
            db.session.add(app_module.PurchaseLot(purchase_id=purchase.id, strain_name="Blue Dream", weight_lbs=100, remaining_weight_lbs=100))
            db.session.commit()
            lot = purchase.lots[0]
            charge = ExtractionCharge(
                purchase_lot_id=lot.id,
                reactor_number=1,
                charged_weight_lbs=22.5,
                source_mode="standalone_extraction",
            )
            db.session.add(charge)
            db.session.commit()
            charge_id = charge.id

        sequence = [
            {"progression_action": "confirm_vacuum_down"},
            {"primary_solvent_charge_lbs": 500, "progression_action": "record_solvent_charge"},
            {"progression_action": "start_primary_soak"},
            {"mixer_started_at": "2026-04-24T09:10", "mixer_ended_at": "2026-04-24T09:20"},
            {"progression_action": "confirm_filter_clear"},
            {"progression_action": "start_pressurization"},
            {"progression_action": "begin_recovery"},
            {"progression_action": "begin_flush_cycle"},
            {"flush_solvent_chiller_temp_f": -45, "flush_plate_temp_f": -41, "progression_action": "verify_flush_temps"},
            {"flush_solvent_charge_lbs": 500, "progression_action": "record_flush_solvent_charge"},
            {"progression_action": "start_flush"},
            {"progression_action": "stop_flush", "flush_short_reason": "Paused early to correct recovery conditions."},
        ]
        for payload in sequence:
            response = client.post(f"/api/mobile/v1/extraction/charges/{charge_id}/run", json=payload)
            assert response.status_code == 200

        missing_flow_reason = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"flow_resumed_decision": "no_adjusting", "progression_action": "confirm_flow_resumed"},
        )
        assert missing_flow_reason.status_code == 400

        flow_adjusting = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={
                "flow_resumed_decision": "no_adjusting",
                "flow_adjustment_reason": "Recovery flow remained restricted after the first flush pass.",
                "progression_action": "confirm_flow_resumed",
            },
        )
        assert flow_adjusting.status_code == 200
        assert flow_adjusting.get_json()["data"]["run"]["progression"]["stage_key"] == "flow_adjustment_required"

        flow_recheck = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "resume_flow_check"},
        )
        assert flow_recheck.status_code == 200
        assert flow_recheck.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_confirm_flow_resumed"

        flow_resumed = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"flow_resumed_decision": "yes", "progression_action": "confirm_flow_resumed"},
        )
        assert flow_resumed.status_code == 200
        assert flow_resumed.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_start_final_purge"

        start_purge = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "start_final_purge"},
        )
        assert start_purge.status_code == 200
        stop_purge = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "stop_final_purge", "final_purge_short_reason": "Stopped early to inspect clarity and vessel response."},
        )
        assert stop_purge.status_code == 200

        clarity_retry = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={
                "final_clarity_decision": "not_yet",
                "final_clarity_reason": "Material was still not fully clear after the first purge pass.",
                "progression_action": "confirm_final_clarity",
            },
        )
        assert clarity_retry.status_code == 200
        assert clarity_retry.get_json()["data"]["run"]["progression"]["stage_key"] == "clarity_adjustment_required"

        resume_purge = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "resume_final_purge"},
        )
        assert resume_purge.status_code == 200
        assert resume_purge.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_start_final_purge"

        restart_purge = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "start_final_purge"},
        )
        assert restart_purge.status_code == 200
        restop_purge = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"progression_action": "stop_final_purge", "final_purge_short_reason": "Second purge pass stopped for another clarity verification."},
        )
        assert restop_purge.status_code == 200

        clarity_yes = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"final_clarity_decision": "yes", "progression_action": "confirm_final_clarity"},
        )
        assert clarity_yes.status_code == 200
        assert clarity_yes.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_complete_shutdown"

        with app.app_context():
            run = db.session.get(ExtractionCharge, charge_id).run
            history_labels = [event.event_label for event in run.booth_session.booth_events.order_by(app_module.ExtractionBoothEvent.created_at.asc()).all()]
            assert "Flow still adjusting" in history_labels
            assert "Flow adjustment resumed" in history_labels
            assert "Final clarity not yet acceptable" in history_labels
            assert "Final purge resumed for additional clarity work" in history_labels
            notification_titles = [
                row.title
                for row in app_module.SupervisorNotification.query.filter_by(run_id=run.id).order_by(app_module.SupervisorNotification.created_at.asc()).all()
            ]
            assert "Flow adjustment required" in notification_titles
            assert "Final clarity still out of scope" in notification_titles
            assert "Final purge finished short of target" not in notification_titles
            notification_reasons = [row.operator_reason for row in app_module.SupervisorNotification.query.filter_by(run_id=run.id).all()]
            assert any(reason and "restricted" in reason for reason in notification_reasons)


def test_mobile_extraction_timing_policy_can_require_supervisor_override():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    with app.app_context():
        for key, value in (
            ("extraction_policy_flush", "supervisor_override"),
            ("extraction_policy_primary_soak", "informational"),
            ("extraction_target_flush_minutes", "10"),
        ):
            row = db.session.get(SystemSetting, key)
            if row is None:
                row = SystemSetting(key=key, value=value)
                db.session.add(row)
            row.value = value
        db.session.commit()
    with app.test_client() as client:
        _login_mobile(client)
        with app.app_context():
            supplier = Supplier(name=f"Override Policy Supplier {gen_uuid()[:6]}", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=app_module.date.today(),
                status="delivered",
                stated_weight_lbs=100,
                actual_weight_lbs=100,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            )
            db.session.add(purchase)
            db.session.flush()
            db.session.add(app_module.PurchaseLot(purchase_id=purchase.id, strain_name="Policy Flower", weight_lbs=100, remaining_weight_lbs=100))
            db.session.commit()
            lot = purchase.lots[0]
            charge = ExtractionCharge(
                purchase_lot_id=lot.id,
                reactor_number=1,
                charged_weight_lbs=22.5,
                source_mode="standalone_extraction",
            )
            db.session.add(charge)
            db.session.commit()
            charge_id = charge.id

        sequence = [
            {"progression_action": "confirm_vacuum_down"},
            {"primary_solvent_charge_lbs": 500, "progression_action": "record_solvent_charge"},
            {"progression_action": "start_primary_soak", "primary_soak_short_reason": "Training override prep."},
            {"progression_action": "start_mixer"},
            {"progression_action": "stop_mixer", "mixer_short_reason": "Training override prep."},
            {"progression_action": "confirm_filter_clear"},
            {"progression_action": "start_pressurization"},
            {"progression_action": "begin_recovery"},
            {"progression_action": "begin_flush_cycle"},
            {"flush_solvent_chiller_temp_f": -45, "flush_plate_temp_f": -41, "progression_action": "verify_flush_temps"},
            {"flush_solvent_charge_lbs": 500, "progression_action": "record_flush_solvent_charge"},
            {"progression_action": "start_flush"},
            {"progression_action": "stop_flush", "flush_short_reason": "Stopped early under override policy test."},
        ]
        for payload in sequence:
            response = client.post(f"/api/mobile/v1/extraction/charges/{charge_id}/run", json=payload)
            assert response.status_code == 200

        blocked = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"flow_resumed_decision": "yes", "progression_action": "confirm_flow_resumed"},
        )
        assert blocked.status_code == 400
        assert "requires supervisor override" in blocked.get_json()["error"]["message"].lower()

        with app.app_context():
            run = db.session.get(ExtractionCharge, charge_id).run
            row = app_module.SupervisorNotification.query.filter_by(run_id=run.id, dedupe_key="timing_short_flush").order_by(app_module.SupervisorNotification.created_at.desc()).first()
            assert row is not None
            row.override_decision = "approved_deviation"
            row.override_reason = "Supervisor approved the short flush for training."
            row.override_at = app_module.datetime.now(app_module.timezone.utc)
            row.status = "resolved"
            db.session.commit()

        resumed = client.post(
            f"/api/mobile/v1/extraction/charges/{charge_id}/run",
            json={"flow_resumed_decision": "yes", "progression_action": "confirm_flow_resumed"},
        )
        assert resumed.status_code == 200
        assert resumed.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_start_final_purge"


def test_mobile_opportunity_edit_delivery_and_photo_flow():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Mobile Supplier {gen_uuid()[:6]}")
    opp_id = None
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
    _set_mobile_workflows(app)
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
    _set_mobile_workflows(app)
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


def test_mobile_receiving_queue_hides_non_operational_purchases_by_default():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Receiving Hidden Supplier {gen_uuid()[:6]}")
    receiver_username = f"receiver_hidden_{gen_uuid()[:6]}"
    purchase_ids: list[str] = []
    try:
        with app.app_context():
            receiver = app_module.User(
                username=receiver_username,
                display_name="Receiving Hidden User",
                role="user",
            )
            receiver.set_password("receiver-pass")
            db.session.add(receiver)
            db.session.flush()
            for status in ("ordered", "cancelled", "complete"):
                purchase = Purchase(
                    supplier_id=supplier_id,
                    purchase_date=app_module.date(2026, 4, 18),
                    availability_date=app_module.date(2026, 4, 18),
                    status=status,
                    stated_weight_lbs=50,
                    purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                )
                db.session.add(purchase)
                db.session.flush()
                purchase_ids.append(purchase.id)
            db.session.commit()

        with app.test_client() as client:
            login = client.post("/api/mobile/v1/auth/login", json={"username": receiver_username, "password": "receiver-pass"})
            assert login.status_code == 200

            listing = client.get("/api/mobile/v1/receiving/queue")
            assert listing.status_code == 200
            ids = {row["id"] for row in listing.get_json()["data"]}
            assert purchase_ids[0] in ids
            assert purchase_ids[1] not in ids
            assert purchase_ids[2] not in ids

            cancelled_listing = client.get("/api/mobile/v1/receiving/queue?status=cancelled")
            assert cancelled_listing.status_code == 200
            cancelled_ids = {row["id"] for row in cancelled_listing.get_json()["data"]}
            assert purchase_ids[1] in cancelled_ids
    finally:
        with app.app_context():
            for purchase_id in purchase_ids:
                purchase = db.session.get(Purchase, purchase_id)
                if purchase:
                    db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            user = User.query.filter_by(username=receiver_username).first()
            if user:
                db.session.delete(user)
            db.session.commit()


def test_mobile_receiving_edit_flow_and_lock_after_downstream_usage():
    app = app_module.create_app()
    _set_mobile_workflows(app)
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
    _set_mobile_workflows(app)
    with app.app_context():
        setting = db.session.get(SystemSetting, "standalone_receiving_enabled")
        setting.value = "0"
        extraction_setting = db.session.get(SystemSetting, "standalone_extraction_enabled")
        extraction_setting.value = "0"
        db.session.commit()
    try:
        with app.test_client() as client:
            _login_mobile(client)
            caps = client.get("/api/mobile/v1/capabilities")
            assert caps.status_code == 200
            payload = caps.get_json()["data"]
            assert payload["write_workflows"]["buying"]["enabled"] is True
            assert payload["write_workflows"]["receiving"]["enabled"] is False
            assert payload["write_workflows"]["extraction"]["enabled"] is False

            denied = client.get("/api/mobile/v1/receiving/queue")
            assert denied.status_code == 403
            assert denied.get_json()["error"]["code"] == "workflow_disabled"

            extraction_denied = client.get("/api/mobile/v1/extraction/board")
            assert extraction_denied.status_code == 403
            assert extraction_denied.get_json()["error"]["code"] == "workflow_disabled"
    finally:
        with app.app_context():
            setting = db.session.get(SystemSetting, "standalone_receiving_enabled")
            setting.value = "1"
            extraction_setting = db.session.get(SystemSetting, "standalone_extraction_enabled")
            extraction_setting.value = "1"
            db.session.commit()


def test_mobile_extraction_board_and_lot_listing():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Extraction Supplier {gen_uuid()[:6]}")
    purchase_id = None
    lot_id = None
    try:
        with app.app_context():
            for key, value in (
                ("extraction_default_biomass_blend_milled_pct", "50"),
                ("extraction_default_fill_count", "2"),
                ("extraction_default_fill_total_weight_lbs", "47.5"),
                ("extraction_default_flush_count", "3"),
                ("extraction_default_flush_total_weight_lbs", "11.5"),
                ("extraction_default_stringer_basket_count", "10"),
                ("extraction_default_crc_blend", "House CRC Default"),
            ):
                setting = db.session.get(SystemSetting, key)
                if setting is None:
                    setting = SystemSetting(key=key, value=value)
                    db.session.add(setting)
                else:
                    setting.value = value
            ops_user = app_module.User.query.filter_by(username="ops").first()
            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 19),
                availability_date=app_module.date(2026, 4, 19),
                status="available",
                stated_weight_lbs=150,
                declared_weight_lbs=150,
                price_per_lb=205,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                created_by_user_id=ops_user.id if ops_user else None,
                testing_status="completed",
                clean_or_dirty="clean",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Tangie",
                weight_lbs=150,
                remaining_weight_lbs=150,
                tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
                potency_pct=29.4,
                milled=True,
                floor_state="reactor_staging",
                location="Prep Bay",
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id
            tracking_id = lot.tracking_id

        with app.test_client() as client:
            _login_mobile(client)
            board = client.get("/api/mobile/v1/extraction/board")
            assert board.status_code == 200
            board_payload = board.get_json()["data"]
            assert board_payload["summary"]["open_lot_count"] >= 1
            assert board_payload["reactor_cards"]
            assert any(option["value"] == "all" for option in board_payload["board_view_options"])

            listing = client.get("/api/mobile/v1/extraction/lots?q=Tang")
            assert listing.status_code == 200
            lots = listing.get_json()["data"]
            assert any(row["id"] == lot_id and row["ready_for_charge"] is True for row in lots)

            detail = client.get(f"/api/mobile/v1/extraction/lots/{lot_id}")
            assert detail.status_code == 200
            detail_payload = detail.get_json()["data"]["lot"]
            assert detail_payload["tracking_id"] == tracking_id
            assert detail_payload["charge_defaults"]["reactor_number"] is None

            lookup = client.get(f"/api/mobile/v1/extraction/lookup/{tracking_id}")
            assert lookup.status_code == 200
            assert lookup.get_json()["data"]["lot"]["id"] == lot_id
    finally:
        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_extraction_charge_and_transition_flow():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Charge Supplier {gen_uuid()[:6]}")
    purchase_id = None
    lot_id = None
    charge_id = None
    try:
        with app.app_context():
            ops_user = app_module.User.query.filter_by(username="ops").first()
            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 19),
                availability_date=app_module.date(2026, 4, 19),
                status="available",
                stated_weight_lbs=120,
                declared_weight_lbs=120,
                price_per_lb=215,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                created_by_user_id=ops_user.id if ops_user else None,
                testing_status="pending",
                clean_or_dirty="clean",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Gary Payton",
                weight_lbs=120,
                remaining_weight_lbs=120,
                tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
                floor_state="inventory",
                location="Dock B",
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id

        with app.test_client() as client:
            _login_mobile(client)
            charge = client.post(
                f"/api/mobile/v1/extraction/lots/{lot_id}/charge",
                json={
                    "charged_weight_lbs": 42.5,
                    "reactor_number": 2,
                    "charged_at": "2026-04-19T08:15",
                    "notes": "Staged from standalone extraction",
                },
            )
            assert charge.status_code == 201
            payload = charge.get_json()["data"]
            charge_row = payload["charge"]
            charge_id = charge_row["id"]
            assert charge_row["source_mode"] == "standalone_extraction"
            assert charge_row["reactor_number"] == 2
            assert payload["lot"]["id"] == lot_id
            assert payload["next_run_url"].endswith("/runs/new?return_to=/floor-ops")

            with client.session_transaction() as session:
                prefill = session.get(app_module.SCAN_RUN_PREFILL_SESSION_KEY)
            assert prefill is not None
            assert prefill["charge_id"] == charge_id
            assert prefill["reactor_number"] == 2
            assert prefill["planned_weight_lbs"] == 42.5

            transition = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/transition",
                json={"target_state": "in_reactor"},
            )
            assert transition.status_code == 200
            transitioned = transition.get_json()["data"]["charge"]
            assert transitioned["status"] == "in_reactor"
            assert any(entry["label"] == "State -> In reactor" for entry in transitioned["history"])

        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id)
            assert charge is not None
            assert charge.source_mode == "standalone_extraction"
            assert charge.status == "in_reactor"
            assert charge.notes == "Staged from standalone extraction"
            audit_rows = AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id).all()
            assert any('"workflow": "extraction"' in (row.details or "") for row in audit_rows)
    finally:
        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id) if charge_id else None
            if charge:
                db.session.delete(charge)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_extraction_run_execution_flow():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Run Supplier {gen_uuid()[:6]}")
    purchase_id = None
    lot_id = None
    charge_id = None
    run_id = None
    try:
        with app.app_context():
            for key, value in (
                ("extraction_default_biomass_blend_milled_pct", "50"),
                ("extraction_default_fill_count", "2"),
                ("extraction_default_fill_total_weight_lbs", "47.5"),
                ("extraction_default_flush_count", "3"),
                ("extraction_default_flush_total_weight_lbs", "11.5"),
                ("extraction_default_stringer_basket_count", "10"),
                ("extraction_default_crc_blend", "House CRC Default"),
                ("extraction_policy_primary_soak", "warning"),
                ("extraction_policy_mixer", "warning"),
                ("extraction_policy_flush", "warning"),
                ("extraction_policy_final_purge", "informational"),
            ):
                setting = db.session.get(SystemSetting, key)
                if setting is None:
                    db.session.add(SystemSetting(key=key, value=value))
                else:
                    setting.value = value
            ops_user = app_module.User.query.filter_by(username="ops").first()
            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 19),
                availability_date=app_module.date(2026, 4, 19),
                status="available",
                stated_weight_lbs=100,
                declared_weight_lbs=100,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                created_by_user_id=ops_user.id if ops_user else None,
                testing_status="completed",
                clean_or_dirty="clean",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Mochi",
                weight_lbs=100,
                remaining_weight_lbs=100,
                tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
                floor_state="reactor_staging",
                location="Prep Bay",
                milled=True,
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id

        with app.test_client() as client:
            _login_mobile(client)
            charge = client.post(
                f"/api/mobile/v1/extraction/lots/{lot_id}/charge",
                json={
                    "charged_weight_lbs": 50,
                    "reactor_number": 1,
                    "charged_at": "2026-04-19T09:00",
                },
            )
            assert charge.status_code == 201
            charge_id = charge.get_json()["data"]["charge"]["id"]

            run_get = client.get(f"/api/mobile/v1/extraction/charges/{charge_id}/run")
            assert run_get.status_code == 200
            run_payload = run_get.get_json()["data"]
            run_id = run_payload["run"]["id"]
            assert run_id is None
            assert run_payload["run"]["run_fill_started_at"] == ""
            assert run_payload["run"]["reactor_number"] == 1
            assert run_payload["run"]["bio_in_reactor_lbs"] == 50.0
            assert run_payload["run"]["progression"]["stage_key"] == "ready_to_confirm_vacuum"
            assert run_payload["run"]["biomass_blend_milled_pct"] == 50.0
            assert run_payload["run"]["biomass_blend_unmilled_pct"] == 50.0
            assert run_payload["run"]["fill_count"] == 2
            assert run_payload["run"]["fill_total_weight_lbs"] == 47.5
            assert run_payload["run"]["flush_count"] == 3
            assert run_payload["run"]["flush_total_weight_lbs"] == 11.5
            assert run_payload["run"]["stringer_basket_count"] == 10
            assert run_payload["run"]["crc_blend"] == "House CRC Default"
            assert run_payload["run"]["inherited"]["tracking_id"]
            assert run_payload["run"]["post_extraction"]["stage_key"] == "blocked_until_run_complete"
            assert run_payload["run"]["post_extraction_pathway_options"]
            assert run_payload["run"]["booth"]["current_stage_key"] == "ready_to_confirm_vacuum"
            assert run_payload["run"]["booth"]["timing_targets"]["primary_soak_minutes"] == 30
            assert run_payload["run"]["booth"]["timing_targets"]["mixer_minutes"] == 5
            assert run_payload["run"]["booth"]["timing_targets"]["flush_minutes"] == 10
            assert run_payload["run"]["timing_controls"]["primary_soak"]["status"] == "not_started"

            confirm_vacuum = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "confirm_vacuum_down"},
            )
            assert confirm_vacuum.status_code == 200
            vacuumed = confirm_vacuum.get_json()["data"]["run"]
            assert vacuumed["progression"]["stage_key"] == "ready_to_record_solvent_charge"

            charge_solvent = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "primary_solvent_charge_lbs": 500,
                    "progression_action": "record_solvent_charge",
                },
            )
            assert charge_solvent.status_code == 200
            solvent_recorded = charge_solvent.get_json()["data"]["run"]
            assert solvent_recorded["primary_solvent_charge_lbs"] == 500.0
            assert solvent_recorded["progression"]["stage_key"] == "ready_to_start_primary_soak"

            start_soak = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "start_primary_soak"},
            )
            assert start_soak.status_code == 200
            soak_started = start_soak.get_json()["data"]["run"]
            assert soak_started["run_fill_started_at"]
            assert soak_started["progression"]["stage_key"] == "ready_to_start_mixer"

            run_save = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "run_fill_started_at": "2026-04-19T09:05",
                    "run_fill_ended_at": "2026-04-19T09:40",
                    "biomass_blend_milled_pct": 80,
                    "biomass_blend_unmilled_pct": 20,
                    "flush_count": 2,
                    "flush_total_weight_lbs": 10,
                    "fill_count": 1,
                    "fill_total_weight_lbs": 50,
                    "stringer_basket_count": 8,
                    "crc_blend": "House CRC",
                    "mixer_started_at": "2026-04-19T09:10",
                    "mixer_ended_at": "2026-04-19T09:20",
                    "notes": "Touch-first run capture",
                },
            )
            assert run_save.status_code == 200
            saved = run_save.get_json()["data"]["run"]
            assert saved["run_fill_duration_minutes"] is not None
            assert saved["mixer_duration_minutes"] == 10
            assert saved["timing_controls"]["primary_soak"]["status"] == "on_target"
            assert saved["timing_controls"]["mixer"]["status"] == "on_target"
            assert saved["crc_blend"] == "House CRC"
            run_id = saved["id"]
            assert saved["open_main_app_url"].endswith(f"/runs/{run_id}/edit?return_to=/floor-ops")

            filter_clear = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "confirm_filter_clear"},
            )
            assert filter_clear.status_code == 200
            assert filter_clear.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_start_pressurization"

            pressurize = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "start_pressurization"},
            )
            assert pressurize.status_code == 200
            assert pressurize.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_begin_recovery"

            recovery = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "begin_recovery"},
            )
            assert recovery.status_code == 200
            assert recovery.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_begin_flush_cycle"

            begin_flush_cycle = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "begin_flush_cycle"},
            )
            assert begin_flush_cycle.status_code == 200
            assert begin_flush_cycle.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_verify_flush_temps"

            verify_temps = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "flush_solvent_chiller_temp_f": -45,
                    "flush_plate_temp_f": -41,
                    "flush_temp_slack_post_confirmed": "1",
                    "progression_action": "verify_flush_temps",
                },
            )
            assert verify_temps.status_code == 200
            assert verify_temps.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_record_flush_solvent_charge"

            flush_charge = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "flush_solvent_charge_lbs": 500,
                    "progression_action": "record_flush_solvent_charge",
                },
            )
            assert flush_charge.status_code == 200
            assert flush_charge.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_flush"

            start_flush = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "start_flush"},
            )
            assert start_flush.status_code == 200
            assert start_flush.get_json()["data"]["run"]["progression"]["stage_key"] == "flushing"

            stop_flush = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "stop_flush", "flush_short_reason": "Stopped early during the test path for timing validation."},
            )
            assert stop_flush.status_code == 200
            stopped_flush = stop_flush.get_json()["data"]["run"]
            assert stopped_flush["flush_duration_minutes"] is not None
            assert stopped_flush["progression"]["stage_key"] == "ready_to_confirm_flow_resumed"

            flow_resumed = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "flow_resumed_decision": "yes",
                    "progression_action": "confirm_flow_resumed",
                },
            )
            assert flow_resumed.status_code == 200
            assert flow_resumed.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_start_final_purge"

            start_final_purge = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "start_final_purge"},
            )
            assert start_final_purge.status_code == 200
            assert start_final_purge.get_json()["data"]["run"]["progression"]["stage_key"] == "purging"

            stop_final_purge = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "stop_final_purge", "final_purge_short_reason": "Stopped early during the test path for timing validation."},
            )
            assert stop_final_purge.status_code == 200
            assert stop_final_purge.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_confirm_clarity"

            final_clarity = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "final_clarity_decision": "yes",
                    "progression_action": "confirm_final_clarity",
                },
            )
            assert final_clarity.status_code == 200
            assert final_clarity.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_complete_shutdown"

            shutdown = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "shutdown_recovery_inlets_closed": "1",
                    "shutdown_filtration_pumpdown_started": "1",
                    "shutdown_nitrogen_off": "1",
                    "shutdown_dewax_inlet_closed": "1",
                    "progression_action": "complete_shutdown",
                },
            )
            assert shutdown.status_code == 200
            assert shutdown.get_json()["data"]["run"]["progression"]["stage_key"] == "ready_to_complete"

            complete_run = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"progression_action": "mark_complete"},
            )
            assert complete_run.status_code == 200
            completed = complete_run.get_json()["data"]["run"]
            assert completed["run_completed_at"]
            assert completed["progression"]["stage_key"] == "completed"

            blocked_start = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"post_extraction_action": "start_post_extraction"},
            )
            assert blocked_start.status_code == 400
            assert "Select the post-extraction pathway" in blocked_start.get_json()["error"]["message"]

            choose_pathway = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"post_extraction_pathway": "minor_run_200"},
            )
            assert choose_pathway.status_code == 200
            chose_pathway = choose_pathway.get_json()["data"]["run"]
            assert chose_pathway["post_extraction"]["stage_key"] == "ready_to_start"

            start_post = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "post_extraction_pathway": "minor_run_200",
                    "post_extraction_action": "start_post_extraction",
                },
            )
            assert start_post.status_code == 200
            started_post = start_post.get_json()["data"]["run"]
            assert started_post["post_extraction_started_at"]
            assert started_post["post_extraction"]["stage_key"] == "ready_to_confirm_initial_outputs"

            blocked_confirm = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={"post_extraction_action": "confirm_initial_outputs"},
            )
            assert blocked_confirm.status_code == 400
            assert "Enter both wet THCA and wet HTE" in blocked_confirm.get_json()["error"]["message"]

            confirm_outputs = client.post(
                f"/api/mobile/v1/extraction/charges/{charge_id}/run",
                json={
                    "wet_hte_g": 1800,
                    "wet_thca_g": 4200,
                    "post_extraction_action": "confirm_initial_outputs",
                    "pot_pour_offgas_started_at": "2026-04-19T10:00",
                    "pot_pour_offgas_completed_at": "2026-04-19T12:00",
                    "pot_pour_daily_stir_count": 2,
                    "pot_pour_centrifuged_at": "2026-04-20T09:00",
                    "thca_oven_started_at": "2026-04-19T12:30",
                    "thca_oven_completed_at": "2026-04-20T04:30",
                    "thca_milled_at": "2026-04-20T08:00",
                    "thca_destination": "make_ld",
                    "hte_offgas_started_at": "2026-04-19T10:30",
                    "hte_offgas_completed_at": "2026-04-21T10:30",
                    "hte_clean_decision": "dirty",
                    "hte_filter_outcome": "needs_prescott",
                    "hte_prescott_processed_at": "2026-04-21T15:00",
                    "hte_potency_disposition": "hold_distillate",
                    "hte_queue_destination": "liquid_loud_hold",
                },
            )
            assert confirm_outputs.status_code == 200
            confirmed_outputs = confirm_outputs.get_json()["data"]["run"]
            assert confirmed_outputs["wet_hte_g"] == 1800.0
            assert confirmed_outputs["wet_thca_g"] == 4200.0
            assert confirmed_outputs["post_extraction_initial_outputs_recorded_at"]
            assert confirmed_outputs["post_extraction"]["stage_key"] == "session_started"
            assert confirmed_outputs["thca_destination"] == "make_ld"
            assert confirmed_outputs["hte_clean_decision"] == "dirty"
            assert confirmed_outputs["hte_filter_outcome"] == "needs_prescott"
            assert confirmed_outputs["hte_queue_destination"] == "liquid_loud_hold"

        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id)
            assert charge is not None
            assert charge.run_id == run_id
            assert charge.status == "completed"
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.biomass_blend_milled_pct == 80
            assert run.flush_count == 2
            assert run.fill_total_weight_lbs == 50
            assert run.stringer_basket_count == 8
            assert run.crc_blend == "House CRC"
            assert run.run_completed_at is not None
            assert run.post_extraction_pathway == "minor_run_200"
            assert run.post_extraction_started_at is not None
            assert run.post_extraction_initial_outputs_recorded_at is not None
            assert run.wet_hte_g == 1800
            assert run.wet_thca_g == 4200
            assert run.pot_pour_daily_stir_count == 2
            assert run.thca_destination == "make_ld"
            assert run.hte_clean_decision == "dirty"
            assert run.hte_filter_outcome == "needs_prescott"
            assert run.hte_potency_disposition == "hold_distillate"
            assert run.hte_queue_destination == "liquid_loud_hold"
            assert run.notes == "Touch-first run capture"
            assert run.booth_session is not None
            assert run.booth_session.primary_solvent_charge_lbs == 500
            assert run.booth_session.flush_solvent_chiller_temp_f == -45
            assert run.booth_session.flush_solvent_charge_lbs == 500
            assert run.booth_session.flow_resumed_decision == "yes"
            assert run.booth_session.final_clarity_decision == "yes"
            assert run.booth_session.booth_process_completed_at is not None
            assert run.booth_session.status == "completed"
    finally:
        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id) if charge_id else None
            if charge:
                db.session.delete(charge)
            if run_id:
                app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
                run = db.session.get(app_module.Run, run_id)
                if run:
                    db.session.delete(run)
                db.session.flush()
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_extraction_board_view_filtering():
    app = app_module.create_app()
    _set_mobile_workflows(app)
    supplier_id = _create_supplier(app, f"Filter Supplier {gen_uuid()[:6]}")
    purchase_id = None
    running_charge_id = None
    pending_charge_id = None
    try:
        with app.app_context():
            ops_user = app_module.User.query.filter_by(username="ops").first()
            purchase = Purchase(
                supplier_id=supplier_id,
                purchase_date=app_module.date(2026, 4, 19),
                availability_date=app_module.date(2026, 4, 19),
                status="available",
                stated_weight_lbs=180,
                declared_weight_lbs=180,
                price_per_lb=220,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                created_by_user_id=ops_user.id if ops_user else None,
                testing_status="completed",
                clean_or_dirty="clean",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id

            lot_running = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Super Boof",
                weight_lbs=90,
                remaining_weight_lbs=90,
                tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
                floor_state="reactor_staging",
                milled=True,
            )
            lot_pending = app_module.PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Permanent Marker",
                weight_lbs=90,
                remaining_weight_lbs=90,
                tracking_id=f"LOT-{gen_uuid()[:8].upper()}",
                floor_state="reactor_staging",
                milled=True,
            )
            db.session.add(lot_running)
            db.session.add(lot_pending)
            db.session.flush()

            running_charge = ExtractionCharge(
                purchase_lot_id=lot_running.id,
                charged_weight_lbs=45,
                reactor_number=1,
                charged_at=app_module.datetime.now(app_module.timezone.utc),
                source_mode="standalone_extraction",
                status="running",
                created_by=ops_user.id if ops_user else None,
            )
            pending_charge = ExtractionCharge(
                purchase_lot_id=lot_pending.id,
                charged_weight_lbs=42,
                reactor_number=2,
                charged_at=app_module.datetime.now(app_module.timezone.utc),
                source_mode="standalone_extraction",
                status="pending",
                created_by=ops_user.id if ops_user else None,
            )
            db.session.add(running_charge)
            db.session.add(pending_charge)
            db.session.commit()
            running_charge_id = running_charge.id
            pending_charge_id = pending_charge.id

        with app.test_client() as client:
            _login_mobile(client)
            running = client.get("/api/mobile/v1/extraction/board?board_view=running")
            assert running.status_code == 200
            running_payload = running.get_json()["data"]
            assert running_payload["board_view"] == "running"
            assert len(running_payload["reactor_cards"]) == 1
            assert running_payload["reactor_cards"][0]["reactor_number"] == 1
            assert running_payload["reactor_cards"][0]["state_key"] == "running"

            pending = client.get("/api/mobile/v1/extraction/board?board_view=pending")
            assert pending.status_code == 200
            pending_payload = pending.get_json()["data"]
            assert pending_payload["board_view"] == "pending"
            assert len(pending_payload["reactor_cards"]) == 1
            assert pending_payload["reactor_cards"][0]["reactor_number"] == 2
            assert pending_payload["reactor_cards"][0]["state_key"] == "pending"
    finally:
        with app.app_context():
            pending_charge = db.session.get(ExtractionCharge, pending_charge_id) if pending_charge_id else None
            if pending_charge:
                db.session.delete(pending_charge)
            running_charge = db.session.get(ExtractionCharge, running_charge_id) if running_charge_id else None
            if running_charge:
                db.session.delete(running_charge)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_write_origin_enforcement_and_audit_log():
    app = app_module.create_app()
    _set_mobile_workflows(app)
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
    _set_mobile_workflows(app)
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
