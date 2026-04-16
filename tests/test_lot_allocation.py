from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import Purchase, PurchaseLot, Run, RunInput, Supplier, db, gen_uuid
from services.lot_allocation import apply_run_allocations, release_run_allocations


def _login_admin(client) -> None:
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "golddrop2026"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_purchase_lot_generates_tracking_fields_on_insert():
    app = app_module.app
    supplier = Supplier(name=f"Lot Tracking {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 10),
        status="delivered",
        stated_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
    )
    lot = PurchaseLot(strain_name="Tracking Strain", weight_lbs=100, remaining_weight_lbs=100)

    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.commit()

        lot_id = lot.id
        purchase_id = purchase.id
        supplier_id = supplier.id

        saved = db.session.get(PurchaseLot, lot_id)
        assert saved is not None
        assert saved.tracking_id and saved.tracking_id.startswith("LOT-")
        assert saved.barcode_value == saved.tracking_id
        assert saved.qr_value == f"/scan/lot/{saved.tracking_id}"
        assert saved.label_generated_at is not None
        assert saved.label_version == 1

        db.session.delete(saved)
        db.session.delete(db.session.get(Purchase, purchase_id))
        db.session.delete(db.session.get(Supplier, supplier_id))
        db.session.commit()


def test_purchase_approval_backfills_missing_lot_tracking_fields():
    app = app_module.app
    supplier = Supplier(name=f"Approval Backfill {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 11),
        status="ordered",
        stated_weight_lbs=50,
    )
    lot = PurchaseLot(strain_name="Approval Strain", weight_lbs=50, remaining_weight_lbs=50)

    with app.app_context():
        db.session.add(supplier)
        db.session.flush()
        purchase.supplier_id = supplier.id
        db.session.add(purchase)
        db.session.flush()
        lot.purchase_id = purchase.id
        db.session.add(lot)
        db.session.commit()

        purchase_id = purchase.id
        lot_id = lot.id
        supplier_id = supplier.id

        saved = db.session.get(PurchaseLot, lot_id)
        saved.tracking_id = None
        saved.barcode_value = None
        saved.qr_value = None
        saved.label_generated_at = None
        saved.label_version = None
        db.session.commit()

    try:
        with app.test_client() as client:
            _login_admin(client)
            res = client.post(f"/purchases/{purchase_id}/approve", follow_redirects=False)
            assert res.status_code in (302, 303)

        with app.app_context():
            updated_purchase = db.session.get(Purchase, purchase_id)
            updated_lot = db.session.get(PurchaseLot, lot_id)
            assert updated_purchase is not None
            assert updated_purchase.purchase_approved_at is not None
            assert updated_lot is not None
            assert updated_lot.tracking_id and updated_lot.tracking_id.startswith("LOT-")
            assert updated_lot.barcode_value == updated_lot.tracking_id
            assert updated_lot.qr_value == f"/scan/lot/{updated_lot.tracking_id}"
            assert updated_lot.label_generated_at is not None
            assert updated_lot.label_version == 1
    finally:
        with app.app_context():
            lot_row = db.session.get(PurchaseLot, lot_id)
            if lot_row:
                db.session.delete(lot_row)
            purchase_row = db.session.get(Purchase, purchase_id)
            if purchase_row:
                db.session.delete(purchase_row)
            supplier_row = db.session.get(Supplier, supplier_id)
            if supplier_row:
                db.session.delete(supplier_row)
            db.session.commit()


def test_apply_run_allocations_decrements_and_releases_lot_weight():
    app = app_module.app
    supplier = Supplier(name=f"Allocation Supplier {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        status="delivered",
        stated_weight_lbs=150,
        purchase_approved_at=datetime.now(timezone.utc),
    )
    lot = PurchaseLot(strain_name="Allocation Strain", weight_lbs=150, remaining_weight_lbs=150)
    run = Run(run_date=date(2026, 4, 12), reactor_number=1, bio_in_reactor_lbs=100)

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

        total = apply_run_allocations(
            app_module,
            run,
            [{"lot_id": lot.id, "weight_lbs": 100.0}],
            allocation_source="manual",
        )
        db.session.flush()

        saved_lot = db.session.get(PurchaseLot, lot.id)
        saved_input = RunInput.query.filter_by(run_id=run.id, lot_id=lot.id).first()
        assert total == 100.0
        assert saved_lot is not None
        assert float(saved_lot.remaining_weight_lbs or 0) == 50.0
        assert saved_lot.allocated_weight_lbs == 100.0
        assert saved_input is not None
        assert saved_input.allocation_source == "manual"

        release_run_allocations(app_module, run)
        assert float(saved_lot.remaining_weight_lbs or 0) == 150.0

        if saved_input:
            db.session.delete(saved_input)
        db.session.delete(run)
        db.session.delete(saved_lot)
        db.session.delete(db.session.get(Purchase, purchase.id))
        db.session.delete(db.session.get(Supplier, supplier.id))
        db.session.commit()


def test_apply_run_allocations_rejects_over_allocation():
    app = app_module.app
    supplier = Supplier(name=f"Allocation Reject {gen_uuid()[:8]}", is_active=True)
    purchase = Purchase(
        supplier_id="",
        purchase_date=date(2026, 4, 12),
        status="delivered",
        stated_weight_lbs=40,
        purchase_approved_at=datetime.now(timezone.utc),
    )
    lot = PurchaseLot(strain_name="Reject Strain", weight_lbs=40, remaining_weight_lbs=40)
    run = Run(run_date=date(2026, 4, 12), reactor_number=2, bio_in_reactor_lbs=50)

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

        try:
            apply_run_allocations(
                app_module,
                run,
                [{"lot_id": lot.id, "weight_lbs": 50.0}],
                allocation_source="manual",
            )
            raise AssertionError("Expected over-allocation to raise ValueError")
        except ValueError as exc:
            assert "only has 40.0 lbs remaining" in str(exc)
        finally:
            db.session.delete(run)
            db.session.delete(lot)
            db.session.delete(db.session.get(Purchase, purchase.id))
            db.session.delete(db.session.get(Supplier, supplier.id))
            db.session.commit()
