from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
from models import FieldAccessToken, FieldPurchaseSubmission, Purchase, PurchaseLot, ScaleDevice, SlackIngestedMessage, Supplier, SystemSetting, User, WeightCapture, db
from flask_login import login_user
from services.scale_ingest import create_weight_capture


def _login(client, username: str, password: str = "golddrop2026"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def _call_view_as_user(
    path: str,
    endpoint: str,
    username: str,
    method: str = "GET",
    data: dict | None = None,
    **view_args,
):
    app = app_module.app
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        assert user is not None
        with app.test_request_context(path, method=method, data=data or {}):
            login_user(user)
            rv = app.view_functions[endpoint](**view_args)
            return app.make_response(rv)


def test_bootstrap_init_db_is_idempotent_for_seeded_rows():
    app = app_module.app
    with app.app_context():
        bootstrap_module.init_db(app_module)
        bootstrap_module.init_db(app_module)

        assert User.query.filter_by(username="admin").count() == 1
        assert User.query.filter_by(username="ops").count() == 1
        assert User.query.filter_by(username="viewer").count() == 1
        assert SystemSetting.query.filter_by(key=app_module.SLACK_RUN_MAPPINGS_KEY).count() == 1


def test_settings_route_rejects_non_admin_user():
    page = _call_view_as_user("/settings", "settings", "viewer")
    assert page.status_code in (302, 303)
    assert page.headers["Location"].endswith("/")


def test_settings_route_renders_with_legacy_naive_field_token_expiry():
    app = app_module.app
    with app.app_context():
        token = FieldAccessToken(
            label="Legacy token",
            token_hash="legacy-naive-expiry",
            expires_at=datetime.now() - timedelta(days=1),
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id

    try:
        page = _call_view_as_user("/settings", "settings", "admin")
        assert page.status_code == 200
        assert b"Legacy token" in page.data
        assert b"Expired" in page.data
    finally:
        with app.app_context():
            token = db.session.get(FieldAccessToken, token_id)
            if token is not None:
                db.session.delete(token)
                db.session.commit()


def test_slack_imports_route_is_registered_for_admin():
    page = _call_view_as_user("/settings/slack-imports", "settings_slack_imports", "admin")
    assert page.status_code == 200
    assert b"Slack channel imports" in page.data
    assert b"Auto-ready" in page.data
    assert b"Inbox bucket" in page.data


def test_biomass_route_is_registered_for_admin():
    page = _call_view_as_user("/biomass", "biomass_list", "admin")
    assert page.status_code == 200
    assert b"Biomass Availability Pipeline" in page.data


def test_slack_sync_channel_route_redirects_cleanly_when_bot_token_missing():
    page = _call_view_as_user(
        "/settings/slack_sync_channel",
        "settings_slack_sync_channel",
        "admin",
        method="POST",
        data={"sync_days": "7"},
    )
    assert page.status_code in (302, 303)
    assert "/settings" in page.headers["Location"]


def test_slack_run_mappings_save_json_persists_rules():
    app = app_module.app
    with app.app_context():
        setting = db.session.get(SystemSetting, app_module.SLACK_RUN_MAPPINGS_KEY)
        assert setting is not None
        original_value = setting.value
        payload = original_value

    try:
        save = _call_view_as_user(
            "/settings/slack-run-mappings",
            "settings_slack_run_mappings",
            "admin",
            method="POST",
            data={"action": "save_json", "rules_json": payload},
        )
        assert save.status_code in (302, 303)

        with app.app_context():
            updated = db.session.get(SystemSetting, app_module.SLACK_RUN_MAPPINGS_KEY)
            assert updated is not None
            assert json.loads(updated.value) == json.loads(payload)
    finally:
        with app.app_context():
            setting = db.session.get(SystemSetting, app_module.SLACK_RUN_MAPPINGS_KEY)
            assert setting is not None
            setting.value = original_value
            db.session.commit()


def test_authenticated_dashboard_and_department_views_render():
    dashboard = _call_view_as_user("/", "dashboard", "admin")
    assert dashboard.status_code == 200
    assert b"Extraction dashboard" in dashboard.data

    dept_index = _call_view_as_user("/dept", "dept_index", "admin")
    assert dept_index.status_code == 200
    assert b"Departments" in dept_index.data

    dept_view = _call_view_as_user("/dept/operations", "dept_view", "admin", slug="operations")
    assert dept_view.status_code == 200
    assert b"Operations" in dept_view.data

    purchasing = _call_view_as_user("/biomass-purchasing", "biomass_purchasing_dashboard", "admin")
    assert purchasing.status_code == 200
    assert b"This week" in purchasing.data or b"Inventory on hand" in purchasing.data

    export_runs = _call_view_as_user("/export/runs.csv", "export_csv", "admin", entity="runs")
    assert export_runs.status_code == 200
    assert export_runs.mimetype.startswith("text/csv")


def test_photos_library_renders_for_authenticated_user():
    page = _call_view_as_user("/photos", "photos_library", "viewer")
    assert page.status_code == 200
    assert b"photo" in page.data.lower()


def test_slack_preview_surfaces_candidate_lots_with_tracking_ids():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Farmlane Preview Safety", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 10),
            delivery_date=date(2026, 4, 11),
            status="delivered",
            stated_weight_lbs=120,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"SAFE-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=120,
            remaining_weight_lbs=120,
        )
        db.session.add(lot)
        row = SlackIngestedMessage(
            channel_id="C123",
            message_ts=f"1743200000.{app_module.gen_uuid().replace('-', '')[:6]}",
            raw_text="reactor: A\nsource: Farmlane\nstrain: Blue Dream\nbio lbs: 100",
            message_kind="production_log",
        )
        db.session.add(row)
        db.session.commit()
        row_id = row.id
        lot_tracking_id = db.session.get(PurchaseLot, lot.id).tracking_id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        page = _call_view_as_user(
            f"/settings/slack-imports/{row_id}/preview",
            "settings_slack_import_preview",
            "admin",
            msg_id=row_id,
        )
        assert page.status_code == 200
        assert b"Candidate source lots" in page.data
        assert lot_tracking_id.encode() in page.data
        assert b"score" in page.data
    finally:
        with app.app_context():
            lot_obj = db.session.get(PurchaseLot, lot_id)
            purchase_obj = db.session.get(Purchase, purchase_id)
            supplier_obj = db.session.get(Supplier, supplier_id)
            row_obj = db.session.get(SlackIngestedMessage, row_id)
            if row_obj:
                db.session.delete(row_obj)
            if lot_obj:
                db.session.delete(lot_obj)
            if purchase_obj:
                db.session.delete(purchase_obj)
            if supplier_obj:
                db.session.delete(supplier_obj)
            db.session.commit()


def test_purchase_label_routes_and_scan_route_render_and_resolve():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Label Safety Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 10),
            delivery_date=date(2026, 4, 11),
            status="delivered",
            stated_weight_lbs=90,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"LABEL-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Label Strain",
            weight_lbs=90,
            remaining_weight_lbs=90,
        )
        db.session.add(lot)
        db.session.commit()
        lot = db.session.get(PurchaseLot, lot.id)
        purchase_id = purchase.id
        lot_id = lot.id
        tracking_id = lot.tracking_id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")

            single = client.get(f"/lots/{lot_id}/label")
            assert single.status_code == 200
            assert b"Lot labels" in single.data
            assert tracking_id.encode() in single.data

            multi = client.get(f"/purchases/{purchase_id}/labels")
            assert multi.status_code == 200
            assert b"Print" in multi.data
            assert b"Barcode payload" in multi.data

            scan = client.get(f"/scan/lot/{tracking_id}", follow_redirects=False)
            assert scan.status_code in (302, 303)
            assert f"/purchases/{purchase_id}/journey" in scan.headers["Location"]
            assert f"lot={tracking_id}" in scan.headers["Location"]
    finally:
        with app.app_context():
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


