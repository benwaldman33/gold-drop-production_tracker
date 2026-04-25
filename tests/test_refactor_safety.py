from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.purchases_module as purchases_module
from models import ApiClient, AuditLog, BiomassAvailability, ExtractionCharge, FieldAccessToken, FieldPurchaseSubmission, LabTest, LotScanEvent, PhotoAsset, Purchase, PurchaseLot, RemoteSite, ScaleDevice, SlackIngestedMessage, Supplier, SupplierAttachment, SystemSetting, User, WeightCapture, db, gen_uuid
from flask_login import login_user
from services.scale_ingest import create_weight_capture
from services.supplier_merge import supplier_merge_preview


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
    with patch.object(app_module, "_seed_historical_data") as seed_mock:
        with app.app_context():
            bootstrap_module.init_db(app_module)
            bootstrap_module.init_db(app_module)

            assert User.query.filter_by(username="admin").count() == 1
            assert User.query.filter_by(username="ops").count() == 1
            assert User.query.filter_by(username="viewer").count() == 1
            assert SystemSetting.query.filter_by(key=app_module.SLACK_RUN_MAPPINGS_KEY).count() == 1

        seed_mock.assert_not_called()


def test_settings_route_rejects_non_admin_user():
    page = _call_view_as_user("/settings", "settings", "viewer")
    assert page.status_code in (302, 303)
    assert page.headers["Location"].endswith("/")


def test_supplier_new_requires_confirmation_for_close_duplicate_names():
    app = app_module.create_app()
    existing_id = None
    created_id = None
    try:
        with app.app_context():
            existing = Supplier(name="Forest Farms", is_active=True)
            db.session.add(existing)
            db.session.commit()
            existing_id = existing.id

        with app.test_client() as client:
            warning = _call_view_as_user(
                "/suppliers/new",
                "supplier_new",
                "ops",
                method="POST",
                data={
                    "name": "Forrest Farms",
                    "contact_name": "Buyer",
                    "contact_phone": "555-0101",
                    "contact_email": "buyer@example.com",
                    "location": "Salinas",
                    "notes": "possible duplicate",
                },
            )
            assert warning.status_code == 200
            assert b"Possible duplicate supplier" in warning.data
            assert b"Forest Farms" in warning.data
            with app.app_context():
                assert Supplier.query.filter_by(name="Forrest Farms").count() == 0

            confirmed = _call_view_as_user(
                "/suppliers/new",
                "supplier_new",
                "ops",
                method="POST",
                data={
                    "name": "Forrest Farms",
                    "contact_name": "Buyer",
                    "contact_phone": "555-0101",
                    "contact_email": "buyer@example.com",
                    "location": "Salinas",
                    "notes": "confirmed duplicate create",
                    "confirm_new_supplier": "1",
                },
            )
            assert confirmed.status_code in (302, 303)

        with app.app_context():
            created = Supplier.query.filter_by(name="Forrest Farms").first()
            assert created is not None
            created_id = created.id
    finally:
        with app.app_context():
            for supplier_id in (created_id, existing_id):
                if not supplier_id:
                    continue
                supplier = db.session.get(Supplier, supplier_id)
                if supplier is not None:
                    db.session.delete(supplier)
            db.session.commit()


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


def test_settings_route_renders_api_clients_section():
    page = _call_view_as_user("/settings", "settings", "admin")
    assert page.status_code == 200
    assert b"Internal API Clients" in page.data
    assert b"Create API Client" in page.data
    assert b"Recent API Request Log" in page.data


def test_settings_route_renders_remote_sites_section():
    page = _call_view_as_user("/settings", "settings", "admin")
    assert page.status_code == 200
    assert b"Remote Sites" in page.data
    assert b"Add Remote Site" in page.data


def test_settings_route_renders_smart_scales_section():
    page = _call_view_as_user("/settings", "settings", "admin")
    assert page.status_code == 200
    assert b"Smart Scales" in page.data
    assert b"Add Scale Device" in page.data
    assert b"Recent Weight Captures" in page.data


def test_cross_site_ops_is_hidden_until_enabled():
    app = app_module.app
    with app.app_context():
        original = SystemSetting.get("cross_site_ops_enabled", "0")
        setting = db.session.get(SystemSetting, "cross_site_ops_enabled")
        if setting is None:
            setting = SystemSetting(key="cross_site_ops_enabled", value="0", description="Enable cross-site operations UI surfaces for this site")
            db.session.add(setting)
        setting.value = "0"
        db.session.commit()

    client = app.test_client()
    _login(client, "admin")
    hidden = client.get("/cross-site", follow_redirects=False)
    assert hidden.status_code == 404

    try:
        with app.app_context():
            db.session.get(SystemSetting, "cross_site_ops_enabled").value = "1"
            db.session.commit()
        visible = client.get("/", follow_redirects=True)
        assert b"Cross-Site Ops" in visible.data
        page = client.get("/cross-site", follow_redirects=False)
        assert page.status_code == 200
        assert b"Cross-Site Ops" in page.data
        suppliers = client.get("/cross-site/suppliers", follow_redirects=False)
        assert suppliers.status_code == 200
        assert b"Cross-Site Supplier Comparison" in suppliers.data
        strains = client.get("/cross-site/strains", follow_redirects=False)
        assert strains.status_code == 200
        assert b"Cross-Site Strain Comparison" in strains.data
        reconciliation = client.get("/cross-site/reconciliation", follow_redirects=False)
        assert reconciliation.status_code == 200
        assert b"Cross-Site Reconciliation" in reconciliation.data
    finally:
        with app.app_context():
            db.session.get(SystemSetting, "cross_site_ops_enabled").value = original
            db.session.commit()


def test_admin_can_create_and_revoke_api_client_from_settings():
    create = _call_view_as_user(
        "/settings/api_clients/create",
        "api_client_create",
        "admin",
        method="POST",
        data={
            "name": "settings test client",
            "notes": "created in test",
            "scopes": ["read:site", "read:lots"],
            "return_to": "#settings-api-clients",
        },
    )
    assert create.status_code in (302, 303)
    assert "#settings-api-clients" in create.headers["Location"]

    app = app_module.app
    with app.app_context():
        client = ApiClient.query.filter_by(name="settings test client").first()
        assert client is not None
        client_id = client.id
        assert client.is_active is True
        assert client.scopes == ["read:lots", "read:site"]

    revoke = _call_view_as_user(
        f"/settings/api_clients/{client_id}/toggle_active",
        "api_client_toggle_active",
        "admin",
        method="POST",
        data={"return_to": "#settings-api-clients"},
        client_id=client_id,
    )
    assert revoke.status_code in (302, 303)

    with app.app_context():
        client = db.session.get(ApiClient, client_id)
        assert client is not None
        assert client.is_active is False
        db.session.delete(client)
        db.session.commit()


def test_admin_can_create_and_pull_remote_site_from_settings():
    suffix = gen_uuid()[:8]
    create = _call_view_as_user(
        "/settings/remote_sites/create",
        "remote_site_create",
        "admin",
        method="POST",
        data={
            "name": f"Remote Site Alpha {suffix}",
            "base_url": f"https://alpha-{suffix}.example.com/",
            "api_token": "remote-secret",
            "notes": "created in test",
            "return_to": "#settings-remote-sites",
        },
    )
    assert create.status_code in (302, 303)
    assert "#settings-remote-sites" in create.headers["Location"]

    app = app_module.app
    with app.app_context():
        site = RemoteSite.query.filter_by(name=f"Remote Site Alpha {suffix}").first()
        assert site is not None
        site_id = site.id
        assert site.base_url == f"https://alpha-{suffix}.example.com"

    fake_pull = type("PullResult", (), {"status": "success", "error_message": None})()
    with patch("gold_drop.settings_module.pull_remote_site", return_value=fake_pull) as pull_mock:
        pull = _call_view_as_user(
            f"/settings/remote_sites/{site_id}/pull",
            "remote_site_pull",
            "admin",
            method="POST",
            data={"return_to": "#settings-remote-sites"},
            site_id=site_id,
        )
        assert pull.status_code in (302, 303)
        pull_mock.assert_called_once()

    with app.app_context():
        site = db.session.get(RemoteSite, site_id)
        assert site is not None
        site.is_active = False
        db.session.commit()
        db.session.delete(site)
        db.session.commit()


def test_admin_can_create_scale_device_and_test_capture_from_settings():
    create = _call_view_as_user(
        "/settings/scale_devices/create",
        "scale_device_create",
        "admin",
        method="POST",
        data={
            "name": "Settings Scale Device",
            "location": "Receiving",
            "make_model": "Demo",
            "interface_type": "rs232",
            "protocol_type": "ascii",
            "connection_target": "COM9",
            "notes": "created in test",
            "return_to": "#settings-scales",
        },
    )
    assert create.status_code in (302, 303)
    assert "#settings-scales" in create.headers["Location"]

    app = app_module.app
    with app.app_context():
        device = ScaleDevice.query.filter_by(name="Settings Scale Device").first()
        assert device is not None
        device_id = device.id

    capture = _call_view_as_user(
        f"/settings/scale_devices/{device_id}/test_capture",
        "scale_device_test_capture",
        "admin",
        method="POST",
        data={
            "capture_type": "adjustment",
            "raw_payload": "ST,GS, 98.4 lb",
            "notes": "settings test ingest",
            "return_to": "#settings-scales",
        },
        device_id=device_id,
    )
    assert capture.status_code in (302, 303)

    with app.app_context():
        saved_device = db.session.get(ScaleDevice, device_id)
        assert saved_device is not None
        weight_capture = WeightCapture.query.filter_by(device_id=device_id).order_by(WeightCapture.created_at.desc()).first()
        assert weight_capture is not None
        capture_id = weight_capture.id
        assert float(weight_capture.measured_weight or 0) == 98.4
        assert weight_capture.source_mode == "device"
        assert weight_capture.raw_payload == "ST,GS, 98.4 lb"
        db.session.delete(weight_capture)
        db.session.delete(saved_device)
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


