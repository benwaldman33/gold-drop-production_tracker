from __future__ import annotations

from datetime import date, datetime, timezone

import app as app_module
from models import DownstreamQueueEvent, MaterialLot, MaterialReconciliationIssue, MaterialTransformation, Purchase, PurchaseLot, Run, RunInput, Supplier, db
from services.material_genealogy import (
    apply_material_lot_correction,
    backfill_biomass_material_lots,
    build_material_lot_ancestry_payload,
    build_material_lot_descendants_payload,
    build_material_lot_detail_payload,
    build_material_lot_journey_payload,
    derivative_material_lots_for_run,
    ensure_downstream_output_genealogy,
    ensure_biomass_material_lot,
    ensure_extraction_output_genealogy,
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
    app = app_module.app
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
    app = app_module.app
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
        run_id = run.id
        lot_id = lot.id
        allocation = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40)
        db.session.add(allocation)
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            db.session.commit()
            material_lots = source_material_lots_for_run(app_module, run)
            assert len(material_lots) == 1
            assert material_lots[0].lot_type == "biomass"
            assert material_lots[0].source_purchase_lot_id == lot.id
        finally:
            db.session.rollback()
            run = db.session.get(Run, run_id)
            lot = db.session.get(PurchaseLot, lot_id)
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
    app = app_module.app
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


