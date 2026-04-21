from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from services.lot_allocation import ensure_lot_tracking_fields


def ensure_sqlite_schema(root) -> None:
    if root.db.engine.dialect.name != "sqlite":
        return

    def has_table(table_name: str) -> bool:
        row = root.db.session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:table"
            ),
            {"table": table_name},
        ).first()
        return row is not None

    def column_names(table_name: str) -> set[str]:
        rows = root.db.session.execute(text(f"PRAGMA table_info({table_name})")).all()
        return {r[1] for r in rows}

    if has_table("purchases"):
        cols = column_names("purchases")
        if "batch_id" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN batch_id VARCHAR(80)"))
        if "created_by_user_id" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN created_by_user_id VARCHAR(36)"))
        if "delivery_recorded_by_user_id" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN delivery_recorded_by_user_id VARCHAR(36)"))
        if "storage_note" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN storage_note TEXT"))
        if "license_info" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN license_info TEXT"))
        if "queue_placement" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN queue_placement VARCHAR(20)"))
        if "coa_status_text" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN coa_status_text TEXT"))
        if "testing_notes" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN testing_notes TEXT"))
        if "delivery_notes" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN delivery_notes TEXT"))
        if "deleted_at" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN deleted_by VARCHAR(36)"))
        if "purchase_approved_at" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN purchase_approved_at DATETIME"))
        if "purchase_approved_by_user_id" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN purchase_approved_by_user_id VARCHAR(36)"))
        if "availability_date" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN availability_date DATE"))
        if "declared_weight_lbs" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN declared_weight_lbs FLOAT"))
        if "declared_price_per_lb" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN declared_price_per_lb FLOAT"))
        if "testing_timing" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN testing_timing VARCHAR(20)"))
        if "testing_status" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN testing_status VARCHAR(20)"))
        if "testing_date" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN testing_date DATE"))
        if "field_photo_paths_json" not in cols:
            root.db.session.execute(text("ALTER TABLE purchases ADD COLUMN field_photo_paths_json TEXT"))

    if has_table("biomass_availabilities"):
        cols = column_names("biomass_availabilities")
        if "purchase_id" not in cols:
            root.db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN purchase_id VARCHAR(36)"))
        if "field_photo_paths_json" not in cols:
            root.db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN field_photo_paths_json TEXT"))
        if "purchase_approved_at" not in cols:
            root.db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN purchase_approved_at DATETIME"))
        if "purchase_approved_by_user_id" not in cols:
            root.db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN purchase_approved_by_user_id VARCHAR(36)"))
        if "deleted_at" not in cols:
            root.db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN deleted_at DATETIME"))

    if has_table("users"):
        cols = column_names("users")
        if "is_slack_importer" not in cols:
            root.db.session.execute(text("ALTER TABLE users ADD COLUMN is_slack_importer BOOLEAN DEFAULT 0"))
        if "is_purchase_approver" not in cols:
            root.db.session.execute(text("ALTER TABLE users ADD COLUMN is_purchase_approver BOOLEAN DEFAULT 0"))

    if has_table("suppliers"):
        cols = column_names("suppliers")
        if "merged_into_supplier_id" not in cols:
            root.db.session.execute(text("ALTER TABLE suppliers ADD COLUMN merged_into_supplier_id VARCHAR(36)"))
        if "merged_at" not in cols:
            root.db.session.execute(text("ALTER TABLE suppliers ADD COLUMN merged_at DATETIME"))
        if "merged_by_user_id" not in cols:
            root.db.session.execute(text("ALTER TABLE suppliers ADD COLUMN merged_by_user_id VARCHAR(36)"))
        if "merge_notes" not in cols:
            root.db.session.execute(text("ALTER TABLE suppliers ADD COLUMN merge_notes TEXT"))

    if has_table("api_clients"):
        cols = column_names("api_clients")
        if "last_used_scope" not in cols:
            root.db.session.execute(text("ALTER TABLE api_clients ADD COLUMN last_used_scope VARCHAR(64)"))
        if "last_used_endpoint" not in cols:
            root.db.session.execute(text("ALTER TABLE api_clients ADD COLUMN last_used_endpoint VARCHAR(255)"))

    if not has_table("api_client_request_logs"):
        root.db.session.execute(text(
            "CREATE TABLE api_client_request_logs ("
            "id VARCHAR(36) PRIMARY KEY, "
            "api_client_id VARCHAR(36) NOT NULL, "
            "request_path VARCHAR(255) NOT NULL, "
            "request_method VARCHAR(16) NOT NULL DEFAULT 'GET', "
            "scope_used VARCHAR(64) NOT NULL, "
            "status_code INTEGER, "
            "created_at DATETIME NOT NULL"
            ")"
        ))

    if has_table("remote_sites"):
        cols = column_names("remote_sites")
        if "last_suppliers_payload_json" not in cols:
            try:
                root.db.session.execute(text("ALTER TABLE remote_sites ADD COLUMN last_suppliers_payload_json TEXT"))
            except OperationalError as exc:
                if "duplicate column name" not in str(getattr(exc, "orig", exc)).lower():
                    raise
        if "last_strains_payload_json" not in cols:
            try:
                root.db.session.execute(text("ALTER TABLE remote_sites ADD COLUMN last_strains_payload_json TEXT"))
            except OperationalError as exc:
                if "duplicate column name" not in str(getattr(exc, "orig", exc)).lower():
                    raise

    if has_table("remote_site_pulls"):
        cols = column_names("remote_site_pulls")
        if "suppliers_payload_json" not in cols:
            try:
                root.db.session.execute(text("ALTER TABLE remote_site_pulls ADD COLUMN suppliers_payload_json TEXT"))
            except OperationalError as exc:
                if "duplicate column name" not in str(getattr(exc, "orig", exc)).lower():
                    raise
        if "strains_payload_json" not in cols:
            try:
                root.db.session.execute(text("ALTER TABLE remote_site_pulls ADD COLUMN strains_payload_json TEXT"))
            except OperationalError as exc:
                if "duplicate column name" not in str(getattr(exc, "orig", exc)).lower():
                    raise

    if has_table("runs"):
        cols = column_names("runs")
        if "cost_per_gram_thca" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_thca FLOAT"))
        if "cost_per_gram_hte" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_hte FLOAT"))
        if "deleted_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN deleted_by VARCHAR(36)"))
        if "load_source_reactors" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN load_source_reactors VARCHAR(120)"))
        if "slack_channel_id" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN slack_channel_id VARCHAR(32)"))
        if "slack_message_ts" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN slack_message_ts VARCHAR(32)"))
        if "slack_import_applied_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN slack_import_applied_at DATETIME"))
        if "hte_pipeline_stage" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN hte_pipeline_stage VARCHAR(40)"))
        if "hte_lab_result_paths_json" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN hte_lab_result_paths_json TEXT"))
        if "hte_terpenes_recovered_g" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN hte_terpenes_recovered_g FLOAT"))
        if "hte_distillate_retail_g" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN hte_distillate_retail_g FLOAT"))
        if "run_fill_started_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN run_fill_started_at DATETIME"))
        if "run_fill_ended_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN run_fill_ended_at DATETIME"))
        if "biomass_blend_milled_pct" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN biomass_blend_milled_pct FLOAT"))
        if "biomass_blend_unmilled_pct" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN biomass_blend_unmilled_pct FLOAT"))
        if "flush_count" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN flush_count INTEGER"))
        if "flush_total_weight_lbs" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN flush_total_weight_lbs FLOAT"))
        if "fill_count" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN fill_count INTEGER"))
        if "fill_total_weight_lbs" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN fill_total_weight_lbs FLOAT"))
        if "stringer_basket_count" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN stringer_basket_count INTEGER"))
        if "crc_blend" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN crc_blend VARCHAR(200)"))
        if "mixer_started_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN mixer_started_at DATETIME"))
        if "mixer_ended_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN mixer_ended_at DATETIME"))
        if "flush_started_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN flush_started_at DATETIME"))
        if "flush_ended_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN flush_ended_at DATETIME"))
        if "run_completed_at" not in cols:
            root.db.session.execute(text("ALTER TABLE runs ADD COLUMN run_completed_at DATETIME"))

    if has_table("purchase_lots"):
        cols = column_names("purchase_lots")
        if "tracking_id" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN tracking_id VARCHAR(24)"))
        if "barcode_value" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN barcode_value VARCHAR(120)"))
        if "qr_value" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN qr_value VARCHAR(255)"))
        if "label_generated_at" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN label_generated_at DATETIME"))
        if "label_version" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN label_version INTEGER"))
        if "floor_state" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN floor_state VARCHAR(40)"))
        if "deleted_at" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            root.db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN deleted_by VARCHAR(36)"))

    if not has_table("lot_scan_events"):
        root.db.session.execute(text(
            "CREATE TABLE lot_scan_events ("
            "id VARCHAR(36) PRIMARY KEY, "
            "lot_id VARCHAR(36) NOT NULL, "
            "tracking_id_snapshot VARCHAR(24) NOT NULL, "
            "action VARCHAR(40) NOT NULL DEFAULT 'scan_open', "
            "context_json TEXT, "
            "user_id VARCHAR(36), "
            "created_at DATETIME NOT NULL"
            ")"
        ))

    if has_table("run_inputs"):
        cols = column_names("run_inputs")
        if "allocation_source" not in cols:
            root.db.session.execute(text("ALTER TABLE run_inputs ADD COLUMN allocation_source VARCHAR(20)"))
        if "allocation_confidence" not in cols:
            root.db.session.execute(text("ALTER TABLE run_inputs ADD COLUMN allocation_confidence FLOAT"))
        if "allocation_notes" not in cols:
            root.db.session.execute(text("ALTER TABLE run_inputs ADD COLUMN allocation_notes TEXT"))
        if "slack_ingested_message_id" not in cols:
            root.db.session.execute(text("ALTER TABLE run_inputs ADD COLUMN slack_ingested_message_id VARCHAR(36)"))

    if has_table("field_purchase_submissions"):
        cols = column_names("field_purchase_submissions")
        if "photos_json" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN photos_json TEXT"))
        if "harvest_date" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN harvest_date DATE"))
        if "storage_note" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN storage_note TEXT"))
        if "license_info" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN license_info TEXT"))
        if "queue_placement" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN queue_placement VARCHAR(20)"))
        if "coa_status_text" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN coa_status_text TEXT"))
        if "supplier_photos_json" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN supplier_photos_json TEXT"))
        if "biomass_photos_json" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN biomass_photos_json TEXT"))
        if "coa_photos_json" not in cols:
            root.db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN coa_photos_json TEXT"))

    if not has_table("lab_tests"):
        root.db.session.execute(text(
            "CREATE TABLE lab_tests ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36) NOT NULL, "
            "purchase_id VARCHAR(36), "
            "test_date DATE NOT NULL, "
            "test_type VARCHAR(50) NOT NULL, "
            "status_text TEXT, "
            "potency_pct FLOAT, "
            "notes TEXT, "
            "result_paths_json TEXT, "
            "created_at DATETIME, "
            "created_by VARCHAR(36)"
            ")"
        ))
    if not has_table("supplier_attachments"):
        root.db.session.execute(text(
            "CREATE TABLE supplier_attachments ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36) NOT NULL, "
            "document_type VARCHAR(50) NOT NULL, "
            "title VARCHAR(200), "
            "file_path VARCHAR(500) NOT NULL, "
            "uploaded_at DATETIME, "
            "uploaded_by VARCHAR(36)"
            ")"
        ))
    if not has_table("photo_assets"):
        root.db.session.execute(text(
            "CREATE TABLE photo_assets ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36), "
            "purchase_id VARCHAR(36), "
            "submission_id VARCHAR(36), "
            "photo_context VARCHAR(32), "
            "source_type VARCHAR(50) NOT NULL, "
            "category VARCHAR(50) NOT NULL, "
            "title VARCHAR(200), "
            "tags VARCHAR(500), "
            "file_path VARCHAR(500) NOT NULL, "
            "uploaded_at DATETIME, "
            "uploaded_by VARCHAR(36)"
            ")"
        ))
    if has_table("photo_assets"):
        cols = column_names("photo_assets")
        if "photo_context" not in cols:
            root.db.session.execute(text("ALTER TABLE photo_assets ADD COLUMN photo_context VARCHAR(32)"))
    if not has_table("slack_ingested_messages"):
        root.db.session.execute(text(
            "CREATE TABLE slack_ingested_messages ("
            "id VARCHAR(36) PRIMARY KEY, "
            "channel_id VARCHAR(32) NOT NULL, "
            "message_ts VARCHAR(32) NOT NULL, "
            "slack_user_id VARCHAR(32), "
            "raw_text TEXT, "
            "message_kind VARCHAR(40), "
            "derived_json TEXT, "
            "ingested_at DATETIME, "
            "ingested_by VARCHAR(36), "
            "hidden_from_imports BOOLEAN NOT NULL DEFAULT 0, "
            "UNIQUE(channel_id, message_ts)"
            ")"
        ))
    if has_table("slack_ingested_messages"):
        cols = column_names("slack_ingested_messages")
        if "hidden_from_imports" not in cols:
            root.db.session.execute(text(
                "ALTER TABLE slack_ingested_messages ADD COLUMN hidden_from_imports BOOLEAN NOT NULL DEFAULT 0"
            ))
    if not has_table("slack_channel_sync_configs"):
        root.db.session.execute(text(
            "CREATE TABLE slack_channel_sync_configs ("
            "id VARCHAR(36) PRIMARY KEY, "
            "slot_index INTEGER NOT NULL, "
            "channel_hint VARCHAR(200) NOT NULL DEFAULT '', "
            "resolved_channel_id VARCHAR(32), "
            "last_watermark_ts VARCHAR(32), "
            "UNIQUE(slot_index)"
            ")"
        ))

    root.db.session.commit()