def test_pull_remote_sites_route_redirects_cleanly():
    fake_pull = type("PullResult", (), {"status": "success", "error_message": None})()
    with patch("gold_drop.settings_module.pull_all_remote_sites", return_value=[fake_pull]):
        page = _call_view_as_user(
            "/settings/pull_remote_sites",
            "settings_pull_remote_sites",
            "admin",
            method="POST",
            data={"return_to": "#settings-maintenance"},
        )
    assert page.status_code in (302, 303)
    assert "#settings-maintenance" in page.headers["Location"]


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
            message_ts="1743200000.327470",
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
            assert b"Format: CODE39" in multi.data
            assert b"<svg" in multi.data
            assert b"api.qrserver.com" in multi.data

            scan = client.get(f"/scan/lot/{tracking_id}")
            assert scan.status_code == 200
            assert b"Scanned Lot" in scan.data
            assert tracking_id.encode() in scan.data
            assert b"Open Charge Form" in scan.data
            assert b"Print Label" in scan.data
            assert b"Trace Journey" in scan.data
            assert b"Recent Scan Activity" in scan.data

            with app.app_context():
                events = LotScanEvent.query.filter_by(lot_id=lot_id).order_by(LotScanEvent.created_at.asc()).all()
                assert len(events) == 1
                assert events[0].action == "scan_open"
    finally:
        with app.app_context():
            LotScanEvent.query.filter_by(lot_id=lot_id).delete()
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


def test_scanned_lot_can_open_charge_form():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Scan Flow Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=80,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"SCAN-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Scan Dream",
            weight_lbs=80,
            remaining_weight_lbs=80,
        )
        db.session.add(lot)
        db.session.commit()
        tracking_id = lot.tracking_id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(f"/scan/lot/{tracking_id}/start-run", follow_redirects=False)
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].endswith(f"/scan/lot/{tracking_id}/charge?run_start_mode=blank&scale_device_id=")

            charge_form = client.get(resp.headers["Location"])
            assert charge_form.status_code == 200
            assert b"Start Extraction Charge" in charge_form.data
            assert tracking_id.encode() in charge_form.data

            with app.app_context():
                actions = [
                    event.action
                    for event in LotScanEvent.query.filter_by(lot_id=lot_id).order_by(LotScanEvent.created_at.asc()).all()
                ]
                assert actions == ["start_run"]
    finally:
        with app.app_context():
            LotScanEvent.query.filter_by(lot_id=lot_id).delete()
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


def test_scanned_lot_guided_run_start_supports_partial_and_full_modes():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Scan Guided Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=125,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"SCANG-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Guided Dream",
            weight_lbs=125,
            remaining_weight_lbs=100,
        )
        db.session.add(lot)
        db.session.commit()
        tracking_id = lot.tracking_id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")

            partial = client.post(
                f"/scan/lot/{tracking_id}/start-run",
                data={"run_start_mode": "partial", "requested_weight_lbs": "42.5"},
                follow_redirects=False,
            )
            assert partial.status_code in (302, 303)
            assert "/scan/lot/" in partial.headers["Location"]
            charge_form = client.get(partial.headers["Location"])
            assert charge_form.status_code == 200
            assert b'value="42.5"' in charge_form.data

            full = client.post(
                f"/scan/lot/{tracking_id}/start-run",
                data={"run_start_mode": "full_remaining"},
                follow_redirects=False,
            )
            assert full.status_code in (302, 303)
            charge_form = client.get(full.headers["Location"])
            assert charge_form.status_code == 200
            assert b'value="100.0"' in charge_form.data
    finally:
        with app.app_context():
            LotScanEvent.query.filter_by(lot_id=lot_id).delete()
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


def test_scan_charge_creates_extraction_charge_and_prefills_run():
    app = app_module.app
    charge_id = None
    with app.app_context():
        supplier = Supplier(name="Charge Scan Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 14),
            delivery_date=date(2026, 4, 14),
            status="delivered",
            stated_weight_lbs=90,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"CHARGE-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Charge Dream",
            weight_lbs=90,
            remaining_weight_lbs=90,
            milled=True,
            floor_state="reactor_staging",
        )
        db.session.add(lot)
        db.session.commit()
        tracking_id = lot.tracking_id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                f"/scan/lot/{tracking_id}/charge",
                data={
                    "charged_weight_lbs": "42.5",
                    "reactor_number": "2",
                    "charged_at": "2026-04-14T10:15",
                    "notes": "scanner charge",
                },
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].startswith("/runs/new")

            with client.session_transaction() as sess:
                prefill = sess.get(app_module.SCAN_RUN_PREFILL_SESSION_KEY)
                assert prefill is not None
                charge_id = prefill["charge_id"]
                assert prefill["tracking_id"] == tracking_id
                assert prefill["planned_weight_lbs"] == 42.5
                assert prefill["reactor_number"] == 2

            run_new = client.get(resp.headers["Location"])
            assert run_new.status_code == 200
            assert b"Extraction charge recorded:" in run_new.data
            assert b"42.5 lbs into Reactor 2" in run_new.data

            with app.app_context():
                charge = db.session.get(ExtractionCharge, charge_id)
                assert charge is not None
                assert charge.purchase_lot_id == lot_id
                assert charge.status == "pending"
                events = LotScanEvent.query.filter_by(lot_id=lot_id).order_by(LotScanEvent.created_at.asc()).all()
                assert events[-1].action == "extraction_charge"
    finally:
        with app.app_context():
            if charge_id:
                ExtractionCharge.query.filter_by(id=charge_id).delete(synchronize_session=False)
            LotScanEvent.query.filter_by(lot_id=lot_id).delete()
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


def test_main_app_lot_charge_links_charge_to_saved_run():
    app = app_module.app
    charge_id = None
    run_id = None
    with app.app_context():
        supplier = Supplier(name="Charge Link Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 14),
            delivery_date=date(2026, 4, 14),
            status="delivered",
            stated_weight_lbs=70,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="pending",
            batch_id=f"CHGLNK-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Link Dream",
            weight_lbs=70,
            remaining_weight_lbs=70,
        )
        db.session.add(lot)
        db.session.commit()
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            charge_resp = client.post(
                f"/lots/{lot_id}/charge",
                data={
                    "charged_weight_lbs": "25",
                    "reactor_number": "1",
                    "charged_at": "2026-04-14T12:00",
                    "notes": "desktop charge",
                },
                follow_redirects=False,
            )
            assert charge_resp.status_code in (302, 303)
            assert charge_resp.headers["Location"].startswith("/runs/new")
            with client.session_transaction() as sess:
                prefill = sess.get(app_module.SCAN_RUN_PREFILL_SESSION_KEY)
                charge_id = prefill["charge_id"]

            save = client.post(
                "/runs/new",
                data={
                    "run_date": "2026-04-14",
                    "reactor_number": "1",
                    "run_type": "standard",
                    "bio_in_reactor_lbs": "25",
                    "dry_hte_g": "5",
                    "dry_thca_g": "15",
                    "lot_ids[]": [lot_id],
                    "lot_weights[]": ["25"],
                },
                follow_redirects=False,
            )
            assert save.status_code in (302, 303)
            assert save.headers["Location"].endswith("/runs")

            with app.app_context():
                charge = db.session.get(ExtractionCharge, charge_id)
                assert charge is not None
                assert charge.run_id is not None
                assert charge.status == "applied"
                run_id = charge.run_id
                run_input = app_module.RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
                assert run_input is not None
                assert float(run_input.weight_lbs or 0) == 25.0
    finally:
        with app.app_context():
            if charge_id:
                ExtractionCharge.query.filter_by(id=charge_id).delete(synchronize_session=False)
            if run_id:
                run_input = app_module.RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
                if run_input:
                    db.session.delete(run_input)
                run_obj = db.session.get(app_module.Run, run_id)
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


def test_scanned_lot_can_confirm_movement_and_testing():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Scan Update Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=60,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="pending",
            batch_id=f"SCNUP-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Scanner Kush",
            weight_lbs=60,
            remaining_weight_lbs=60,
            location="Staging",
        )
        db.session.add(lot)
        db.session.commit()
        tracking_id = lot.tracking_id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            movement = client.post(
                f"/scan/lot/{tracking_id}/confirm-movement",
                data={"movement_code": "vault", "location": "Vault A / Shelf 2"},
                follow_redirects=False,
            )
            assert movement.status_code in (302, 303)
            assert movement.headers["Location"].endswith(f"/scan/lot/{tracking_id}")

            testing = client.post(
                f"/scan/lot/{tracking_id}/confirm-testing",
                data={"testing_status": "completed"},
                follow_redirects=False,
            )
            assert testing.status_code in (302, 303)
            assert movement.headers["Location"].endswith(f"/scan/lot/{tracking_id}")

            milled = client.post(
                f"/scan/lot/{tracking_id}/confirm-milled",
                data={"milled_state": "milled"},
                follow_redirects=False,
            )
            assert milled.status_code in (302, 303)

            with app.app_context():
                lot = db.session.get(PurchaseLot, lot_id)
                purchase = db.session.get(Purchase, purchase_id)
                assert lot is not None
                assert purchase is not None
                assert lot.location == "Vault A / Shelf 2"
                assert lot.floor_state == "vault"
                assert lot.milled is True
                assert purchase.testing_status == "completed"
                assert purchase.testing_date == app_module.date.today()
                events = LotScanEvent.query.filter_by(lot_id=lot_id).order_by(LotScanEvent.created_at.asc()).all()
                actions = [event.action for event in events]
                assert actions == ["confirm_movement", "confirm_testing", "confirm_milled"]
                movement_context = events[0].context or {}
                assert movement_context["movement_code"] == "vault"
                assert movement_context["movement_label"] == "Move to vault"
                assert movement_context["floor_state"] == "vault"
                milled_context = events[2].context or {}
                assert milled_context["milled"] is True
    finally:
        with app.app_context():
            LotScanEvent.query.filter_by(lot_id=lot_id).delete()
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


def test_floor_ops_page_shows_recent_scans_and_scale_captures():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Floor Ops Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=55,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"FLOOR-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Floor Dream",
            weight_lbs=55,
            remaining_weight_lbs=40,
            floor_state="reactor_staging",
            milled=True,
        )
        db.session.add(lot)
        db.session.flush()
        event = LotScanEvent(lot_id=lot.id, tracking_id_snapshot=lot.tracking_id, action="scan_open")
        db.session.add(event)
        device = ScaleDevice(name="Floor Scale", interface_type="usb", protocol_type="generic_ascii", location="Reactor A")
        db.session.add(device)
        db.session.flush()
        capture = WeightCapture(
            device_id=device.id,
            capture_type="reactor_input",
            source_mode="device",
            measured_weight=101.5,
            unit="lbs",
            raw_payload="WT,101.5,lb",
        )
        db.session.add(capture)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        event_id = event.id
        device_id = device.id
        capture_id = capture.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/floor-ops")
            assert resp.status_code == 200
            assert b"Floor Ops" in resp.data
            assert b"Recent Scan Activity" in resp.data
            assert b"Recent Scale Captures" in resp.data
            assert b"Ready For Extraction" in resp.data
            assert b"Reactor staging" in resp.data
            assert b"lbs staged, milled, and test-ready" in resp.data
            assert b"Open Scan Page" in resp.data
            assert b"Floor Scale" in resp.data
    finally:
        with app.app_context():
            capture_obj = db.session.get(WeightCapture, capture_id)
            if capture_obj:
                db.session.delete(capture_obj)
            device_obj = db.session.get(ScaleDevice, device_id)
            if device_obj:
                db.session.delete(device_obj)
            event_obj = db.session.get(LotScanEvent, event_id)
            if event_obj:
                db.session.delete(event_obj)
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