def test_ensure_extraction_output_genealogy_creates_derivative_lots_and_transformation():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Output Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Sour Diesel",
            weight_lbs=120,
            remaining_weight_lbs=80,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=3,
            bio_in_reactor_lbs=40,
            dry_hte_g=12,
            dry_thca_g=28,
            cost_per_gram_hte=3.5,
            cost_per_gram_thca=4.5,
        )
        db.session.add_all([lot, run])
        db.session.flush()
        run_id = run.id
        lot_id = lot.id
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            transformation = ensure_extraction_output_genealogy(app_module, run)
            db.session.commit()

            assert transformation is not None
            assert transformation.transformation_type == "extraction"
            assert transformation.inputs.count() == 1
            assert transformation.outputs.count() == 2

            derivative_lots = derivative_material_lots_for_run(app_module, run)
            assert {item.lot_type for item in derivative_lots} == {"dry_hte", "dry_thca"}
            by_type = {item.lot_type: item for item in derivative_lots}
            assert by_type["dry_hte"].quantity == 12.0
            assert by_type["dry_hte"].unit == "g"
            assert by_type["dry_hte"].cost_basis_per_unit == 3.5
            assert by_type["dry_thca"].quantity == 28.0
            assert by_type["dry_thca"].cost_basis_per_unit == 4.5
        finally:
            db.session.rollback()
            MaterialReconciliationIssue.query.filter_by(run_id=run_id).delete()
            run = db.session.get(Run, run_id)
            for output in run.material_lots.all() if run is not None else []:
                db.session.delete(output)
            MaterialTransformation.query.filter_by(run_id=run_id).delete()
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None and lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            if run is not None:
                db.session.delete(run)
            if lot is not None:
                db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_material_lot_payloads_include_ancestry_and_descendants():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Journey Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Papaya",
            weight_lbs=100,
            remaining_weight_lbs=55,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=4,
            bio_in_reactor_lbs=45,
            dry_hte_g=15,
        )
        db.session.add_all([lot, run])
        db.session.flush()
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=45))
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            ensure_extraction_output_genealogy(app_module, run)
            db.session.commit()

            derivative_lot = run.material_lots.filter_by(lot_type="dry_hte").first()

            with app.test_request_context("/"):
                detail = build_material_lot_detail_payload(app_module, derivative_lot)
                ancestry = build_material_lot_ancestry_payload(app_module, derivative_lot)
                journey = build_material_lot_journey_payload(app_module, derivative_lot)

                assert detail["material_lot"]["lot_type"] == "dry_hte"
                assert ancestry["ancestry"][0]["transformation"]["transformation_type"] == "extraction"
                assert ancestry["ancestry"][0]["inputs"][0]["material_lot"]["lot_type"] == "biomass"
                assert journey["summary"]["ancestor_transformation_count"] >= 1
        finally:
            MaterialReconciliationIssue.query.filter_by(run_id=run.id).delete()
            for output in run.material_lots.all():
                db.session.delete(output)
            MaterialTransformation.query.filter_by(run_id=run.id).delete()
            if lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            db.session.delete(run)
            db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_apply_material_lot_correction_adjusts_quantity_with_replacement_and_audit():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Correction Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Runtz",
            weight_lbs=100,
            remaining_weight_lbs=60,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=5,
            bio_in_reactor_lbs=40,
            dry_hte_g=10,
        )
        db.session.add_all([lot, run])
        db.session.flush()
        run_id = run.id
        lot_id = lot.id
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            ensure_extraction_output_genealogy(app_module, run)
            db.session.commit()

            derivative_lot = run.material_lots.filter_by(lot_type="dry_hte").first()
            result = apply_material_lot_correction(
                app_module,
                derivative_lot,
                correction_kind="adjust_quantity",
                reason="Correct dry HTE weight after recount.",
                new_quantity=8.5,
            )
            db.session.commit()

            replacement = result["replacement_lot"]
            db.session.refresh(derivative_lot)
            assert derivative_lot.correction_state == "replaced"
            assert derivative_lot.inventory_status == "closed"
            assert replacement is not None
            assert replacement.quantity == 8.5
            assert replacement.origin_confidence == "corrected"

            correction = MaterialTransformation.query.filter_by(
                run_id=run.id,
                transformation_type="correction_quantity_adjustment",
                source_record_id=derivative_lot.id,
            ).first()
            assert correction is not None
            assert correction.outputs.count() == 1
        finally:
            db.session.rollback()
            MaterialReconciliationIssue.query.filter_by(run_id=run_id).delete()
            MaterialTransformation.query.filter_by(run_id=run_id).delete()
            run = db.session.get(Run, run_id)
            for output in run.material_lots.all() if run is not None else []:
                db.session.delete(output)
            lot = db.session.get(PurchaseLot, lot_id)
            if lot is not None and lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            if run is not None:
                db.session.delete(run)
            if lot is not None:
                db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_ensure_downstream_output_genealogy_creates_golddrop_and_wholesale_thca_lots():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Downstream Genealogy Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Mimosa",
            weight_lbs=120,
            remaining_weight_lbs=80,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=6,
            bio_in_reactor_lbs=40,
            dry_hte_g=18,
            dry_thca_g=25,
            cost_per_gram_hte=3.0,
            cost_per_gram_thca=4.0,
            thca_destination="sell_thca",
        )
        db.session.add_all([lot, run])
        db.session.flush()
        run_id = run.id
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.add(
            DownstreamQueueEvent(
                run_id=run.id,
                queue_key="golddrop_queue",
                action_key="release_complete",
            )
        )
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            ensure_extraction_output_genealogy(app_module, run)
            ensure_downstream_output_genealogy(app_module, run)
            db.session.commit()

            lot_types = {item.lot_type for item in derivative_material_lots_for_run(app_module, run)}
            assert {"dry_hte", "dry_thca", "golddrop", "wholesale_thca"} <= lot_types

            dry_hte = run.material_lots.filter_by(lot_type="dry_hte").first()
            with app.test_request_context("/"):
                descendants = build_material_lot_descendants_payload(app_module, dry_hte)
            assert descendants["descendants"][0]["transformation"]["transformation_type"] == "golddrop_production"
            assert descendants["descendants"][0]["outputs"][0]["material_lot"]["lot_type"] == "golddrop"
        finally:
            db.session.rollback()
            MaterialReconciliationIssue.query.filter_by(run_id=run_id).delete()
            DownstreamQueueEvent.query.filter_by(run_id=run_id).delete()
            MaterialTransformation.query.filter_by(run_id=run_id).delete()
            run = db.session.get(Run, run_id)
            for output in run.material_lots.all() if run is not None else []:
                db.session.delete(output)
            if lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            db.session.delete(run)
            db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_ensure_downstream_output_genealogy_creates_terp_strip_output_lot():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Terp Genealogy Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Papaya Kush",
            weight_lbs=110,
            remaining_weight_lbs=70,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        run = Run(
            run_date=date.today(),
            reactor_number=7,
            bio_in_reactor_lbs=40,
            dry_hte_g=20,
            hte_terpenes_recovered_g=6,
        )
        db.session.add_all([lot, run])
        db.session.flush()
        db.session.add(RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=40))
        db.session.add(
            DownstreamQueueEvent(
                run_id=run.id,
                queue_key="terp_strip_cage",
                action_key="strip_complete",
            )
        )
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, lot.id))
            ensure_extraction_output_genealogy(app_module, run)
            ensure_downstream_output_genealogy(app_module, run)
            db.session.commit()

            output_lot = run.material_lots.filter_by(lot_type="terp_strip_output").first()
            assert output_lot is not None
            assert output_lot.quantity == 6.0
            dry_hte = run.material_lots.filter_by(lot_type="dry_hte").first()
            assert dry_hte is not None
            assert dry_hte.inventory_status == "partially_consumed"
        finally:
            MaterialReconciliationIssue.query.filter_by(run_id=run.id).delete()
            DownstreamQueueEvent.query.filter_by(run_id=run.id).delete()
            MaterialTransformation.query.filter_by(run_id=run.id).delete()
            for output in run.material_lots.all():
                db.session.delete(output)
            if lot.material_lot_id:
                material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                if material_lot is not None:
                    db.session.delete(material_lot)
            db.session.delete(run)
            db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()