def test_slack_apply_run_carries_manual_lot_selection_into_prefill_session():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Farmlane", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 10),
            delivery_date=date(2026, 4, 11),
            status="delivered",
            stated_weight_lbs=120,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"SAFE-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=120,
            remaining_weight_lbs=120,
        )
        db.session.add(lot)
        row = SlackIngestedMessage(
            channel_id="C124",
            message_ts=f"1743200001.{app_module.gen_uuid().replace('-', '')[:6]}",
            raw_text="reactor: A\nsource: Farmlane\nstrain: Blue Dream\nbio lbs: 100",
            message_kind="production_log",
        )
        db.session.add(row)
        db.session.commit()
        row_id = row.id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                f"/settings/slack-imports/{row_id}/apply-run",
                data={
                    "slack_supplier_mode": "existing",
                    "slack_supplier_id": supplier_id,
                    "slack_selected_allocations_json": json.dumps([{"lot_id": lot_id, "weight_lbs": 100.0}]),
                },
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].endswith("/runs/new")
            with client.session_transaction() as sess:
                prefill = sess.get(app_module.SLACK_RUN_PREFILL_SESSION_KEY)
                assert prefill is not None
                assert prefill["suggested_allocations"] == [{"lot_id": lot_id, "weight_lbs": 100.0}]
    finally:
        with app.app_context():
            row_obj = db.session.get(SlackIngestedMessage, row_id)
            if row_obj:
                db.session.delete(row_obj)
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


