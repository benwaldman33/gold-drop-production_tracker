from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import MaterialLot, MaterialReconciliationIssue, Purchase, PurchaseLot, Run, RunInput, Supplier, db
from services.material_genealogy import (
    backfill_biomass_material_lots,
    reconcile_run_material_genealogy,
    source_material_lots_for_run,
)


def _approved_purchase(supplier_id: str) -> Purchase:
    return Purchase(
        supplier_id=supplier_id,
        purchase_date=date.today(),
        status="delivered",
        stated_weight_lbs=100,
        actual_weight_lbs=100,
        purchase_approved_at=datetime.now(timezone.utc),
    )


def test_backfill_biomass_material_lots_bridges_purchase_lots():
    app = app_module.create_app()
    with app.app_context():
        supplier = Supplier(name=f"Genealogy Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Blue Dream",
            weight_lbs=80,
            remaining_weight_lbs=80,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        db.session.add(lot)
        db.session.commit()

        try:
            count = backfill_biomass_material_lots(app_module)
            db.session.commit()

            db.session.refresh(lot)
            assert count >= 1
            assert lot.material_lot_id
            material_lot = db.session.get(MaterialLot, lot.material_lot_id)
            assert material_lot is not None
            assert material_lot.lot_type == "biomass"
            assert material_lot.source_purchase_lot_id == lot.id
            assert material_lot.tracking_id == lot.tracking_id
            assert material_lot.inventory_status == "open"
        finally:
            material_lot = db.session.get(MaterialLot, lot.material_lot_id) if lot.material_lot_id else None
            if material_lot is not None:
                db.session.delete(material_lot)
            db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_source_material_lots_for_run_returns_bridged_biomass_lots():
    app = app_module.create_app()
    with app.app_context():
        supplier = Supplier(name=f"Run Source Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Gelato",
            weight_lbs=100,
            remaining_weight_lbs=60,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=1,
            bio_in_reactor_lbs=40,
        )
        db.session.add_all([lot, run])
        db.session.flush()
        allocation = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40)
        db.session.add(allocation)
        db.session.commit()

        try:
            backfill_biomass_material_lots(app_module)
            db.session.commit()
            material_lots = source_material_lots_for_run(app_module, run)
            assert len(material_lots) == 1
            assert material_lots[0].lot_type == "biomass"
            assert material_lots[0].source_purchase_lot_id == lot.id
        finally:
            if lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            db.session.delete(run)
            db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_reconcile_run_material_genealogy_flags_missing_allocations():
    app = app_module.create_app()
    with app.app_context():
        run = Run(run_date=date.today(), reactor_number=2, bio_in_reactor_lbs=55)
        db.session.add(run)
        db.session.commit()
        try:
            issues = reconcile_run_material_genealogy(app_module, run)
            db.session.commit()
            assert issues
            stored = MaterialReconciliationIssue.query.filter_by(run_id=run.id, issue_type="missing_input_link", status="open").all()
            assert stored
        finally:
            MaterialReconciliationIssue.query.filter_by(run_id=run.id).delete()
            db.session.delete(run)
            db.session.commit()