def test_scan_center_page_renders_for_authenticated_user():
    app = app_module.app
    with app.test_client() as client:
        _login(client, "admin")
        resp = client.get("/scan")
        assert resp.status_code == 200
        assert b"Scan Center" in resp.data
        assert b"Start Camera Scan" in resp.data
        assert b"tracking_id" in resp.data
        assert b"Recent Floor Scans" in resp.data or b"Bluetooth scanner" in resp.data


def test_run_form_scale_capture_prefills_reactor_weight_and_links_capture():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Run Scale Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 12),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=100,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"RUNSC-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Run Scale Strain",
            weight_lbs=100,
            remaining_weight_lbs=100,
        )
        device = ScaleDevice(
            name="Run Scale Device",
            location="Lab",
            interface_type="rs232",
            protocol_type="ascii",
            connection_target="COM5",
            is_active=True,
        )
        db.session.add(lot)
        db.session.add(device)
        db.session.commit()
        supplier_id = supplier.id
        purchase_id = purchase.id
        lot_id = lot.id
        device_id = device.id

    run_id = None
    capture_id = None
    try:
        with app.test_client() as client:
            _login(client, "admin")
            capture = client.post(
                "/runs/scale-capture",
                data={
                    "scale_device_id": device_id,
                    "scale_raw_payload": "ST,GS, 44.2 lb",
                    "scale_notes": "run form capture",
                },
                follow_redirects=False,
            )
            assert capture.status_code in (302, 303)
            assert capture.headers["Location"].endswith("/runs/new")

            with client.session_transaction() as sess:
                prefill = sess.get(app_module.RUN_SCALE_PREFILL_SESSION_KEY)
                assert prefill is not None
                assert float(prefill["measured_weight"]) == 44.2
                capture_id = prefill["capture_id"]

            run_new = client.get("/runs/new")
            assert run_new.status_code == 200
            assert b"Scale prefill:" in run_new.data
            assert b"44.20" in run_new.data

            save = client.post(
                "/runs/new",
                data={
                    "run_date": "2026-04-14",
                    "reactor_number": "1",
                    "run_type": "standard",
                    "bio_in_reactor_lbs": "44.2",
                    "dry_hte_g": "10",
                    "dry_thca_g": "20",
                    "lot_ids[]": [lot_id],
                    "lot_weights[]": ["44.2"],
                    "scale_capture_id": capture_id,
                },
                follow_redirects=False,
            )
            assert save.status_code in (302, 303)
            assert save.headers["Location"].endswith("/runs")

            with app.app_context():
                capture_obj = db.session.get(WeightCapture, capture_id)
                assert capture_obj is not None
                assert capture_obj.run_id is not None
                run_id = capture_obj.run_id
                run = db.session.get(app_module.Run, run_id)
                assert run is not None
                assert float(run.bio_in_reactor_lbs or 0) == 44.2
    finally:
        with app.app_context():
            if run_id:
                run_input = app_module.RunInput.query.filter_by(run_id=run_id, lot_id=lot_id).first()
                if run_input:
                    db.session.delete(run_input)
                run_obj = db.session.get(app_module.Run, run_id)
                if run_obj:
                    db.session.delete(run_obj)
            if capture_id:
                capture_obj = db.session.get(WeightCapture, capture_id)
                if capture_obj:
                    db.session.delete(capture_obj)
            lot_obj = db.session.get(PurchaseLot, lot_id)
            if lot_obj:
                db.session.delete(lot_obj)
            purchase_obj = db.session.get(Purchase, purchase_id)
            if purchase_obj:
                db.session.delete(purchase_obj)
            supplier_obj = db.session.get(Supplier, supplier_id)
            if supplier_obj:
                db.session.delete(supplier_obj)
            device_obj = db.session.get(ScaleDevice, device_id)
            if device_obj:
                db.session.delete(device_obj)
            db.session.commit()


def test_floor_ops_page_shows_pending_and_applied_extraction_charges():
    app = app_module.app
    pending_charge_id = None
    applied_charge_id = None
    third_charge_id = None
    run_id = None
    third_run_id = None
    with app.app_context():
        admin_id = app_module.User.query.filter_by(username="admin").first().id
        supplier = Supplier(name="Floor Charge Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 16),
            delivery_date=date(2026, 4, 16),
            status="delivered",
            stated_weight_lbs=120,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"FCHG-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        pending_lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Pending Dream",
            weight_lbs=60,
            remaining_weight_lbs=60,
            floor_state="reactor_staging",
            milled=True,
        )
        applied_lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Applied Dream",
            weight_lbs=60,
            remaining_weight_lbs=35,
            floor_state="reactor_staging",
            milled=True,
        )
        third_lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Third Dream",
            weight_lbs=40,
            remaining_weight_lbs=22,
            floor_state="reactor_staging",
            milled=True,
        )
        db.session.add_all([pending_lot, applied_lot, third_lot])
        db.session.flush()
        run = app_module.Run(
            run_date=date(2026, 4, 16),
            reactor_number=2,
            run_type="standard",
            bio_in_reactor_lbs=25,
            dry_hte_g=5,
            dry_thca_g=10,
            created_by=admin_id,
        )
        db.session.add(run)
        db.session.flush()
        db.session.add(app_module.RunInput(run_id=run.id, lot_id=applied_lot.id, weight_lbs=25))
        third_run = app_module.Run(
            run_date=date(2026, 4, 16),
            reactor_number=3,
            run_type="standard",
            bio_in_reactor_lbs=18,
            dry_hte_g=4,
            dry_thca_g=7,
            created_by=admin_id,
        )
        db.session.add(third_run)
        db.session.flush()
        db.session.add(app_module.RunInput(run_id=third_run.id, lot_id=third_lot.id, weight_lbs=18))
        pending_charge = ExtractionCharge(
            purchase_lot_id=pending_lot.id,
            charged_weight_lbs=30,
            reactor_number=1,
            charged_at=app_module.datetime.now(app_module.timezone.utc),
            source_mode="main_app",
            status="pending",
            notes="awaiting run save",
            created_by=admin_id,
        )
        applied_charge = ExtractionCharge(
            purchase_lot_id=applied_lot.id,
            run_id=run.id,
            charged_weight_lbs=25,
            reactor_number=2,
            charged_at=app_module.datetime.now(app_module.timezone.utc),
            source_mode="scan",
            status="applied",
            created_by=admin_id,
        )
        third_charge = ExtractionCharge(
            purchase_lot_id=third_lot.id,
            run_id=third_run.id,
            charged_weight_lbs=18,
            reactor_number=3,
            charged_at=app_module.datetime.now(app_module.timezone.utc),
            source_mode="scan",
            status="applied",
            created_by=admin_id,
        )
        db.session.add_all([pending_charge, applied_charge, third_charge])
        db.session.commit()
        pending_charge_id = pending_charge.id
        applied_charge_id = applied_charge.id
        third_charge_id = third_charge.id
        run_id = run.id
        third_run_id = third_run.id
        purchase_id = purchase.id
        pending_lot_id = pending_lot.id
        applied_lot_id = applied_lot.id
        third_lot_id = third_lot.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/floor-ops")
            assert resp.status_code == 200
            assert b"Active Reactor Board" in resp.data
            assert b"Board view" in resp.data
            assert b"Reactor History Today" in resp.data
            assert b"Charged / waiting" in resp.data
            assert b"Run linked" in resp.data
            assert b"Queue depth:" in resp.data
            assert b"operator:" in resp.data
            assert b"Mark In Reactor" in resp.data
            assert b"Mark Running" in resp.data
            assert b"Reactor Charge Queue" in resp.data
            assert b"Pending Charges" in resp.data
            assert b"Pending Dream" in resp.data
            assert b"Applied Dream" in resp.data
            assert b"Third Dream" in resp.data
            assert b"Reactor 3" in resp.data
            assert b"awaiting run save" in resp.data
            assert b"Charge recorded (Run linked)" in resp.data or b"Charge recorded (Charged / waiting)" in resp.data
            assert b"Recently Applied Charges" in resp.data
            assert b"Open Run" in resp.data
            assert b"return_to=/floor-ops" in resp.data or b"return_to=%2Ffloor-ops" in resp.data
    finally:
        with app.app_context():
            if pending_charge_id:
                obj = db.session.get(ExtractionCharge, pending_charge_id)
                if obj:
                    db.session.delete(obj)
            if applied_charge_id:
                obj = db.session.get(ExtractionCharge, applied_charge_id)
                if obj:
                    db.session.delete(obj)
            if third_charge_id:
                obj = db.session.get(ExtractionCharge, third_charge_id)
                if obj:
                    db.session.delete(obj)
            if run_id:
                run_input = app_module.RunInput.query.filter_by(run_id=run_id, lot_id=applied_lot_id).first()
                if run_input:
                    db.session.delete(run_input)
                run_obj = db.session.get(app_module.Run, run_id)
                if run_obj:
                    db.session.delete(run_obj)
            if third_run_id:
                run_input = app_module.RunInput.query.filter_by(run_id=third_run_id, lot_id=third_lot_id).first()
                if run_input:
                    db.session.delete(run_input)
                run_obj = db.session.get(app_module.Run, third_run_id)
                if run_obj:
                    db.session.delete(run_obj)
            for lot_id in (pending_lot_id, applied_lot_id, third_lot_id):
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


