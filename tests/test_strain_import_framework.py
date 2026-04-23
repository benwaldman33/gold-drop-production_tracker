from __future__ import annotations

import io
import uuid

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.strains_module as strains_module
from flask_login import login_user
from models import Purchase, PurchaseLot, Supplier, User, db
from strain_import import (
    parse_strain_spreadsheet_upload_for_mapping,
    strain_import_rows_from_mapping,
)


def test_strain_import_mapping_detects_headers_and_suggestions():
    raw = (
        "Supplier,Current Strain,New Strain,Notes\n"
        "Example Farm,Blue Dream,Blue Dream BX1,Rename vendor spelling\n"
    ).encode("utf-8")

    staged = parse_strain_spreadsheet_upload_for_mapping("strain.csv", raw)

    mapping = staged["mapping"]
    assert any(field == "supplier_name" for field in mapping.values())
    assert any(field == "current_strain_name" for field in mapping.values())
    assert any(field == "new_strain_name" for field in mapping.values())
    assert any(field == "notes" for field in mapping.values())


def test_strain_import_rows_follow_manual_mapping_override():
    data_rows = [["Example Farm", "Blue Dream", "Blue Dream BX1", "Rename row"]]
    mapping = {
        "0": "supplier_name",
        "1": "current_strain_name",
        "2": "new_strain_name",
        "3": "notes",
    }

    rows = strain_import_rows_from_mapping(data_rows, mapping, 0)

    assert len(rows) == 1
    assert rows[0]["supplier_name"] == "Example Farm"
    assert rows[0]["current_strain_name"] == "Blue Dream"
    assert rows[0]["new_strain_name"] == "Blue Dream BX1"
    assert rows[0]["notes"] == "Rename row"


def test_strain_import_commit_renames_matching_lots():
    app = app_module.app
    unique_supplier = f"Strain Import Farm {uuid.uuid4().hex[:8]}"
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
                purchase_date=app_module.date(2026, 4, 21),
                status="ordered",
                stated_weight_lbs=100,
            )
            db.session.add(purchase)
            db.session.flush()
            purchase_id = purchase.id

            lot = PurchaseLot(
                purchase_id=purchase.id,
                strain_name="Blue Dream",
                weight_lbs=100,
                remaining_weight_lbs=100,
            )
            db.session.add(lot)
            db.session.commit()
            lot_id = lot.id

            errors, norm = strains_module.strain_import_validate_row(
                app_module,
                {
                    "supplier_name": unique_supplier,
                    "current_strain_name": "Blue Dream",
                    "new_strain_name": "Blue Dream BX1",
                    "notes": "Standardize naming",
                },
            )
            assert not errors
            assert norm is not None
            assert norm["matched_lot_count"] == 1

            admin = User.query.filter_by(username="admin").first()
            assert admin is not None
            with app.test_request_context("/strains/import/commit", method="POST"):
                login_user(admin)
                strains_module.strain_import_commit_norm(app_module, norm)

            lot = db.session.get(PurchaseLot, lot_id)
            assert lot is not None
            assert lot.strain_name == "Blue Dream BX1"
    finally:
        with app.app_context():
            if lot_id:
                PurchaseLot.query.filter_by(id=lot_id).delete()
            if purchase_id:
                Purchase.query.filter_by(id=purchase_id).delete()
            if supplier_id:
                Supplier.query.filter_by(id=supplier_id).delete()
            db.session.commit()


def test_strain_import_preview_renders_mapping_ui():
    app = app_module.app
    with app.test_client() as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "golddrop2026"},
            follow_redirects=False,
        )
        assert login.status_code in (302, 303)

        raw = (
            "Supplier,Current Strain,New Strain,Notes\n"
            "Example Farm,Blue Dream,Blue Dream BX1,Rename vendor spelling\n"
        ).encode("utf-8")
        response = client.post(
            "/strains/import",
            data={"spreadsheet": (io.BytesIO(raw), "strains.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Column mapping" in response.data
        assert b"Map to strain import field" in response.data
        assert b"Matched lots" in response.data