def test_field_submission_approve_creates_purchase_and_lots():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Refactor Safety Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        submission = FieldPurchaseSubmission(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 10),
            status="pending",
            lots_json=json.dumps([{"strain": "Blue Dream", "weight_lbs": 5.0}]),
            notes="Safety test submission",
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id
        supplier_id = supplier.id

    try:
        with patch.object(app_module, "notify_slack") as notify_mock:
            resp = _call_view_as_user(
                f"/settings/field_submissions/{submission_id}/approve",
                "field_submission_approve",
                "admin",
                method="POST",
                data={"review_notes": "approved by test"},
                submission_id=submission_id,
            )
            assert resp.status_code in (302, 303)
            notify_mock.assert_called_once()

        with app.app_context():
            submission = db.session.get(FieldPurchaseSubmission, submission_id)
            assert submission is not None
            assert submission.status == "approved"
            assert submission.approved_purchase_id

            purchase = db.session.get(Purchase, submission.approved_purchase_id)
            assert purchase is not None
            assert purchase.supplier_id == supplier_id
            assert purchase.purchase_approved_at is not None

            lots = PurchaseLot.query.filter_by(purchase_id=purchase.id).all()
            assert len(lots) == 1
            assert lots[0].strain_name == "Blue Dream"
            assert float(lots[0].weight_lbs or 0) == 5.0
    finally:
        with app.app_context():
            submission = db.session.get(FieldPurchaseSubmission, submission_id)
            purchase_id = submission.approved_purchase_id if submission else None
            if purchase_id:
                for lot in PurchaseLot.query.filter_by(purchase_id=purchase_id).all():
                    db.session.delete(lot)
                purchase = db.session.get(Purchase, purchase_id)
                if purchase:
                    db.session.delete(purchase)
            submission = db.session.get(FieldPurchaseSubmission, submission_id)
            if submission:
                db.session.delete(submission)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_batch_edit_purchase_path_runs_inventory_and_budget_side_effects():
    touched_purchase = object()
    with (
        patch.object(app_module, "parse_uuid_ids", return_value=["id-1", "id-2"]),
        patch.object(app_module, "apply_batch_purchases", return_value=(2, [], [touched_purchase])),
        patch("gold_drop.batch_edit_module.maintain_purchase_inventory_lots") as maintain_mock,
        patch("gold_drop.batch_edit_module.biomass_budget_snapshot_for_purchase", return_value={"ok": True}) as snap_mock,
        patch("gold_drop.batch_edit_module.enforce_weekly_biomass_purchase_limits") as enforce_mock,
        patch.object(app_module, "log_audit") as audit_mock,
    ):
        resp = _call_view_as_user(
            "/batch-edit/purchases",
            "batch_edit",
            "admin",
            method="POST",
            data={"ids": "id-1,id-2", "return_to": "/purchases"},
            entity="purchases",
        )
        assert resp.status_code in (302, 303)
        assert resp.headers["Location"].endswith("/purchases")
        maintain_mock.assert_called_once_with(app_module, touched_purchase)
        snap_mock.assert_called_once_with(touched_purchase)
        enforce_mock.assert_called_once()
        audit_mock.assert_called_once()