def test_run_edit_honors_floor_ops_return_context():
    app = app_module.app
    run_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            run = app_module.Run(
                run_date=date(2026, 4, 16),
                reactor_number=2,
                run_type="standard",
                bio_in_reactor_lbs=20,
                created_by=admin_id,
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id

        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get(f"/runs/{run_id}/edit?return_to=/floor-ops")
            assert resp.status_code == 200
            assert b"Back to Floor Ops" in resp.data
            assert b"Open Runs" in resp.data
            assert b'name="return_to" value="/floor-ops"' in resp.data
    finally:
        with app.app_context():
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
                db.session.commit()


def test_run_edit_shows_booth_review_surface():
    app = app_module.app
    run_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            run = app_module.Run(
                run_date=date(2026, 4, 16),
                reactor_number=2,
                run_type="standard",
                bio_in_reactor_lbs=20,
                created_by=admin_id,
                run_fill_started_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=40),
                run_fill_ended_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=5),
                mixer_started_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=20),
                mixer_ended_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=10),
                flush_started_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=15),
                flush_ended_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=4),
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id

            session = app_module.ExtractionBoothSession(
                run_id=run.id,
                current_stage_key="clarity_adjustment_required",
                status="in_progress",
                flow_resumed_decision="no_adjusting",
                flow_resumed_confirmed_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=12),
                final_clarity_decision="not_yet",
                final_clarity_confirmed_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=3),
                final_purge_started_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=8),
                final_purge_completed_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=3),
            )
            db.session.add(session)
            db.session.flush()
            db.session.add(app_module.ExtractionBoothEvent(
                session_id=session.id,
                run_id=run.id,
                event_key="final_purge_resumed",
                event_label="Final purge resumed for additional clarity work",
                occurred_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=4),
                recorded_by_user_id=admin_id,
            ))
            db.session.add(app_module.ExtractionBoothEvidence(
                session_id=session.id,
                run_id=run.id,
                evidence_type="plate_temp_photo",
                file_path="uploads/mobile/test-plate-photo.jpg",
                captured_at=app_module.datetime.now(app_module.timezone.utc) - timedelta(minutes=6),
                captured_by_user_id=admin_id,
            ))
            db.session.add(app_module.SupervisorNotification(
                run_id=run.id,
                booth_session_id=session.id,
                event_key="flow_adjustment_required",
                dedupe_key="flow_adjustment_required",
                notification_class="warnings",
                severity="critical",
                title="Flow adjustment required",
                message="Recovery flow did not resume after flush adjustments.",
            ))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get(f"/runs/{run_id}/edit")
            assert resp.status_code == 200
            assert b"Booth Review" in resp.data
            assert b"Deviation Flags" in resp.data
            assert b"Flow is still being adjusted." in resp.data
            assert b"Final clarity is not yet acceptable." in resp.data
            assert b"Recent Booth History" in resp.data
            assert b"Booth Evidence" in resp.data
            assert b"Supervisor Notifications" in resp.data
            assert b"Flow adjustment required" in resp.data
            assert b"Final purge resumed for additional clarity work" in resp.data
            assert b"Open evidence" in resp.data
    finally:
        with app.app_context():
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
                db.session.commit()


def test_dashboard_shows_and_approves_supervisor_notifications():
    app = app_module.app
    run_id = None
    notification_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            run = app_module.Run(
                run_date=date(2026, 4, 24),
                reactor_number=1,
                run_type="standard",
                bio_in_reactor_lbs=22,
                created_by=admin_id,
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            notification = app_module.SupervisorNotification(
                run_id=run.id,
                event_key="timing_short_flush",
                dedupe_key="timing_short_flush",
                notification_class="warnings",
                severity="warning",
                title="Flush soak finished short of target",
                message="Flush soak recorded 4 minute(s) against a 10-minute target.",
            )
            db.session.add(notification)
            db.session.commit()
            notification_id = notification.id

        with app.test_client() as client:
            _login(client, "admin")
            dashboard = client.get("/")
            assert dashboard.status_code == 200
            assert b"Supervisor Notifications" in dashboard.data
            assert b"Flush soak finished short of target" in dashboard.data
            assert b"Approve Deviation" in dashboard.data
            assert b"Require Rework" in dashboard.data

            approve = client.post(
                f"/supervisor-notifications/{notification_id}/approve",
                data={
                    "return_to": "/#supervisor-notifications",
                    "override_reason": "Supervisor approved the short flush after review of booth conditions.",
                },
                follow_redirects=False,
            )
            assert approve.status_code in (302, 303)

        with app.app_context():
            row = db.session.get(app_module.SupervisorNotification, notification_id)
            assert row is not None
            assert row.status == "resolved"
            assert row.override_decision == "approved_deviation"
            assert row.override_by_user_id == admin_id
            assert row.override_reason == "Supervisor approved the short flush after review of booth conditions."
    finally:
        with app.app_context():
            row = db.session.get(app_module.SupervisorNotification, notification_id) if notification_id else None
            if row:
                db.session.delete(row)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            db.session.commit()


def test_floor_ops_board_view_filter_shows_only_running_reactors():
    app = app_module.app
    charge_id = None
    run_id = None
    purchase_id = None
    lot_id = None
    supplier_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Running Filter Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 19),
                delivery_date=date(2026, 4, 19),
                status="delivered",
                stated_weight_lbs=45,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"RUNFLT-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Running Dream",
                weight_lbs=45,
                remaining_weight_lbs=45,
                floor_state="reactor_staging",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 19),
                reactor_number=4,
                run_type="standard",
                bio_in_reactor_lbs=20,
                created_by=admin_id,
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            charge = ExtractionCharge(
                purchase_lot_id=lot.id,
                run_id=run.id,
                charged_weight_lbs=20,
                reactor_number=4,
                charged_at=app_module.datetime.now(app_module.timezone.utc),
                source_mode="main_app",
                status="running",
                created_by=admin_id,
            )
            db.session.add(charge)
            db.session.flush()
            charge_id = charge.id
            db.session.add(
                AuditLog(
                    user_id=admin_id,
                    action="state_change",
                    entity_type="extraction_charge",
                    entity_id=charge.id,
                    details=app_module.json.dumps({"to_state": "running"}),
                )
            )
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/floor-ops?board_view=running")
            assert resp.status_code == 200
            assert b"No reactors match the current board filter." not in resp.data
            assert b"Reactor 4" in resp.data
            assert b"Running Dream" in resp.data
            assert b"Charge recorded (Running)" in resp.data
    finally:
        with app.app_context():
            AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id).delete(synchronize_session=False)
            if charge_id:
                ExtractionCharge.query.filter_by(id=charge_id).delete(synchronize_session=False)
            if run_id:
                run = db.session.get(app_module.Run, run_id)
                if run:
                    db.session.delete(run)
            if lot_id:
                lot = db.session.get(PurchaseLot, lot_id)
                if lot:
                    db.session.delete(lot)
            if purchase_id:
                purchase = db.session.get(Purchase, purchase_id)
                if purchase:
                    db.session.delete(purchase)
            if supplier_id:
                supplier = db.session.get(Supplier, supplier_id)
                if supplier:
                    db.session.delete(supplier)
            db.session.commit()


def test_settings_route_saves_reactor_lifecycle_controls():
    app = app_module.app
    keys = [
        "reactor_state_in_reactor_enabled",
        "reactor_state_in_reactor_required",
        "reactor_state_running_enabled",
        "reactor_state_running_required",
        "reactor_state_completed_enabled",
        "reactor_state_completed_required",
        "reactor_state_cancelled_enabled",
        "reactor_state_cancelled_required",
        "reactor_running_requires_linked_run",
        "reactor_show_state_history",
    ]
    with app.app_context():
        originals = {key: SystemSetting.get(key) for key in keys}

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                "/settings",
                data={
                    "form_type": "system",
                    "return_to": "#settings-system",
                    "reactor_state_in_reactor_enabled": "on",
                    "reactor_state_in_reactor_required": "on",
                    "reactor_state_running_enabled": "on",
                    "reactor_state_completed_enabled": "on",
                    "reactor_state_cancelled_enabled": "on",
                    "reactor_running_requires_linked_run": "on",
                },
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)

        with app.app_context():
            assert SystemSetting.get("reactor_state_in_reactor_enabled") == "1"
            assert SystemSetting.get("reactor_state_in_reactor_required") == "1"
            assert SystemSetting.get("reactor_state_running_enabled") == "1"
            assert SystemSetting.get("reactor_state_running_required") == "0"
            assert SystemSetting.get("reactor_show_state_history") == "0"
            assert SystemSetting.get("reactor_running_requires_linked_run") == "1"
    finally:
        with app.app_context():
            for key, value in originals.items():
                row = db.session.get(SystemSetting, key)
                if value is None:
                    if row is not None:
                        db.session.delete(row)
                else:
                    if row is None:
                        db.session.add(SystemSetting(key=key, value=value))
                    else:
                        row.value = value
            db.session.commit()


