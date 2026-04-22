from __future__ import annotations

import io
import uuid

import app as app_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.suppliers_module as suppliers_module
from models import Supplier, User, db
from supplier_import import (
    parse_supplier_spreadsheet_upload_for_mapping,
    supplier_import_rows_from_mapping,
)
from flask_login import login_user


def test_supplier_import_mapping_detects_headers_and_suggestions():
    raw = (
        "Vendor,Contact,Phone,Email,Location,Active\n"
        "Example Farm,Jamie Buyer,555-0101,jamie@example.com,Salinas,yes\n"
    ).encode("utf-8")

    staged = parse_supplier_spreadsheet_upload_for_mapping("supplier.csv", raw)

    mapping = staged["mapping"]
    assert any(field == "name" for field in mapping.values())
    assert any(field == "contact_name" for field in mapping.values())
    assert any(field == "contact_phone" for field in mapping.values())
    assert any(field == "contact_email" for field in mapping.values())
    assert any(field == "location" for field in mapping.values())
    assert any(field == "is_active" for field in mapping.values())


def test_supplier_import_rows_follow_manual_mapping_override():
    data_rows = [["Example Farm", "Jamie Buyer", "Salinas"]]
    mapping = {
        "0": "name",
        "1": "contact_name",
        "2": "location",
    }

    rows = supplier_import_rows_from_mapping(data_rows, mapping, 0)

    assert len(rows) == 1
    assert rows[0]["name"] == "Example Farm"
    assert rows[0]["contact_name"] == "Jamie Buyer"
    assert rows[0]["location"] == "Salinas"


def test_supplier_import_commit_creates_and_updates_matching_supplier():
    app = app_module.app
    unique_name = f"Import Supplier {uuid.uuid4().hex[:8]}"
    supplier_id = None
    try:
        with app.app_context():
            bootstrap_module.init_db(app_module)
            existing = Supplier(name=unique_name, is_active=True, contact_name="Old Name")
            db.session.add(existing)
            db.session.commit()
            supplier_id = existing.id

            errors, norm = suppliers_module.supplier_import_validate_row(
                app_module,
                {
                    "name": unique_name,
                    "contact_name": "New Buyer",
                    "contact_phone": "555-1111",
                    "contact_email": "buyer@example.com",
                    "location": "Salinas",
                    "notes": "Imported supplier row",
                    "is_active": "yes",
                },
            )
            assert not errors
            assert norm is not None
            assert norm["exact_match_supplier_id"] == supplier_id

            admin = User.query.filter_by(username="admin").first()
            assert admin is not None
            with app.test_request_context("/suppliers/import/commit", method="POST"):
                login_user(admin)
                suppliers_module.supplier_import_commit_norm(app_module, norm, update_existing=True)

            updated = db.session.get(Supplier, supplier_id)
            assert updated is not None
            assert updated.contact_name == "New Buyer"
            assert updated.contact_phone == "555-1111"
            assert updated.contact_email == "buyer@example.com"
            assert updated.location == "Salinas"
            assert updated.notes == "Imported supplier row"
    finally:
        with app.app_context():
            if supplier_id:
                Supplier.query.filter_by(id=supplier_id).delete()
            db.session.commit()


def test_supplier_import_preview_renders_mapping_ui():
    app = app_module.app
    with app.test_client() as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "golddrop2026"},
            follow_redirects=False,
        )
        assert login.status_code in (302, 303)

        raw = (
            "Supplier,Contact Name,Phone,Email,Location,Active\n"
            "Example Farm,Jamie Buyer,555-0101,jamie@example.com,Salinas,yes\n"
        ).encode("utf-8")
        response = client.post(
            "/suppliers/import",
            data={"spreadsheet": (io.BytesIO(raw), "suppliers.csv")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Column mapping" in response.data
        assert b"Map to supplier field" in response.data
        assert b"Update existing suppliers" in response.data