def test_purchase_approve_respects_inline_return_target():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Approve Inline Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date.today(),
            delivery_date=date.today(),
            status="ordered",
            stated_weight_lbs=10.0,
            batch_id="INLINE-APPROVE-001",
        )
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        resp = _call_view_as_user(
            f"/purchases/{purchase_id}/approve",
            "purchase_approve",
            "admin",
            method="POST",
            data={"return_to": "/purchases?status=ordered"},
            purchase_id=purchase_id,
        )
        assert resp.status_code in (302, 303)
        assert resp.headers["Location"].endswith("/purchases?status=ordered")

        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id)
            assert purchase is not None
            assert purchase.purchase_approved_at is not None
    finally:
        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                for lot in PurchaseLot.query.filter_by(purchase_id=purchase_id).all():
                    db.session.delete(lot)
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            db.session.commit()


def test_scale_readiness_models_and_weight_capture_persist():
    app = app_module.app
    with app.app_context():
        operator = User.query.filter_by(username="admin").first()
        assert operator is not None

        device = ScaleDevice(
            name="Receiving Scale A",
            location="Receiving",
            interface_type="serial",
            protocol_type="ascii",
            connection_target="COM3",
            is_active=True,
        )
        db.session.add(device)
        db.session.flush()

        supplier = Supplier(name="Scale Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()

        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=125,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            batch_id=f"SCALE-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()

        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Scale Strain",
            weight_lbs=125,
            remaining_weight_lbs=125,
        )
        db.session.add(lot)
        db.session.flush()

        capture = create_weight_capture(
            app_module,
            capture_type="intake",
            measured_weight=124.6,
            unit="lb",
            source_mode="device",
            device=device,
            purchase=purchase,
            purchase_lot=lot,
            raw_payload="ST,GS, 124.6 lb",
            is_stable=True,
            notes="Scale test capture",
        )
        capture.created_by = operator.id
        db.session.commit()

        capture_id = capture.id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id
        device_id = device.id

        saved = db.session.get(WeightCapture, capture_id)
        assert saved is not None
        assert saved.source_mode == "device"
        assert float(saved.measured_weight or 0) == 124.6
        assert saved.device_id == device_id
        assert saved.purchase_lot_id == lot_id
        assert saved.raw_payload == "ST,GS, 124.6 lb"

    with app.app_context():
        capture = db.session.get(WeightCapture, capture_id)
        if capture is not None:
            db.session.delete(capture)
        lot = db.session.get(PurchaseLot, lot_id)
        if lot is not None:
            db.session.delete(lot)
        purchase = db.session.get(Purchase, purchase_id)
        if purchase is not None:
            db.session.delete(purchase)
        supplier = db.session.get(Supplier, supplier_id)
        if supplier is not None:
            db.session.delete(supplier)
        device = db.session.get(ScaleDevice, device_id)
        if device is not None:
            db.session.delete(device)
        db.session.commit()