def test_floor_charge_transitions_require_states_and_record_history():
    app = app_module.app
    keys = [
        "reactor_state_in_reactor_enabled",
        "reactor_state_in_reactor_required",
        "reactor_state_running_enabled",
        "reactor_state_running_required",
        "reactor_state_completed_enabled",
        "reactor_running_requires_linked_run",
    ]
    with app.app_context():
        originals = {key: SystemSetting.get(key) for key in keys}
        for key, value in (
            ("reactor_state_in_reactor_enabled", "1"),
            ("reactor_state_in_reactor_required", "1"),
            ("reactor_state_running_enabled", "1"),
            ("reactor_state_running_required", "1"),
            ("reactor_state_completed_enabled", "1"),
            ("reactor_running_requires_linked_run", "1"),
        ):
            row = db.session.get(SystemSetting, key)
            if row is None:
                db.session.add(SystemSetting(key=key, value=value))
            else:
                row.value = value
        supplier = Supplier(name="Floor Transition Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 19),
            delivery_date=date(2026, 4, 19),
            status="delivered",
            stated_weight_lbs=80,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            testing_status="completed",
            clean_or_dirty="clean",
            batch_id=f"TRN-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Transition Dream",
            weight_lbs=80,
            remaining_weight_lbs=80,
            floor_state="reactor_staging",
            milled=True,
        )
        db.session.add(lot)
        db.session.flush()
        charge = ExtractionCharge(
            purchase_lot_id=lot.id,
            charged_weight_lbs=30,
            reactor_number=1,
            charged_at=app_module.datetime.now(app_module.timezone.utc),
            source_mode="main_app",
            status="pending",
            created_by=app_module.User.query.filter_by(username="admin").first().id,
        )
        db.session.add(charge)
        db.session.commit()
        charge_id = charge.id
        purchase_id = purchase.id
        lot_id = lot.id
        supplier_id = supplier.id

    run_id = None
    try:
        with app.test_client() as client:
            _login(client, "admin")
            blocked = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "completed"},
                follow_redirects=True,
            )
            assert blocked.status_code == 200
            assert b"Mark In Reactor is required before this transition." in blocked.data

            moved = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "in_reactor"},
                follow_redirects=True,
            )
            assert moved.status_code == 200
            assert b"Reactor state updated to In reactor." in moved.data

            blocked_running = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "running"},
                follow_redirects=True,
            )
            assert blocked_running.status_code == 200
            assert b"Mark Running requires a linked run" in blocked_running.data

        with app.app_context():
            run = app_module.Run(
                run_date=date(2026, 4, 19),
                reactor_number=1,
                run_type="standard",
                bio_in_reactor_lbs=30,
                created_by=app_module.User.query.filter_by(username="admin").first().id,
            )
            db.session.add(run)
            db.session.flush()
            charge = db.session.get(ExtractionCharge, charge_id)
            charge.run_id = run.id
            run_id = run.id
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            running = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "running"},
                follow_redirects=True,
            )
            assert running.status_code == 200
            assert b"Reactor state updated to Running." in running.data

            completed = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "completed"},
                follow_redirects=True,
            )
            assert completed.status_code == 200
            assert b"Reactor state updated to Completed today." in completed.data

        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id)
            assert charge is not None
            assert charge.status == "completed"
            history = AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id, action="state_change").order_by(AuditLog.timestamp.asc()).all()
            states = [json.loads(item.details or "{}").get("to_state") for item in history]
            assert states == ["in_reactor", "running", "completed"]
    finally:
        with app.app_context():
            for item in AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id).all():
                db.session.delete(item)
            charge = db.session.get(ExtractionCharge, charge_id)
            if charge is not None:
                db.session.delete(charge)
            if run_id:
                run = db.session.get(app_module.Run, run_id)
                if run is not None:
                    db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            for key, value in originals.items():
                row = db.session.get(SystemSetting, key)
                if value is None:
                    if row is not None:
                        db.session.delete(row)
                else:
                    if row is None:
                        db.session.add(SystemSetting(key=key, value=value))
                    else:
                        row.value = value
            db.session.commit()


def test_floor_charge_cancel_modify_redirects_to_run_and_logs_resolution():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Floor Cancel Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 19),
            delivery_date=date(2026, 4, 19),
            status="delivered",
            stated_weight_lbs=70,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            batch_id=f"CAN-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Cancel Dream",
            weight_lbs=70,
            remaining_weight_lbs=40,
            floor_state="reactor_staging",
            milled=True,
        )
        db.session.add(lot)
        db.session.flush()
        run = app_module.Run(
            run_date=date(2026, 4, 19),
            reactor_number=2,
            run_type="standard",
            bio_in_reactor_lbs=20,
            created_by=app_module.User.query.filter_by(username="admin").first().id,
        )
        db.session.add(run)
        db.session.flush()
        charge = ExtractionCharge(
            purchase_lot_id=lot.id,
            run_id=run.id,
            charged_weight_lbs=20,
            reactor_number=2,
            charged_at=app_module.datetime.now(app_module.timezone.utc),
            source_mode="main_app",
            status="applied",
            created_by=app_module.User.query.filter_by(username="admin").first().id,
        )
        db.session.add(charge)
        db.session.commit()
        charge_id = charge.id
        run_id = run.id
        purchase_id = purchase.id
        lot_id = lot.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                f"/floor-ops/charges/{charge_id}/transition",
                data={"target_state": "cancelled", "cancel_resolution": "modify"},
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].endswith(f"/runs/{run_id}/edit")

        with app.app_context():
            charge = db.session.get(ExtractionCharge, charge_id)
            assert charge is not None
            assert charge.status == "cancelled"
            audit = AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id, action="state_change").order_by(AuditLog.timestamp.desc()).first()
            assert audit is not None
            assert json.loads(audit.details or "{}").get("cancel_resolution") == "modify"
    finally:
        with app.app_context():
            for item in AuditLog.query.filter_by(entity_type="extraction_charge", entity_id=charge_id).all():
                db.session.delete(item)
            charge = db.session.get(ExtractionCharge, charge_id)
            if charge is not None:
                db.session.delete(charge)
            run = db.session.get(app_module.Run, run_id)
            if run is not None:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            db.session.commit()


def test_inventory_on_hand_rows_expose_edit_and_charge_actions():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Inventory Link Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 18),
            delivery_date=date(2026, 4, 18),
            status="delivered",
            stated_weight_lbs=50,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"INV-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Inventory Dream",
            weight_lbs=50,
            remaining_weight_lbs=50,
        )
        db.session.add(lot)
        db.session.commit()
        purchase_id = purchase.id
        lot_id = lot.id
        tracking_id = lot.tracking_id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/inventory")
            assert resp.status_code == 200
            assert f"/lots/{lot_id}/edit".encode() in resp.data
            assert f'/lots/{lot_id}/charge'.encode() in resp.data
            assert f'/scan/lot/{tracking_id}'.encode() in resp.data
            assert b">Edit<" in resp.data
            assert b">Charge<" in resp.data
            assert b">Scan<" in resp.data
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