def ensure_postgres_run_hte_columns(root) -> None:
    if root.db.engine.dialect.name != "postgresql":
        return
    for stmt in (
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS hte_pipeline_stage VARCHAR(40)",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS hte_lab_result_paths_json TEXT",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS hte_terpenes_recovered_g DOUBLE PRECISION",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS hte_distillate_retail_g DOUBLE PRECISION",
    ):
        root.db.session.execute(text(stmt))
    root.db.session.commit()


def ensure_postgres_run_execution_columns(root) -> None:
    if root.db.engine.dialect.name != "postgresql":
        return
    for stmt in (
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_fill_started_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_fill_ended_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS biomass_blend_milled_pct DOUBLE PRECISION",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS biomass_blend_unmilled_pct DOUBLE PRECISION",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS flush_count INTEGER",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS flush_total_weight_lbs DOUBLE PRECISION",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS fill_count INTEGER",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS fill_total_weight_lbs DOUBLE PRECISION",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS stringer_basket_count INTEGER",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS crc_blend VARCHAR(200)",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS mixer_started_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS mixer_ended_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS flush_started_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS flush_ended_at TIMESTAMP",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_completed_at TIMESTAMP",
    ):
        root.db.session.execute(text(stmt))
    root.db.session.commit()


def ensure_postgres_slack_ingested_columns(root) -> None:
    if root.db.engine.dialect.name != "postgresql":
        return
    root.db.session.execute(text(
        "ALTER TABLE slack_ingested_messages ADD COLUMN IF NOT EXISTS hidden_from_imports BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    root.db.session.commit()


def ensure_postgres_mobile_columns(root) -> None:
    if root.db.engine.dialect.name != "postgresql":
        return
    for stmt in (
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36)",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS delivery_recorded_by_user_id VARCHAR(36)",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS testing_notes TEXT",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS delivery_notes TEXT",
        "ALTER TABLE photo_assets ADD COLUMN IF NOT EXISTS photo_context VARCHAR(32)",
    ):
        root.db.session.execute(text(stmt))
    root.db.session.commit()


def maintain_purchase_inventory_lots(root, purchase) -> None:
    if not purchase or purchase.deleted_at is not None:
        return
    active_lots = (
        root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
        .filter(root.PurchaseLot.deleted_at.is_(None))
        .all()
    )
    for lot in active_lots:
        ensure_lot_tracking_fields(lot)
    weight = (
        float(purchase.actual_weight_lbs)
        if purchase.actual_weight_lbs is not None
        else float(purchase.stated_weight_lbs or 0)
    )
    is_on_hand = (
        purchase.deleted_at is None
        and purchase.status in root.INVENTORY_ON_HAND_PURCHASE_STATUSES
        and purchase.purchase_approved_at is not None
    )
    if not is_on_hand or weight <= 0:
        for lot in active_lots:
            lot.remaining_weight_lbs = 0.0
        return
    if not active_lots:
        lot = root.PurchaseLot(
            purchase_id=purchase.id,
            strain_name="Purchase total",
            weight_lbs=weight,
            remaining_weight_lbs=weight,
            potency_pct=purchase.tested_potency_pct or purchase.stated_potency_pct,
        )
        ensure_lot_tracking_fields(lot)
        root.db.session.add(lot)
        return
    if len(active_lots) == 1 and (active_lots[0].strain_name or "") == "Purchase total":
        lot = active_lots[0]
        consumed = max(0.0, float(lot.weight_lbs or 0) - float(lot.remaining_weight_lbs or 0))
        lot.weight_lbs = weight
        lot.remaining_weight_lbs = max(0.0, weight - consumed)
        lot.potency_pct = purchase.tested_potency_pct or purchase.stated_potency_pct


def reconcile_closed_purchase_inventory_lots(root) -> None:
    try:
        purchases = root.Purchase.query.filter(root.Purchase.deleted_at.is_(None)).all()
        touched = False
        for purchase in purchases:
            before = [
                (lot.id, float(lot.remaining_weight_lbs or 0), float(lot.weight_lbs or 0))
                for lot in root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
                .filter(root.PurchaseLot.deleted_at.is_(None))
                .all()
            ]
            maintain_purchase_inventory_lots(root, purchase)
            after = [
                (lot.id, float(lot.remaining_weight_lbs or 0), float(lot.weight_lbs or 0))
                for lot in root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
                .filter(root.PurchaseLot.deleted_at.is_(None))
                .all()
            ]
            if before != after:
                touched = True
        if touched:
            root.db.session.commit()
    except Exception:
        root.db.session.rollback()


def backfill_default_inventory_lots(root) -> None:
    try:
        purchases = root.Purchase.query.filter(
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
            root.Purchase.purchase_approved_at.isnot(None),
        ).all()
        touched = False
        for purchase in purchases:
            before_count = (
                root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
                .filter(root.PurchaseLot.deleted_at.is_(None))
                .count()
            )
            maintain_purchase_inventory_lots(root, purchase)
            after_count = (
                root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
                .filter(root.PurchaseLot.deleted_at.is_(None))
                .count()
            )
            if after_count != before_count:
                touched = True
        if touched:
            root.db.session.commit()
    except Exception:
        root.db.session.rollback()


def backfill_purchase_approval(root) -> None:
    try:
        unapproved_on_hand = root.Purchase.query.filter(
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
            root.Purchase.purchase_approved_at.is_(None),
        ).all()
        if unapproved_on_hand:
            now = datetime.now(timezone.utc)
            for purchase in unapproved_on_hand:
                purchase.purchase_approved_at = now
            root.db.session.commit()
    except Exception:
        root.db.session.rollback()


def migrate_biomass_to_purchase(root) -> None:
    try:
        if not hasattr(root.BiomassAvailability, "__table__"):
            return
        try:
            root.BiomassAvailability.query.limit(1).all()
        except Exception:
            return

        stage_to_status = {
            "declared": "declared",
            "testing": "in_testing",
            "committed": "committed",
            "delivered": "delivered",
            "cancelled": "cancelled",
        }
        migrated = False

        for biomass in root.BiomassAvailability.query.all():
            if biomass.purchase_id:
                purchase = root.db.session.get(root.Purchase, biomass.purchase_id)
                if not purchase or purchase.availability_date is not None:
                    continue
                purchase.availability_date = biomass.availability_date
                purchase.declared_weight_lbs = biomass.declared_weight_lbs
                purchase.declared_price_per_lb = biomass.declared_price_per_lb
                purchase.testing_timing = biomass.testing_timing
                purchase.testing_status = biomass.testing_status
                purchase.testing_date = biomass.testing_date
                purchase.field_photo_paths_json = biomass.field_photo_paths_json
                if not purchase.stated_potency_pct and biomass.estimated_potency_pct:
                    purchase.stated_potency_pct = biomass.estimated_potency_pct
                if not purchase.purchase_approved_at and biomass.purchase_approved_at:
                    purchase.purchase_approved_at = biomass.purchase_approved_at
                    purchase.purchase_approved_by_user_id = biomass.purchase_approved_by_user_id
                if biomass.strain_name:
                    existing_lot = (
                        root.PurchaseLot.query.filter_by(purchase_id=purchase.id)
                        .filter(root.PurchaseLot.deleted_at.is_(None))
                        .first()
                    )
                    if not existing_lot:
                        weight = (
                            float(purchase.actual_weight_lbs)
                            if purchase.actual_weight_lbs is not None
                            else float(purchase.stated_weight_lbs or 0)
                        )
                        if weight > 0:
                            root.db.session.add(root.PurchaseLot(
                                purchase_id=purchase.id,
                                strain_name=biomass.strain_name,
                                weight_lbs=weight,
                                remaining_weight_lbs=weight,
                                potency_pct=purchase.tested_potency_pct or purchase.stated_potency_pct,
                            ))
                migrated = True
                continue

            if not biomass.supplier_id:
                continue
            availability_date = biomass.availability_date or date.today()
            purchase = root.Purchase(
                supplier_id=biomass.supplier_id,
                availability_date=availability_date,
                purchase_date=availability_date,
                status=stage_to_status.get((biomass.stage or "").strip(), "declared"),
                declared_weight_lbs=biomass.declared_weight_lbs,
                stated_weight_lbs=biomass.declared_weight_lbs or 0,
                declared_price_per_lb=biomass.declared_price_per_lb,
                stated_potency_pct=biomass.estimated_potency_pct,
                testing_timing=biomass.testing_timing,
                testing_status=biomass.testing_status,
                testing_date=biomass.testing_date,
                field_photo_paths_json=biomass.field_photo_paths_json,
                notes=biomass.notes,
                purchase_approved_at=biomass.purchase_approved_at,
                purchase_approved_by_user_id=biomass.purchase_approved_by_user_id,
            )
            root.db.session.add(purchase)
            root.db.session.flush()
            supplier = root.db.session.get(root.Supplier, biomass.supplier_id)
            supplier_name = supplier.name if supplier else "BATCH"
            batch_weight = (
                float(purchase.actual_weight_lbs)
                if purchase.actual_weight_lbs is not None
                else float(purchase.stated_weight_lbs or 0)
            )
            purchase.batch_id = root._ensure_unique_batch_id(
                root._generate_batch_id(supplier_name, availability_date, batch_weight),
                exclude_purchase_id=purchase.id,
            )
            if biomass.strain_name and batch_weight > 0:
                root.db.session.add(root.PurchaseLot(
                    purchase_id=purchase.id,
                    strain_name=biomass.strain_name,
                    weight_lbs=batch_weight,
                    remaining_weight_lbs=batch_weight,
                    potency_pct=purchase.tested_potency_pct or purchase.stated_potency_pct,
                ))
            migrated = True

        if migrated:
            root.db.session.commit()
    except Exception:
        root.db.session.rollback()
