from __future__ import annotations

import io
import uuid

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.purchase_import_module as purchase_import_module
from flask_login import login_user
from models import Purchase, PurchaseLot, Supplier, db
from purchase_import import (
    parse_purchase_spreadsheet_upload_for_mapping,
    purchase_import_rows_from_mapping,
)


def test_purchase_import_mapping_detects_headers_and_field_suggestions():
    raw = (
        "Vendor,Purchase Date,Invoice Weight,Manifest,Testing Notes,Floor State\n"
        "Example Farm,2026-04-21,275,MAN-001,COA pending,inventory\n"
    ).encode("utf-8")

    staged = parse_purchase_spreadsheet_upload_for_mapping("sample.csv", raw)

    mapping = staged["mapping"]
    assert any(field == "supplier" for field in mapping.values())
    assert any(field == "purchase_date" for field in mapping.values())
    assert any(field == "stated_weight_lbs" for field in mapping.values())
    assert any(field == "testing_notes" for field in mapping.values())
    assert any(field == "lot_floor_state" for field in mapping.values())


def test_purchase_import_rows_follow_manual_mapping_override():
    data_rows = [["Example Farm", "Dock B", "2026-04-21", "275"]]
    mapping = {
        "0": "supplier",
        "1": "lot_location",
        "2": "purchase_date",
        "3": "stated_weight_lbs",
    }

    rows = purchase_import_rows_from_mapping(data_rows, mapping, 0)

    assert len(rows) == 1
    assert rows[0]["supplier"] == "Example Farm"
    assert rows[0]["lot_location"] == "Dock B"
    assert rows[0]["purchase_date"] == "2026-04-21"
    assert rows[0]["stated_weight_lbs"] == "275"


def test_purchase_import_commit_sets_extended_purchase_and_lot_fields():
    app = app_module.app
    unique_name = f"Import Test Farm {uuid.uuid4().hex[:8]}"
    purchase_id = None
    supplier_id = None
    try:
        with app.app_context():
            bootstrap_module.init_db(app_module)
            supplier = Supplier(name=unique_name, is_active=True)
            db.session.add(supplier)
            db.session.commit()
            supplier_id = supplier.id

            errors, norm = purchase_import_module.purchase_import_validate_row(
                app_module,
                {
                    "supplier": unique_name,
                    "purchase_date": "2026-04-21",
                    "stated_weight_lbs": "250",
                    "status": "ordered",
                    "testing_notes": "Initial intake note",
                    "delivery_notes": "Dock checked",
                    "availability_date": "2026-04-20",
                    "declared_weight_lbs": "255",
                    "declared_price_per_lb": "18.5",
                    "testing_timing": "after_delivery",
                    "testing_status": "pending",
                    "testing_date": "2026-04-22",
                    "strain": "Blue Dream",
                    "lot_weight_lbs": "240",
                    "lot_potency_pct": "31.2",
                    "lot_milled": "yes",
                    "lot_floor_state": "reactor_staging",
                    "lot_location": "Dock B",
                    "lot_notes": "Ready for charge",
                },
            )
            assert not errors
            assert norm is not None

            from models import User

            admin = User.query.filter_by(username="admin").first()
            assert admin is not None
            with app.test_request_context("/purchases/import/commit", method="POST"):
                login_user(admin)
                purchase_import_module.purchase_import_commit_norm(app_module, norm, create_suppliers=False)

            purchase = (
                Purchase.query.filter(Purchase.supplier_id == supplier_id)
                .order_by(Purchase.created_at.desc())
                .first()
            )
            assert purchase is not None
            purchase_id = purchase.id
            assert purchase.testing_notes == "Initial intake note"
            assert purchase.delivery_notes == "Dock checked"
            assert purchase.availability_date.isoformat() == "2026-04-20"
            assert purchase.declared_weight_lbs == 255.0
            assert purchase.declared_price_per_lb == 18.5
            assert purchase.testing_timing == "after_delivery"
            assert purchase.testing_status == "pending"
            assert purchase.testing_date.isoformat() == "2026-04-22"

            lot = PurchaseLot.query.filter_by(purchase_id=purchase_id).first()
            assert lot is not None
            assert lot.strain_name == "Blue Dream"
            assert lot.weight_lbs == 240.0
            assert lot.potency_pct == 31.2
            assert lot.milled is True
            assert lot.floor_state == "reactor_staging"
            assert lot.location == "Dock B"
            assert lot.notes == "Ready for charge"
    finally:
        with app.app_context():
            if purchase_id:
                PurchaseLot.query.filter_by(purchase_id=purchase_id).delete()
                Purchase.query.filter_by(id=purchase_id).delete()
            if supplier_id:
                Supplier.query.filter_by(id=supplier_id).delete()
            db.session.commit()


def test_purchase_import_preview_renders_mapping_ui():
    app = app_module.app
    with app.test_client() as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "golddrop2026"},
            follow_redirects=False,
        )
        assert login.status_code in (302, 303)

        raw = (
            "Vendor,Purchase Date,Invoice Weight,Manifest,Strain,Lot Location\n"
            "Example Farm,2026-04-21,275,MAN-001,Blue Dream,Dock B\n"
        ).encode("utf-8")
        response = client.post(
            "/purchases/import",
            data={"spreadsheet": (io.BytesIO(raw), "sample.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Column mapping" in response.data
        assert b"Map to app field" in response.data
        assert b"Lot location" in response.data