def test_downstream_queues_page_groups_runs_by_destination():
    app = app_module.app
    run_ids = []
    purchase_id = None
    supplier_id = None
    lot_ids = []
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Downstream Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 22),
                delivery_date=date(2026, 4, 22),
                status="delivered",
                stated_weight_lbs=180,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"DQ-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lots = []
            for idx, strain in enumerate(("Queue Dream", "Hold Dream", "Unrouted Dream"), start=1):
                lot = PurchaseLot(
                    purchase_id=purchase.id,
                    strain_name=strain,
                    tracking_id=f"DQLOT-{idx}",
                    weight_lbs=60,
                    remaining_weight_lbs=20,
                    floor_state="inventory",
                    milled=True,
                )
                lots.append(lot)
            db.session.add_all(lots)
            db.session.flush()
            lot_ids = [lot.id for lot in lots]

            queue_run = app_module.Run(
                run_date=date(2026, 4, 22),
                reactor_number=1,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=1200,
                wet_thca_g=3000,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="golddrop_queue",
                thca_destination="make_ld",
            )
            hold_run = app_module.Run(
                run_date=date(2026, 4, 22),
                reactor_number=2,
                run_type="standard",
                bio_in_reactor_lbs=35,
                wet_hte_g=900,
                wet_thca_g=2600,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_potency_disposition="hold_distillate",
            )
            unrouted_run = app_module.Run(
                run_date=date(2026, 4, 22),
                reactor_number=3,
                run_type="standard",
                bio_in_reactor_lbs=38,
                wet_hte_g=1000,
                wet_thca_g=2800,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
            )
            db.session.add_all([queue_run, hold_run, unrouted_run])
            db.session.flush()
            run_ids = [queue_run.id, hold_run.id, unrouted_run.id]
            db.session.add_all(
                [
                    app_module.RunInput(run_id=queue_run.id, lot_id=lots[0].id, weight_lbs=40),
                    app_module.RunInput(run_id=hold_run.id, lot_id=lots[1].id, weight_lbs=35),
                    app_module.RunInput(run_id=unrouted_run.id, lot_id=lots[2].id, weight_lbs=38),
                ]
            )
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/downstream-queues")
            assert resp.status_code == 200
            assert b"Downstream Queues" in resp.data
            assert b"Queue Snapshot" in resp.data
            assert b"Needs Queue Decision" in resp.data
            assert b"GoldDrop Production Queue" in resp.data
            assert b"Distillate Hold" in resp.data
            assert b"Queue Dream" in resp.data
            assert b"Hold Dream" in resp.data
            assert b"Unrouted Dream" in resp.data
            assert b"Move to GoldDrop production queue" in resp.data
            assert b"Mark downstream queue complete" in resp.data
            assert b"return_to=/downstream-queues" in resp.data or b"return_to=%2Fdownstream-queues" in resp.data
    finally:
        with app.app_context():
            for run_id in run_ids:
                app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
                run = db.session.get(app_module.Run, run_id)
                if run:
                    db.session.delete(run)
            for lot_id in lot_ids:
                lot = db.session.get(PurchaseLot, lot_id)
                if lot:
                    db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_downstream_queue_move_updates_active_destination():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Move Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 22),
                delivery_date=date(2026, 4, 22),
                status="delivered",
                stated_weight_lbs=60,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"MOVEQ-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Move Queue Dream",
                tracking_id="MOVEQ-LOT",
                weight_lbs=60,
                remaining_weight_lbs=25,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 22),
                reactor_number=4,
                run_type="standard",
                bio_in_reactor_lbs=35,
                wet_hte_g=800,
                wet_thca_g=2200,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="golddrop_queue",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=35))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            move = client.post(
                f"/downstream-queues/runs/{run_id}/move",
                data={"target_destination": "hold_hp_base_oil"},
                follow_redirects=False,
            )
            assert move.status_code in (302, 303)
            assert move.headers["Location"].endswith("/downstream-queues")

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_queue_destination is None
            assert run.hte_potency_disposition == "hold_hp_base_oil"

        with app.test_client() as client:
            _login(client, "admin")
            complete = client.post(
                f"/downstream-queues/runs/{run_id}/move",
                data={"target_destination": "complete"},
                follow_redirects=False,
            )
            assert complete.status_code in (302, 303)

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_queue_destination is None
            assert run.hte_potency_disposition is None
    finally:
        with app.app_context():
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_golddrop_queue_page_renders_history_and_actions():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="GoldDrop Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=70,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"GDQ-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="GoldDrop Queue Dream",
                tracking_id="GDQ-LOT-1",
                weight_lbs=70,
                remaining_weight_lbs=30,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=1,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=1100,
                wet_thca_g=2800,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="golddrop_queue",
                thca_destination="sell_thca",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.add(
                app_module.DownstreamQueueEvent(
                    run_id=run.id,
                    queue_key="golddrop_queue",
                    action_key="entered_queue",
                    notes="Entered for planning",
                    created_by=admin_id,
                )
            )
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get("/downstream-queues/golddrop")
            assert resp.status_code == 200
            assert b"GoldDrop Production Queue" in resp.data
            assert b"GoldDrop Queue Dream" in resp.data
            assert b"Queue History" in resp.data
            assert b"Entered queue" in resp.data
            assert b"Mark Reviewed" in resp.data
            assert b"Queue For Production" in resp.data
            assert b"Release Complete" in resp.data
            assert b"return_to=/downstream-queues/golddrop" in resp.data or b"return_to=%2Fdownstream-queues%2Fgolddrop" in resp.data
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_golddrop_queue_actions_update_history_and_release_run():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="GoldDrop Queue Action Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=65,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"GDQA-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="GoldDrop Action Dream",
                tracking_id="GDQA-LOT-1",
                weight_lbs=65,
                remaining_weight_lbs=25,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=2,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=900,
                wet_thca_g=2400,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="golddrop_queue",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            reviewed = client.post(
                f"/downstream-queues/golddrop/runs/{run_id}/action",
                data={"queue_action": "mark_reviewed", "queue_notes": "Reviewed by planning"},
                follow_redirects=False,
            )
            assert reviewed.status_code in (302, 303)

        with app.app_context():
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id, queue_key="golddrop_queue")
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert len(events) == 1
            assert events[0].action_key == "mark_reviewed"
            assert events[0].notes == "Reviewed by planning"

        with app.test_client() as client:
            _login(client, "admin")
            released = client.post(
                f"/downstream-queues/golddrop/runs/{run_id}/action",
                data={"queue_action": "release_complete"},
                follow_redirects=False,
            )
            assert released.status_code in (302, 303)

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_queue_destination is None
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id, queue_key="golddrop_queue")
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert len(events) == 2
            assert events[-1].action_key == "release_complete"
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_liquid_loud_queue_page_and_release_to_golddrop():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Liquid Loud Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=55,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"LLQ-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Liquid Loud Dream",
                tracking_id="LLQ-LOT-1",
                weight_lbs=55,
                remaining_weight_lbs=15,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=1,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=1000,
                wet_thca_g=2200,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="liquid_loud_hold",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.add(
                app_module.DownstreamQueueEvent(
                    run_id=run.id,
                    queue_key="liquid_loud_hold",
                    action_key="entered_queue",
                    notes="Held for Liquid Loud review",
                    created_by=admin_id,
                )
            )
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            page = client.get("/downstream-queues/liquid-loud")
            assert page.status_code == 200
            assert b"Liquid Loud Hold" in page.data
            assert b"Reserve For Liquid Loud" in page.data
            assert b"Release To GoldDrop Queue" in page.data

            moved = client.post(
                f"/downstream-queues/liquid-loud/runs/{run_id}/action",
                data={"queue_action": "release_to_golddrop", "queue_notes": "Released to GoldDrop"},
                follow_redirects=False,
            )
            assert moved.status_code in (302, 303)
            assert moved.headers["Location"].endswith("/downstream-queues/golddrop")

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_queue_destination == "golddrop_queue"
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id)
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert [event.queue_key for event in events[-2:]] == ["liquid_loud_hold", "golddrop_queue"]
            assert events[-2].action_key == "release_to_golddrop"
            assert events[-1].action_key == "entered_queue"
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_terp_strip_queue_actions_update_pipeline_state():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Terp Strip Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=60,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"TSQ-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Terp Strip Dream",
                tracking_id="TSQ-LOT-1",
                weight_lbs=60,
                remaining_weight_lbs=20,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=2,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=800,
                wet_thca_g=2100,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_queue_destination="terp_strip_cage",
                hte_clean_decision="dirty",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            page = client.get("/downstream-queues/terp-strip")
            assert page.status_code == 200
            assert b"Terp Strip / CDT Cage" in page.data
            assert b"Queue Prescott" in page.data
            assert b"Strip Complete" in page.data

            prescott = client.post(
                f"/downstream-queues/terp-strip/runs/{run_id}/action",
                data={"queue_action": "queue_prescott"},
                follow_redirects=False,
            )
            assert prescott.status_code in (302, 303)

            complete = client.post(
                f"/downstream-queues/terp-strip/runs/{run_id}/action",
                data={"queue_action": "strip_complete"},
                follow_redirects=False,
            )
            assert complete.status_code in (302, 303)

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_filter_outcome == "needs_prescott"
            assert run.hte_pipeline_stage == "terp_stripped"
            assert run.hte_queue_destination is None
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id, queue_key="terp_strip_cage")
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert [event.action_key for event in events] == ["queue_prescott", "strip_complete"]
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_hp_base_oil_queue_actions_render_and_release():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="HP Base Oil Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=58,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"HBO-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Base Oil Dream",
                tracking_id="HBO-LOT-1",
                weight_lbs=58,
                remaining_weight_lbs=18,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=3,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=750,
                wet_thca_g=2000,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_potency_disposition="hold_hp_base_oil",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            page = client.get("/downstream-queues/hp-base-oil")
            assert page.status_code == 200
            assert b"HP Base Oil Hold" in page.data
            assert b"Confirm Hold" in page.data
            assert b"Release Complete" in page.data

            reviewed = client.post(
                f"/downstream-queues/hp-base-oil/runs/{run_id}/action",
                data={"queue_action": "confirm_hold", "queue_notes": "Hold confirmed"},
                follow_redirects=False,
            )
            assert reviewed.status_code in (302, 303)

            released = client.post(
                f"/downstream-queues/hp-base-oil/runs/{run_id}/action",
                data={"queue_action": "release_complete"},
                follow_redirects=False,
            )
            assert released.status_code in (302, 303)

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_potency_disposition is None
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id, queue_key="hold_hp_base_oil")
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert [event.action_key for event in events] == ["confirm_hold", "release_complete"]
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_distillate_queue_actions_render_and_release():
    app = app_module.app
    run_id = None
    purchase_id = None
    supplier_id = None
    lot_id = None
    try:
        with app.app_context():
            admin_id = app_module.User.query.filter_by(username="admin").first().id
            supplier = Supplier(name="Distillate Queue Supplier", is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id
            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=date(2026, 4, 23),
                delivery_date=date(2026, 4, 23),
                status="delivered",
                stated_weight_lbs=62,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                testing_status="completed",
                clean_or_dirty="clean",
                batch_id=f"DST-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id
            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Distillate Dream",
                tracking_id="DST-LOT-1",
                weight_lbs=62,
                remaining_weight_lbs=22,
                floor_state="inventory",
                milled=True,
            )
            db.session.add(lot)
            db.session.flush()
            lot_id = lot.id
            run = app_module.Run(
                run_date=date(2026, 4, 23),
                reactor_number=4,
                run_type="standard",
                bio_in_reactor_lbs=40,
                wet_hte_g=780,
                wet_thca_g=2050,
                created_by=admin_id,
                run_completed_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_pathway="minor_run_200",
                post_extraction_started_at=app_module.datetime.now(app_module.timezone.utc),
                post_extraction_initial_outputs_recorded_at=app_module.datetime.now(app_module.timezone.utc),
                hte_potency_disposition="hold_distillate",
            )
            db.session.add(run)
            db.session.flush()
            run_id = run.id
            db.session.add(app_module.RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
            db.session.commit()

        with app.test_client() as client:
            _login(client, "admin")
            page = client.get("/downstream-queues/distillate")
            assert page.status_code == 200
            assert b"Distillate Hold" in page.data
            assert b"Confirm Hold" in page.data
            assert b"Release Complete" in page.data

            confirmed = client.post(
                f"/downstream-queues/distillate/runs/{run_id}/action",
                data={"queue_action": "confirm_hold", "queue_notes": "Distillate hold confirmed"},
                follow_redirects=False,
            )
            assert confirmed.status_code in (302, 303)

            released = client.post(
                f"/downstream-queues/distillate/runs/{run_id}/action",
                data={"queue_action": "release_complete"},
                follow_redirects=False,
            )
            assert released.status_code in (302, 303)

        with app.app_context():
            run = db.session.get(app_module.Run, run_id)
            assert run is not None
            assert run.hte_potency_disposition is None
            events = (
                app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id, queue_key="hold_distillate")
                .order_by(app_module.DownstreamQueueEvent.created_at.asc())
                .all()
            )
            assert [event.action_key for event in events] == ["confirm_hold", "release_complete"]
    finally:
        with app.app_context():
            app_module.DownstreamQueueEvent.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            app_module.RunInput.query.filter_by(run_id=run_id).delete(synchronize_session=False)
            run = db.session.get(app_module.Run, run_id) if run_id else None
            if run:
                db.session.delete(run)
            lot = db.session.get(PurchaseLot, lot_id) if lot_id else None
            if lot:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id) if purchase_id else None
            if purchase:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id) if supplier_id else None
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_inventory_lot_edit_updates_only_lot_fields_and_returns_to_inventory():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Inventory Edit Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 18),
            delivery_date=date(2026, 4, 18),
            status="delivered",
            stated_weight_lbs=40,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"IED-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Inventory Edit Dream",
            weight_lbs=40,
            remaining_weight_lbs=40,
            floor_state="inventory",
            milled=False,
            location="Dock B",
        )
        db.session.add(lot)
        db.session.commit()
        purchase_id = purchase.id
        lot_id = lot.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            edit_page = client.get(f"/lots/{lot_id}/edit?return_to=/inventory")
            assert edit_page.status_code == 200
            assert b"Edit Lot" in edit_page.data
            assert b"Save Lot" in edit_page.data

            save = client.post(
                f"/lots/{lot_id}/edit",
                data={
                    "strain_name": "Inventory Edited Dream",
                    "potency_pct": "21.5",
                    "location": "Vault A",
                    "floor_state": "vault",
                    "milled_state": "milled",
                    "notes": "updated from inventory",
                    "return_to": "/inventory",
                },
                follow_redirects=False,
            )
            assert save.status_code in (302, 303)
            assert save.headers["Location"].endswith("/inventory")

            with app.app_context():
                lot = db.session.get(PurchaseLot, lot_id)
                purchase = db.session.get(Purchase, purchase_id)
                assert lot is not None
                assert purchase is not None
                assert lot.strain_name == "Inventory Edited Dream"
                assert float(lot.potency_pct or 0) == 21.5
                assert lot.location == "Vault A"
                assert lot.floor_state == "vault"
                assert lot.milled is True
                assert lot.notes == "updated from inventory"
                assert purchase.status == "delivered"
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


def test_inventory_label_link_can_return_to_inventory():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Inventory Label Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 18),
            delivery_date=date(2026, 4, 18),
            status="delivered",
            stated_weight_lbs=30,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            batch_id=f"ILB-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Inventory Label Dream",
            weight_lbs=30,
            remaining_weight_lbs=30,
        )
        db.session.add(lot)
        db.session.commit()
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.get(f"/lots/{lot_id}/label?return_to=/inventory")
            assert resp.status_code == 200
            assert b"Back to inventory" in resp.data
            assert b'href="/inventory"' in resp.data
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
            message_ts="1743200001.123456",
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


