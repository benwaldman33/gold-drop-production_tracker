from __future__ import annotations

import io
import uuid

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.inventory_module as inventory_module
from flask_login import login_user
from models import Purchase, PurchaseLot, Supplier, User, db
from inventory_import import (
    inventory_import_rows_from_mapping,
    parse_inventory_spreadsheet_upload_for_mapping,
)


def test_inventory_import_mapping_detects_headers_and_suggestions():
    raw = (
        "Tracking ID,Strain,Potency %,Location,Floor State,Milled,Notes\n"
        "LOT-ABC12345,Blue Dream,31.2,Dock B,reactor_staging,yes,Ready for charge\n"
    ).encode("utf-8")

    staged = parse_inventory_spreadsheet_upload_for_mapping("inventory.csv", raw)

    mapping = staged["mapping"]
    assert any(field == "tracking_id" for field in mapping.values())
    assert any(field == "strain_name" for field in mapping.values())
    assert any(field == "potency_pct" for field in mapping.values())
    assert any(field == "location" for field in mapping.values())
    assert any(field == "floor_state" for field in mapping.values())
    assert any(field == "milled" for field in mapping.values())
    assert any(field == "notes" for field in mapping.values())


def test_inventory_import_rows_follow_manual_mapping_override():
    data_rows = [["LOT-ABC12345", "Vault A", "quarantine"]]
    mapping = {
        "0": "tracking_id",
        "1": "location",
        "2": "floor_state",
    }

    rows = inventory_import_rows_from_mapping(data_rows, mapping, 0)

    assert len(rows) == 1
    assert rows[0]["tracking_id"] == "LOT-ABC12345"
    assert rows[0]["location"] == "Vault A"
    assert rows[0]["floor_state"] == "quarantine"


def test_inventory_import_commit_updates_matching_lot():
    app = app_module.app
    unique_supplier = f"Inventory Import Farm {uuid.uuid4().hex[:8]}"
    supplier_id = None
    purchase_id = None
    lot_id = None
    try:
        with app.app_context():
            bootstrap_module.init_db(app_module)
            supplier = Supplier(name=unique_supplier, is_active=True)
            db.session.add(supplier)
            db.session.flush()
            supplier_id = supplier.id

            purchase = Purchase(
                supplier_id=supplier.id,
                purchase_date=app_module.date(2026, 4, 22),
                delivery_date=app_module.date(2026, 4, 22),
                status="delivered",
                stated_weight_lbs=100,
                purchase_approved_at=app_module.datetime.now(app_module.timezone.utc),
                batch_id=f"IIM-{app_module.gen_uuid()[:6]}",
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id

            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Blue Dream",
                weight_lbs=100,
                remaining_weight_lbs=100,
                potency_pct=29.0,
                location="Dock B",
                floor_state="inventory",
                milled=False,
                notes="Original note",
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id
            tracking_id = lot.tracking_id

            errors, norm = inventory_module.inventory_import_validate_row(
                app_module,
                {
                    "tracking_id": tracking_id,
                    "strain_name": "Blue Dream BX1",
                    "potency_pct": "31.2",
                    "location": "Vault A",
                    "floor_state": "vault",
                    "milled": "yes",
                    "notes": "Imported inventory update",
                },
            )
            assert not errors
            assert norm is not None
            assert norm["lot_id"] == lot_id

            admin = User.query.filter_by(username="admin").first()
            assert admin is not None
            with app.test_request_context("/inventory/import/commit", method="POST"):
                login_user(admin)
                inventory_module.inventory_import_commit_norm(app_module, norm)

            updated = db.session.get(PurchaseLot, lot_id)
            assert updated is not None
            assert updated.strain_name == "Blue Dream BX1"
            assert float(updated.potency_pct or 0) == 31.2
            assert updated.location == "Vault A"
            assert updated.floor_state == "vault"
            assert updated.milled is True
            assert updated.notes == "Imported inventory update"
    finally:
        with app.app_context():
            if lot_id:
                PurchaseLot.query.filter_by(id=lot_id).delete()
            if purchase_id:
                Purchase.query.filter_by(id=purchase_id).delete()
            if supplier_id:
                Supplier.query.filter_by(id=supplier_id).delete()
            db.session.commit()


def test_inventory_import_preview_renders_mapping_ui():
    app = app_module.app
    with app.test_client() as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "golddrop2026"},
            follow_redirects=False,
        )
        assert login.status_code in (302, 303)

        raw = (
            "Tracking ID,Strain,Location,Floor State\n"
            "LOT-ABC12345,Blue Dream,Vault A,vault\n"
        ).encode("utf-8")
        response = client.post(
            "/inventory/import",
            data={"spreadsheet": (io.BytesIO(raw), "inventory.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Column mapping" in response.data
        assert b"Map to inventory field" in response.data
        assert b"Tracking ID" in response.data