def test_ensure_downstream_output_genealogy_creates_hp_base_oil_and_distillate_lots():
    app = app_module.app
    with app.app_context():
        supplier = Supplier(name=f"Conversion Supplier {app_module.gen_uuid()[:6]}", is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = _approved_purchase(supplier.id)
        db.session.add(purchase)
        db.session.flush()
        hp_lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Conversion Dream",
            weight_lbs=100,
            remaining_weight_lbs=60,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        dist_lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Conversion Dream",
            weight_lbs=100,
            remaining_weight_lbs=60,
            tracking_id=f"LOT-{app_module.gen_uuid()[:8].upper()}",
        )
        hp_run = Run(
            run_date=date.today(),
            reactor_number=8,
            bio_in_reactor_lbs=40,
            dry_hte_g=14,
        )
        dist_run = Run(
            run_date=date.today(),
            reactor_number=9,
            bio_in_reactor_lbs=40,
            dry_hte_g=16,
            hte_distillate_retail_g=9,
        )
        db.session.add_all([hp_lot, dist_lot, hp_run, dist_run])
        db.session.flush()
        hp_run_id = hp_run.id
        dist_run_id = dist_run.id
        hp_lot_id = hp_lot.id
        dist_lot_id = dist_lot.id
        db.session.add_all(
            [
                RunInput(run_id=hp_run.id, lot_id=hp_lot.id, weight_lbs=40),
                RunInput(run_id=dist_run.id, lot_id=dist_lot.id, weight_lbs=40),
                DownstreamQueueEvent(run_id=hp_run.id, queue_key="hold_hp_base_oil", action_key="release_complete"),
                DownstreamQueueEvent(run_id=dist_run.id, queue_key="hold_distillate", action_key="release_complete"),
            ]
        )
        db.session.commit()

        try:
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, hp_lot.id))
            ensure_biomass_material_lot(app_module, db.session.get(PurchaseLot, dist_lot.id))
            ensure_extraction_output_genealogy(app_module, hp_run)
            ensure_extraction_output_genealogy(app_module, dist_run)
            ensure_downstream_output_genealogy(app_module, hp_run)
            ensure_downstream_output_genealogy(app_module, dist_run)
            db.session.commit()

            hp_output = hp_run.material_lots.filter_by(lot_type="hp_base_oil").first()
            dist_output = dist_run.material_lots.filter_by(lot_type="distillate").first()
            assert hp_output is not None
            assert hp_output.quantity == 14.0
            assert dist_output is not None
            assert dist_output.quantity == 9.0
        finally:
            db.session.rollback()
            for run_id in (hp_run_id, dist_run_id):
                run = db.session.get(Run, run_id)
                MaterialReconciliationIssue.query.filter_by(run_id=run_id).delete()
                DownstreamQueueEvent.query.filter_by(run_id=run_id).delete()
                MaterialTransformation.query.filter_by(run_id=run_id).delete()
                for output in run.material_lots.all() if run is not None else []:
                    db.session.delete(output)
                if run is not None:
                    db.session.delete(run)
            for lot_id in (hp_lot_id, dist_lot_id):
                lot = db.session.get(PurchaseLot, lot_id)
                if lot is not None and lot.material_lot_id:
                    material_lot = db.session.get(MaterialLot, lot.material_lot_id)
                    if material_lot is not None:
                        db.session.delete(material_lot)
                if lot is not None:
                    db.session.delete(lot)
            db.session.delete(purchase)
            db.session.delete(supplier)
            db.session.commit()