def test_slack_apply_charge_creates_extraction_charge_and_scan_prefill():
    app = app_module.app
    charge_id = None
    with app.app_context():
        supplier = Supplier(name="Slack Charge Supplier", is_active=True)
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
            batch_id=f"SLKCHG-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=120,
            remaining_weight_lbs=120,
        )
        row = SlackIngestedMessage(
            channel_id="C125",
            message_ts="1743200002.222222",
            raw_text="reactor: A\nsource: Slack Charge Supplier\nstrain: Blue Dream\nbio lbs: 100",
            message_kind="production_log",
        )
        db.session.add_all([lot, row])
        db.session.commit()
        row_id = row.id
        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                f"/settings/slack-imports/{row_id}/apply-charge",
                data={
                    "slack_supplier_mode": "existing",
                    "slack_supplier_id": supplier_id,
                    "slack_selected_allocations_json": json.dumps([{"lot_id": lot_id, "weight_lbs": 100.0}]),
                },
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].startswith("/runs/new")
            assert "return_to=" in resp.headers["Location"]

            with client.session_transaction() as sess:
                prefill = sess.get(app_module.SCAN_RUN_PREFILL_SESSION_KEY)
                assert prefill is not None
                charge_id = prefill["charge_id"]
                assert prefill["planned_weight_lbs"] == 100.0
                assert prefill["reactor_number"] == 1
                assert prefill["charge_source_mode"] == "slack"

            with app.app_context():
                charge = db.session.get(ExtractionCharge, charge_id)
                assert charge is not None
                assert charge.purchase_lot_id == lot_id
                assert float(charge.charged_weight_lbs or 0) == 100.0
                assert charge.reactor_number == 1
                assert charge.source_mode == "slack"
                assert charge.slack_ingested_message_id == row_id
    finally:
        with app.app_context():
            if charge_id:
                ExtractionCharge.query.filter_by(id=charge_id).delete(synchronize_session=False)
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


def test_slack_apply_charge_rejects_split_allocations():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Slack Split Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 10),
            delivery_date=date(2026, 4, 11),
            status="delivered",
            stated_weight_lbs=200,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            clean_or_dirty="clean",
            testing_status="completed",
            batch_id=f"SLKSPL-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot_one = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=120,
            remaining_weight_lbs=120,
        )
        lot_two = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=120,
            remaining_weight_lbs=120,
        )
        row = SlackIngestedMessage(
            channel_id="C126",
            message_ts="1743200003.333333",
            raw_text="reactor: 2\nsource: Slack Split Supplier\nstrain: Blue Dream\nbio lbs: 100",
            message_kind="production_log",
        )
        db.session.add_all([lot_one, lot_two, row])
        db.session.commit()
        row_id = row.id
        lot_one_id = lot_one.id
        lot_two_id = lot_two.id
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        with app.test_client() as client:
            _login(client, "admin")
            resp = client.post(
                f"/settings/slack-imports/{row_id}/apply-charge",
                data={
                    "slack_supplier_mode": "existing",
                    "slack_supplier_id": supplier_id,
                    "slack_selected_allocations_json": json.dumps(
                        [
                            {"lot_id": lot_one_id, "weight_lbs": 50.0},
                            {"lot_id": lot_two_id, "weight_lbs": 50.0},
                        ]
                    ),
                },
                follow_redirects=False,
            )
            assert resp.status_code in (302, 303)
            assert resp.headers["Location"].endswith(f"/settings/slack-imports/{row_id}/preview")

            with app.app_context():
                assert ExtractionCharge.query.filter_by(slack_ingested_message_id=row_id).count() == 0
    finally:
        with app.app_context():
            row_obj = db.session.get(SlackIngestedMessage, row_id)
            if row_obj:
                db.session.delete(row_obj)
            lot_obj = db.session.get(PurchaseLot, lot_one_id)
            if lot_obj:
                db.session.delete(lot_obj)
            lot_obj = db.session.get(PurchaseLot, lot_two_id)
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


def test_desk_purchase_intake_creates_purchase_opportunity_directly():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Desk Intake Supplier", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        supplier_id = supplier.id

    purchase_id = None
    try:
        resp = _call_view_as_user(
            "/biomass-purchasing/new-submission",
            "desk_field_purchase_submission",
            "admin",
            method="POST",
            data={
                "supplier_id": supplier_id,
                "purchase_date": "2026-04-16",
                "delivery_date": "2026-04-18",
                "estimated_potency_pct": "18.5",
                "price_per_lb": "27.25",
                "queue_placement": "indoor",
                "storage_note": "Cold room",
                "license_info": "LIC-123",
                "coa_status_text": "Pending COA",
                "notes": "desk intake opportunity",
                "lot_strains[]": ["Blue Dream"],
                "lot_weights[]": ["12.5"],
            },
        )
        assert resp.status_code in (302, 303)
        assert "/purchases/" in resp.headers["Location"]

        with app.app_context():
            purchase = Purchase.query.filter(
                Purchase.supplier_id == supplier_id,
                Purchase.notes == "desk intake opportunity",
            ).order_by(Purchase.created_at.desc()).first()
            assert purchase is not None
            purchase_id = purchase.id
            assert purchase.status == "ordered"
            assert purchase.purchase_approved_at is None
            assert float(purchase.stated_weight_lbs or 0) == 12.5
            assert float(purchase.declared_weight_lbs or 0) == 12.5
            assert float(purchase.price_per_lb or 0) == 27.25
            assert purchase.queue_placement == "indoor"
            assert purchase.coa_status_text == "Pending COA"
            assert FieldPurchaseSubmission.query.filter_by(supplier_id=supplier_id, notes="desk intake opportunity").count() == 0

            lots = PurchaseLot.query.filter_by(purchase_id=purchase.id).all()
            assert len(lots) == 1
            assert lots[0].strain_name == "Blue Dream"
            assert float(lots[0].weight_lbs or 0) == 12.5
    finally:
        with app.app_context():
            if purchase_id:
                for photo in PhotoAsset.query.filter_by(purchase_id=purchase_id).all():
                    db.session.delete(photo)
                for attachment in SupplierAttachment.query.filter_by(supplier_id=supplier_id).all():
                    if attachment.title and purchase_id in attachment.title:
                        db.session.delete(attachment)
                for lot in PurchaseLot.query.filter_by(purchase_id=purchase_id).all():
                    db.session.delete(lot)
                purchase = db.session.get(Purchase, purchase_id)
                if purchase:
                    db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier:
                db.session.delete(supplier)
            db.session.commit()


def test_supplier_merge_preview_and_execute_rehomes_records():
    app = app_module.app
    with app.app_context():
        source = Supplier(
            name="Merge Source Supplier",
            contact_name="Source Contact",
            contact_phone="555-111-2222",
            is_active=True,
        )
        target = Supplier(
            name="Merge Target Supplier",
            contact_name="Target Contact",
            contact_phone="555-333-4444",
            is_active=True,
        )
        db.session.add_all([source, target])
        db.session.flush()

        purchase = Purchase(
            supplier_id=source.id,
            purchase_date=date(2026, 4, 11),
            delivery_date=date(2026, 4, 12),
            status="delivered",
            stated_weight_lbs=10.0,
            batch_id=f"MERGE-{gen_uuid()[:8]}",
        )
        db.session.add(purchase)
        db.session.flush()

        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Merge Strain",
            weight_lbs=10.0,
            remaining_weight_lbs=10.0,
        )
        biomass = BiomassAvailability(
            supplier_id=source.id,
            availability_date=date(2026, 4, 10),
            declared_weight_lbs=4.0,
            notes="Merge test biomass row",
        )
        lab_test = LabTest(
            supplier_id=source.id,
            test_date=date(2026, 4, 9),
            test_type="coa",
            status_text="passed",
            notes="Merge test lab row",
        )
        attachment = SupplierAttachment(
            supplier_id=source.id,
            document_type="coa",
            title="Merge COA",
            file_path="uploads/supplier-merge-test.pdf",
        )
        photo = PhotoAsset(
            supplier_id=source.id,
            source_type="manual",
            category="supplier_doc",
            title="Merge photo",
            tags="merge,test",
            file_path="uploads/library/supplier-merge-test.jpg",
        )
        submission = FieldPurchaseSubmission(
            supplier_id=source.id,
            purchase_date=date(2026, 4, 8),
            status="pending",
            lots_json=json.dumps([{"strain": "Merge Strain", "weight_lbs": 3.0}]),
            notes="Merge test field submission",
        )
        db.session.add_all([lot, biomass, lab_test, attachment, photo, submission])
        db.session.commit()

        source_id = source.id
        target_id = target.id
        purchase_id = purchase.id
        biomass_id = biomass.id
        lab_test_id = lab_test.id
        attachment_id = attachment.id
        photo_id = photo.id
        submission_id = submission.id
        lot_id = lot.id

    try:
        preview = _call_view_as_user(
            f"/suppliers/{source_id}/edit",
            "supplier_edit",
            "admin",
            method="POST",
            data={
                "form_type": "merge",
                "merge_target_supplier_id": target_id,
                "merge_action": "preview",
                "merge_notes": "duplicate supplier",
            },
            sid=source_id,
        )
        assert preview.status_code == 200
        assert b"Impact Summary" in preview.data
        assert b"Purchases (and linked lots)" in preview.data

        merge = _call_view_as_user(
            f"/suppliers/{source_id}/edit",
            "supplier_edit",
            "admin",
            method="POST",
            data={
                "form_type": "merge",
                "merge_target_supplier_id": target_id,
                "merge_action": "execute",
                "merge_confirm": "1",
                "merge_notes": "duplicate supplier",
            },
            sid=source_id,
        )
        assert merge.status_code in (302, 303)
        assert merge.headers["Location"].endswith(f"/suppliers/{target_id}/edit")

        with app.app_context():
            source = db.session.get(Supplier, source_id)
            target = db.session.get(Supplier, target_id)
            purchase = db.session.get(Purchase, purchase_id)
            biomass = db.session.get(BiomassAvailability, biomass_id)
            lab_test = db.session.get(LabTest, lab_test_id)
            attachment = db.session.get(SupplierAttachment, attachment_id)
            photo = db.session.get(PhotoAsset, photo_id)
            submission = db.session.get(FieldPurchaseSubmission, submission_id)
            audit = AuditLog.query.filter_by(entity_type="supplier", entity_id=source_id, action="merge").first()

            assert source is not None
            assert target is not None
            assert source.is_active is False
            assert source.merged_into_supplier_id == target_id
            assert source.merged_by_user_id is not None
            assert source.merged_at is not None
            assert purchase is not None and purchase.supplier_id == target_id
            assert biomass is not None and biomass.supplier_id == target_id
            assert lab_test is not None and lab_test.supplier_id == target_id
            assert attachment is not None and attachment.supplier_id == target_id
            assert photo is not None and photo.supplier_id == target_id
            assert submission is not None and submission.supplier_id == target_id
            assert audit is not None
            assert target.name in (audit.details or "")
    finally:
        with app.app_context():
            for model, obj_id in (
                (FieldPurchaseSubmission, submission_id),
                (PhotoAsset, photo_id),
                (SupplierAttachment, attachment_id),
                (LabTest, lab_test_id),
                (BiomassAvailability, biomass_id),
            ):
                obj = db.session.get(model, obj_id)
                if obj is not None:
                    db.session.delete(obj)
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            audit = AuditLog.query.filter_by(entity_type="supplier", entity_id=source_id, action="merge").first()
            if audit is not None:
                db.session.delete(audit)
            source = db.session.get(Supplier, source_id)
            if source is not None:
                db.session.delete(source)
            target = db.session.get(Supplier, target_id)
            if target is not None:
                db.session.delete(target)
            db.session.commit()


def test_supplier_merge_preview_rejects_self_merge():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Merge Self Supplier", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        supplier_id = supplier.id

    try:
        with app.app_context():
            supplier = db.session.get(Supplier, supplier_id)
            assert supplier is not None
            try:
                supplier_merge_preview(app_module, supplier, supplier)
            except ValueError as exc:
                assert "different" in str(exc).lower()
            else:
                raise AssertionError("Expected self-merge preview to fail")
    finally:
        with app.app_context():
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
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


def test_purchase_edit_round_trips_mobile_fields():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Mobile Field Roundtrip Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 18),
            availability_date=date(2026, 4, 19),
            status="ordered",
            stated_weight_lbs=25.0,
            declared_weight_lbs=25.0,
            testing_notes="Initial mobile testing note",
            notes="Initial mobile note",
            batch_id=f"ROUNDTRIP-{gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id

    try:
        detail = _call_view_as_user(f"/purchases/{purchase_id}/edit", "purchase_edit", "admin", purchase_id=purchase_id)
        assert detail.status_code == 200
        assert b"Availability Date" in detail.data
        assert b"2026-04-19" in detail.data
        assert b"Testing Notes" in detail.data
        assert b"Initial mobile testing note" in detail.data

        resp = _call_view_as_user(
            f"/purchases/{purchase_id}/edit",
            "purchase_edit",
            "admin",
            method="POST",
            data={
                "supplier_id": supplier_id,
                "purchase_date": "2026-04-18",
                "availability_date": "2026-04-21",
                "status": "ordered",
                "stated_weight_lbs": "25",
                "actual_weight_lbs": "",
                "stated_potency_pct": "",
                "tested_potency_pct": "",
                "price_per_lb": "",
                "queue_placement": "",
                "coa_status_text": "",
                "clean_or_dirty": "clean",
                "indoor_outdoor": "",
                "testing_notes": "Updated from main purchase form",
                "notes": "Updated main note",
            },
            purchase_id=purchase_id,
        )
        assert resp.status_code in (302, 303)
        assert resp.headers["Location"].endswith("/purchases")

        with app.app_context():
            purchase = db.session.get(Purchase, purchase_id)
            assert purchase is not None
            assert purchase.availability_date == date(2026, 4, 21)
            assert purchase.testing_notes == "Updated from main purchase form"
            assert purchase.notes == "Updated main note"
    finally:
        with app.app_context():
            for lot in PurchaseLot.query.filter_by(purchase_id=purchase_id).all():
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            db.session.commit()


def test_lot_split_creates_new_lot_from_remaining_inventory():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Lot Split Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 18),
            delivery_date=date(2026, 4, 18),
            status="delivered",
            stated_weight_lbs=100.0,
            actual_weight_lbs=100.0,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            batch_id=f"SPLIT-{gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Original Strain",
            weight_lbs=100.0,
            remaining_weight_lbs=60.0,
            potency_pct=21.5,
            location="Vault A",
            notes="Original note",
        )
        db.session.add(lot)
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id
        lot_id = lot.id

    try:
        resp = _call_view_as_user(
            f"/lots/{lot_id}/split",
            "lot_split",
            "admin",
            method="POST",
            data={
                "split_weight_lbs": "20",
                "strain_name": "Split Strain",
                "location": "Vault B",
                "potency_pct": "22.1",
                "notes": "Split from original lot",
            },
            lot_id=lot_id,
        )
        assert resp.status_code in (302, 303)
        assert resp.headers["Location"].endswith(f"/purchases/{purchase_id}/edit")

        with app.app_context():
            original = db.session.get(PurchaseLot, lot_id)
            assert original is not None
            assert float(original.weight_lbs or 0) == 80.0
            assert float(original.remaining_weight_lbs or 0) == 40.0

            lots = PurchaseLot.query.filter_by(purchase_id=purchase_id).order_by(PurchaseLot.id.asc()).all()
            assert len(lots) == 2
            new_lot = next(l for l in lots if l.id != lot_id)
            assert new_lot.strain_name == "Split Strain"
            assert float(new_lot.weight_lbs or 0) == 20.0
            assert float(new_lot.remaining_weight_lbs or 0) == 20.0
            assert float(new_lot.potency_pct or 0) == 22.1
            assert new_lot.location == "Vault B"
            assert new_lot.notes == "Split from original lot"
            assert new_lot.tracking_id

            audit = AuditLog.query.filter_by(entity_type="lot", entity_id=lot_id, action="split").first()
            assert audit is not None
            assert new_lot.id in (audit.details or "")
    finally:
        with app.app_context():
            for audit in AuditLog.query.filter_by(entity_type="lot", entity_id=lot_id, action="split").all():
                db.session.delete(audit)
            for lot in PurchaseLot.query.filter_by(purchase_id=purchase_id).all():
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            db.session.commit()


def test_mobile_created_purchase_review_surfaces_origin_and_photos():
    app = app_module.app
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        supplier = Supplier(name="Mobile Review Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date.today(),
            delivery_date=date.today(),
            status="delivered",
            stated_weight_lbs=10.0,
            actual_weight_lbs=9.5,
            batch_id=f"MOBILE-REVIEW-{gen_uuid()[:6]}",
            created_by_user_id=admin.id,
            delivery_recorded_by_user_id=admin.id,
            purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
            purchase_approved_by_user_id=admin.id,
        )
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=10.0,
            remaining_weight_lbs=10.0,
        )
        db.session.add(lot)
        db.session.flush()
        opp_photo = PhotoAsset(
            purchase_id=purchase.id,
            supplier_id=supplier.id,
            source_type="mobile_api",
            category="biomass",
            photo_context="opportunity",
            file_path="uploads/library/mobile-opportunity-test.jpg",
            title="Opportunity photo",
            uploaded_by=admin.id,
        )
        delivery_photo = PhotoAsset(
            purchase_id=purchase.id,
            supplier_id=supplier.id,
            source_type="mobile_api",
            category="biomass",
            photo_context="delivery",
            file_path="uploads/library/mobile-delivery-test.jpg",
            title="Delivery photo",
            uploaded_by=admin.id,
        )
        db.session.add_all([opp_photo, delivery_photo])
        db.session.commit()
        purchase_id = purchase.id
        supplier_id = supplier.id
        lot_id = lot.id
        opp_photo_id = opp_photo.id
        delivery_photo_id = delivery_photo.id

    try:
        listing = _call_view_as_user("/purchases", "purchases_list", "admin")
        assert listing.status_code == 200
        assert b"Mobile app" in listing.data
        assert b"Created by VP Operations" in listing.data

        detail = _call_view_as_user(f"/purchases/{purchase_id}/edit", "purchase_edit", "admin", purchase_id=purchase_id)
        assert detail.status_code == 200
        assert b"Submission Origin" in detail.data
        assert b"Delivery Recorded By" in detail.data
        assert b"Opportunity intake photos" in detail.data
        assert b"Delivery confirmation photos" in detail.data
    finally:
        with app.app_context():
            for model, obj_id in (
                (PhotoAsset, opp_photo_id),
                (PhotoAsset, delivery_photo_id),
                (PurchaseLot, lot_id),
                (Purchase, purchase_id),
                (Supplier, supplier_id),
            ):
                obj = db.session.get(model, obj_id)
                if obj is not None:
                    db.session.delete(obj)
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


def test_unapproved_opportunity_purchase_displays_pending_labels():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name="Opportunity Label Supplier", is_active=True)
        db.session.add(supplier)
        db.session.flush()

        purchase = Purchase(
            supplier_id=supplier.id,
            purchase_date=date(2026, 4, 16),
            status="ordered",
            stated_weight_lbs=80,
            batch_id=f"OPP-LABEL-{app_module.gen_uuid()[:6]}",
        )
        db.session.add(purchase)
        db.session.flush()

        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Opportunity Label Strain",
            weight_lbs=80,
            remaining_weight_lbs=80,
        )
        db.session.add(lot)
        db.session.commit()

        purchase_id = purchase.id
        lot_id = lot.id
        supplier_id = supplier.id

        db.session.refresh(purchase)
        purchases_module._annotate_purchase_row(purchase)
        assert purchase._display_status_key == "opportunity"
        assert purchase._display_status_label == "Opportunity"
        assert purchase._allocation_state_key == "pending_approval"
        assert purchase._allocation_state_label == "Pending approval"

    try:
        listing = _call_view_as_user("/purchases", "purchases_list", "admin")
        assert listing.status_code == 200
        assert b"Opportunity" in listing.data
        assert b"Pending approval" in listing.data
    finally:
        with app.app_context():
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None:
                db.session.delete(lot)
            purchase = db.session.get(Purchase, purchase_id)
            if purchase is not None:
                db.session.delete(purchase)
            supplier = db.session.get(Supplier, supplier_id)
            if supplier is not None:
                db.session.delete(supplier)
            db.session.commit()
