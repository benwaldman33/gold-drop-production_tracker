"""Gold Drop Biomass Inventory & Extraction Tracking System."""
from __future__ import annotations

import os
import csv
import io
import json
import sys
import tempfile
import re
import hashlib
import hmac
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import gold_drop.biomass_module as biomass_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.purchases_module as purchases_module
import gold_drop.dashboard_module as dashboard_module
import gold_drop.floor_module as floor_module
import gold_drop.field_intake_module as field_intake_module
import gold_drop.costs_module as costs_module
import gold_drop.inventory_module as inventory_module
import gold_drop.batch_edit_module as batch_edit_module
import gold_drop.mobile_module as mobile_module
import gold_drop.purchase_import_module as purchase_import_module
import gold_drop.suppliers_module as suppliers_module
import gold_drop.runs_module as runs_module
import gold_drop.settings_module as settings_module
import gold_drop.slack_integration_module as slack_integration_module
import gold_drop.api_v1_module as api_v1_module
import gold_drop.strains_module as strains_module
from datetime import datetime, date, timedelta, timezone
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, flash,
                   jsonify, Response, session, abort)
from flask_login import (login_user, logout_user, login_required,
                         current_user)
from sqlalchemy import func, desc, and_, or_, text, select, exists
from werkzeug.utils import secure_filename

from models import (db, User, Supplier, Purchase, PurchaseLot, Run, RunInput, ExtractionCharge, ExtractionBoothSession, ExtractionBoothEvent, ExtractionBoothEvidence, SupervisorNotification, NotificationDelivery, DownstreamQueueEvent, MaterialLot, MaterialTransformation, MaterialTransformationInput, MaterialTransformationOutput, MaterialReconciliationIssue,
                    KpiTarget, SystemSetting, AuditLog, BiomassAvailability, CostEntry,
                    FieldAccessToken, FieldPurchaseSubmission, LabTest, SupplierAttachment, PhotoAsset,
                    SlackIngestedMessage, SlackChannelSyncConfig, LotScanEvent, ScaleDevice, WeightCapture, gen_uuid)
from purchase_import import (
    PURCHASE_IMPORT_FIELDS,
    parse_purchase_spreadsheet_upload,
    parse_purchase_spreadsheet_upload_for_mapping,
    purchase_import_field_choices,
    purchase_import_rows_from_mapping,
)
from blueprints import register_blueprints
from policies.purchase_status import (
    require_approval_for_on_hand_status,
    validate_delivered_requires_prior_commitment,
    validate_pipeline_commitment_transition,
)
from services.purchases import stamp_purchase_approval
from batch_edit import (
    STRAIN_PAIR_SEP,
    apply_batch_runs,
    apply_batch_purchases,
    apply_batch_biomass,
    apply_batch_suppliers,
    apply_batch_costs,
    apply_batch_inventory_lots,
    apply_batch_strain_rename,
    parse_uuid_ids,
)
from gold_drop.audit import log_audit
from gold_drop.auth import (
    admin_required,
    editor_required,
    field_purchase_approval_required,
    init_app as init_auth,
    purchase_editor_required,
    slack_importer_required,
)
from gold_drop.list_state import (
    APP_DISPLAY_TIMEZONE_CHOICES,
    APP_DISPLAY_TIMEZONE_DEFAULT,
    LIST_FILTERS_SESSION_KEY,
    app_display_timezone_name as _app_display_timezone_name,
    app_display_zoneinfo as _app_display_zoneinfo,
    list_filters_clear_redirect as _list_filters_clear_redirect,
    list_filters_merge as _list_filters_merge,
    runs_list_filters_active as _runs_list_filters_active,
    slack_channel_filter_label as _slack_channel_filter_label,
    slack_resolved_channel_hint_map as _slack_resolved_channel_hint_map,
)
from gold_drop.purchases import (
    INVENTORY_ON_HAND_PURCHASE_STATUSES,
    biomass_budget_snapshot_for_purchase as _biomass_budget_snapshot_for_purchase,
    budget_week_purchase_metrics as _budget_week_purchase_metrics,
    enforce_weekly_biomass_purchase_limits as _enforce_weekly_biomass_purchase_limits,
    purchase_biomass_budget_lbs as _purchase_biomass_budget_lbs,
    purchase_biomass_budget_potency as _purchase_biomass_budget_potency,
    purchase_budget_spend as _purchase_budget_spend,
    purchase_counts_toward_biomass_budget as _purchase_counts_toward_biomass_budget,
    purchase_week_start as _purchase_week_start,
)
from gold_drop.uploads import (
    json_paths as _json_paths,
    save_lab_files as _save_lab_files,
)
from services.slack_workflow import (
    slack_apply_form_passthrough,
    slack_build_supplier_candidate,
    slack_selected_canonical_strain,
    slack_strain_candidates_for_name,
    slack_strain_mapping_needs_fuzzy_confirm,
    slack_supplier_candidates_for_source,
    slack_supplier_exact_name_match,
    slack_supplier_mapping_needs_fuzzy_confirm,
    slack_resolution_from_apply_form,
    slack_resolution_create_declared_biomass as _slack_resolution_create_declared_biomass,
    slack_resolution_materialize_supplier as _slack_resolution_materialize_supplier,
    slack_run_prefill_put,
)
from services.bootstrap_helpers import (
    backfill_biomass_material_genealogy as _backfill_biomass_material_genealogy_service,
    backfill_default_inventory_lots as _backfill_default_inventory_lots_service,
    backfill_purchase_approval as _backfill_purchase_approval_service,
    ensure_postgres_run_execution_columns as _ensure_postgres_run_execution_columns_service,
    ensure_postgres_run_hte_columns as _ensure_postgres_run_hte_columns_service,
    ensure_postgres_slack_ingested_columns as _ensure_postgres_slack_ingested_columns_service,
    ensure_sqlite_schema as _ensure_sqlite_schema_service,
    maintain_purchase_inventory_lots as _maintain_purchase_inventory_lots_service,
    migrate_biomass_to_purchase as _migrate_biomass_to_purchase_service,
    reconcile_closed_purchase_inventory_lots as _reconcile_closed_purchase_inventory_lots_service,
)
from services.material_genealogy import (
    first_open_reconciliation_issues as _first_open_reconciliation_issues,
    material_lot_for_purchase_lot as _material_lot_for_purchase_lot,
    reconcile_run_material_genealogy as _reconcile_run_material_genealogy,
    source_material_lots_for_run as _source_material_lots_for_run,
)
from services.extraction_run import (
    HTE_CLEAN_DECISION_OPTIONS,
    HTE_FILTER_OUTCOME_OPTIONS,
    HTE_POTENCY_DISPOSITION_OPTIONS,
    HTE_QUEUE_DESTINATION_OPTIONS,
    POST_EXTRACTION_PATHWAY_OPTIONS,
    THCA_DESTINATION_OPTIONS,
    booth_session_payload,
    display_local_datetime,
    display_local_timestamp,
    downstream_state_payload,
    duration_minutes,
    post_extraction_progression_payload,
    run_progression_payload,
    run_timing_controls_payload,
)
from services.supervisor_notifications import (
    manager_can_review,
    notification_rows_for_run,
    summarize_notifications,
)
from gold_drop.slack import (
    SLACK_IMPORT_KIND_FILTER_CHOICES,
    SLACK_IMPORT_TEXT_FILTER_OPS,
    SLACK_IMPORT_TEXT_OPS_ALLOWED,
    SLACK_RUN_MAPPINGS_KEY,
    _apply_slack_mapping_transform,
    _default_slack_run_field_rules,
    _derive_slack_production_message,
    _preview_slack_to_run_fields,
    _slack_coverage_label,
    _slack_default_availability_date_iso,
    _slack_default_bio_weight_lbs,
    _ensure_slack_message_date_derived,
    _slack_imports_row_matches_kind_text,
    _load_slack_run_field_rules,
    _slack_intake_manifest_normalized,
    _slack_message_needs_resolution_ui,
    _slack_mapping_transform_from_form,
    _slack_non_run_mapping_rule_count,
    _slack_parse_mdy_date,
    _slack_rule_kind_select_value,
    _slack_run_rules_from_mapping_form,
    _slack_run_mappings_template_kwargs,
    _slack_strip_slack_links,
    _slack_ts_to_date_value,
    _slack_ts_to_display_datetime_str,
    _validate_slack_run_field_rules,
)

def create_app():
    flask_app = Flask(__name__)
    flask_app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gold-drop-dev-key-change-in-prod")
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///golddrop.db")
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    flask_app.config["FIELD_UPLOAD_DIR"] = os.path.join(flask_app.root_path, "static", "uploads", "field")
    flask_app.config["FIELD_UPLOAD_MAX_BYTES"] = 50 * 1024 * 1024
    flask_app.config["LAB_UPLOAD_DIR"] = os.path.join(flask_app.root_path, "static", "uploads", "labs")
    flask_app.config["LAB_UPLOAD_MAX_BYTES"] = 50 * 1024 * 1024
    flask_app.config["PURCHASE_UPLOAD_DIR"] = os.path.join(flask_app.root_path, "static", "uploads", "purchases")
    flask_app.config["PURCHASE_UPLOAD_MAX_BYTES"] = 50 * 1024 * 1024
    flask_app.config["PHOTO_LIBRARY_UPLOAD_DIR"] = os.path.join(flask_app.root_path, "static", "uploads", "library")
    flask_app.config["PHOTO_LIBRARY_MAX_BYTES"] = 50 * 1024 * 1024
    flask_app.config["MOBILE_UPLOAD_DIR"] = os.path.join(flask_app.root_path, "static", "uploads", "mobile")
    flask_app.config["MOBILE_UPLOAD_MAX_BYTES"] = 50 * 1024 * 1024
    flask_app.config["FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET"] = int(
        os.environ.get("FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET", 30)
    )
    db.init_app(flask_app)
    init_auth(flask_app)
    register_blueprints(flask_app)
    return flask_app

app = create_app()


# IANA tz for Slack timestamps, date filters, and derived slack_message_date (Settings → Operational).
APP_DISPLAY_TIMEZONE_DEFAULT = "America/Los_Angeles"


def _runs_list_filters_active(m: dict[str, str]) -> bool:
    try:
        if int(m.get("page") or 1) > 1:
            return True
    except ValueError:
        pass
    if (m.get("sort") or "run_date") != "run_date":
        return True
    if (m.get("order") or "desc") != "desc":
        return True
    for k in ("search", "start_date", "end_date", "supplier_id", "min_potency", "max_potency", "hte_stage"):
        if (m.get(k) or "").strip():
            return True
    return False


@app.context_processor
def inject_app_display_timezone():
    try:
        name = _app_display_timezone_name()
    except Exception:
        name = APP_DISPLAY_TIMEZONE_DEFAULT
    return {"app_display_timezone_name": name}


@app.context_processor
def inject_biomass_budget():
    if not current_user.is_authenticated:
        return {}
    today = date.today()
    ws = _purchase_week_start(today)
    we = ws + timedelta(days=6)
    m = _budget_week_purchase_metrics(ws, we)
    weekly_budget_usd = SystemSetting.get_float("biomass_purchase_weekly_budget_usd", 0)
    weekly_target_lbs = SystemSetting.get_float("biomass_purchase_weekly_target_lbs", 0)
    target_pot = SystemSetting.get_float("biomass_purchase_weekly_target_potency_pct", 0)
    if target_pot <= 0:
        target_pot = SystemSetting.get_float("biomass_budget_target_potency_pct", 0)
    avg = (m["weighted_pot_sum"] / m["lbs"]) if m["lbs"] > 1e-9 else None
    return {
        "biomass_sidebar_week_label": f"{ws.strftime('%b %d')} – {we.strftime('%b %d')}",
        "biomass_purchase_week_spend": m["spend"],
        "biomass_purchase_week_lbs": m["lbs"],
        "biomass_purchase_weekly_budget_usd": weekly_budget_usd,
        "biomass_purchase_weekly_target_lbs": weekly_target_lbs,
        "biomass_purchase_weekly_target_potency_pct": target_pot if target_pot > 0 else None,
        "biomass_purchase_week_avg_potency_pct": avg,
    }


@app.context_processor
def inject_cross_site_visibility():
    enabled = (SystemSetting.get("cross_site_ops_enabled", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
    return {"cross_site_ops_enabled": enabled}


@app.context_processor
def inject_supervisor_notification_summary():
    if not current_user.is_authenticated:
        return {"supervisor_notification_summary": {"open_count": 0, "critical_count": 0, "warning_count": 0, "info_count": 0, "rows": []}, "can_review_supervisor_notifications": False}
    if not manager_can_review(current_user):
        return {"supervisor_notification_summary": {"open_count": 0, "critical_count": 0, "warning_count": 0, "info_count": 0, "rows": []}, "can_review_supervisor_notifications": False}
    return {
        "supervisor_notification_summary": summarize_notifications(sys.modules[__name__], limit=6),
        "can_review_supervisor_notifications": True,
    }


def slack_importer_required(f):
    """Super Admin always allowed; others need Settings → Slack Importer flag."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_slack_import:
            flash("Slack import access is not enabled for your account.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def field_purchase_approval_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_approve_field_purchases:
            flash("Purchase approval access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def purchase_editor_required(f):
    """Edits purchases and related lots/docs; includes Super Buyer, excludes viewers."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_edit_purchases:
            flash("Edit access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(func.lower(User.username) == username.lower()).first() if username else None
        if user and user.check_password(password) and getattr(user, "is_active_user", True):
            login_user(user)
            flash("Signed in.", "success")
            next_url = request.args.get("next") or request.form.get("next") or ""
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    return redirect(url_for("purchase_import"))


@app.route("/import/confirm", methods=["POST"])
@login_required
def import_confirm():
    return redirect(url_for("purchase_import"))


@app.route("/export/<entity>.csv", endpoint="export_csv")
@login_required
def export_csv(entity: str):
    buf = io.StringIO()
    writer = csv.writer(buf)

    if entity == "runs":
        writer.writerow(["run_date", "reactor_number", "bio_in_reactor_lbs", "dry_thca_g", "dry_hte_g", "overall_yield_pct", "hte_pipeline_stage"])
        query = Run.query.filter(Run.deleted_at.is_(None)).order_by(Run.run_date.desc(), Run.id.desc())
        for run in query.all():
            writer.writerow([
                run.run_date.isoformat() if run.run_date else "",
                run.reactor_number,
                run.bio_in_reactor_lbs,
                run.dry_thca_g,
                run.dry_hte_g,
                run.overall_yield_pct,
                run.hte_pipeline_stage or "",
            ])
    elif entity == "purchases":
        writer.writerow(["batch_id", "purchase_date", "delivery_date", "supplier", "status", "stated_weight_lbs", "price_per_lb", "total_cost"])
        query = Purchase.query.filter(Purchase.deleted_at.is_(None)).order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
        for purchase in query.all():
            writer.writerow([
                purchase.batch_id or "",
                purchase.purchase_date.isoformat() if purchase.purchase_date else "",
                purchase.delivery_date.isoformat() if purchase.delivery_date else "",
                purchase.supplier_name,
                purchase.status or "",
                purchase.stated_weight_lbs,
                purchase.price_per_lb,
                purchase.total_cost,
            ])
    elif entity == "biomass":
        writer.writerow(["availability_date", "supplier", "status", "declared_weight_lbs", "declared_price_per_lb", "stated_potency_pct"])
        query = Purchase.query.filter(Purchase.deleted_at.is_(None)).order_by(Purchase.availability_date.desc(), Purchase.id.desc())
        for purchase in query.all():
            writer.writerow([
                purchase.availability_date.isoformat() if purchase.availability_date else "",
                purchase.supplier_name,
                purchase.status or "",
                purchase.declared_weight_lbs,
                purchase.declared_price_per_lb,
                purchase.stated_potency_pct,
            ])
    elif entity == "inventory":
        writer.writerow(["batch_id", "supplier", "strain_name", "weight_lbs", "remaining_weight_lbs", "potency_pct"])
        query = PurchaseLot.query.join(Purchase).filter(
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
        ).order_by(Purchase.purchase_date.desc(), PurchaseLot.id.desc())
        for lot in query.all():
            writer.writerow([
                lot.purchase.batch_id if lot.purchase else "",
                lot.supplier_name,
                lot.strain_name or "",
                lot.weight_lbs,
                lot.remaining_weight_lbs,
                lot.potency_pct,
            ])
    elif entity == "costs":
        writer.writerow(["cost_type", "name", "total_cost", "start_date", "end_date", "notes"])
        query = CostEntry.query.order_by(CostEntry.start_date.desc(), CostEntry.id.desc())
        for cost in query.all():
            writer.writerow([
                cost.cost_type or "",
                cost.name or "",
                cost.total_cost,
                cost.start_date.isoformat() if cost.start_date else "",
                cost.end_date.isoformat() if cost.end_date else "",
                cost.notes or "",
            ])
    elif entity == "suppliers":
        writer.writerow(["name", "contact_name", "contact_phone", "contact_email", "location", "is_active"])
        query = Supplier.query.order_by(Supplier.name.asc(), Supplier.id.asc())
        for supplier in query.all():
            writer.writerow([
                supplier.name or "",
                supplier.contact_name or "",
                supplier.contact_phone or "",
                supplier.contact_email or "",
                supplier.location or "",
                "1" if supplier.is_active else "0",
            ])
    elif entity == "strains":
        writer.writerow(["strain_name", "supplier", "batch_id", "weight_lbs", "remaining_weight_lbs"])
        query = PurchaseLot.query.join(Purchase).filter(
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
        ).order_by(PurchaseLot.strain_name.asc(), PurchaseLot.id.asc())
        for lot in query.all():
            writer.writerow([
                lot.strain_name or "",
                lot.supplier_name,
                lot.purchase.batch_id if lot.purchase else "",
                lot.weight_lbs,
                lot.remaining_weight_lbs,
            ])
    else:
        abort(404)

    body = buf.getvalue()
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={entity}.csv"},
    )


SLACK_RUN_PREFILL_SESSION_KEY = "slack_run_prefill"
SCAN_RUN_PREFILL_SESSION_KEY = "scan_run_prefill"
RUN_SCALE_PREFILL_SESSION_KEY = "run_scale_prefill"


def _slack_apply_form_passthrough(form) -> dict[str, str]:
    return slack_apply_form_passthrough(form)


def _slack_run_prefill_put(
    *,
    msg_id: str,
    channel_id: str,
    message_ts: str,
    filled: dict,
    allow_duplicate: bool,
    resolution: dict | None = None,
) -> None:
    slack_run_prefill_put(
        session,
        msg_id=msg_id,
        channel_id=channel_id,
        message_ts=message_ts,
        filled=filled,
        allow_duplicate=allow_duplicate,
        resolution=resolution,
    )


def _slack_supplier_exact_name_match(source_raw: str, supplier: Supplier | None) -> bool:
    return slack_supplier_exact_name_match(source_raw, supplier)


def _slack_build_supplier_candidate(source_raw: str, supplier: Supplier | None) -> dict | None:
    return slack_build_supplier_candidate(source_raw, supplier)


def _slack_supplier_mapping_needs_fuzzy_confirm(source_raw: str, supplier_id: str | None) -> bool:
    return slack_supplier_mapping_needs_fuzzy_confirm(sys.modules[__name__], source_raw, supplier_id)


def _slack_supplier_candidates_for_source(source_raw: str, limit: int = 12) -> list[dict]:
    return slack_supplier_candidates_for_source(sys.modules[__name__], source_raw, limit)


def _slack_strain_mapping_needs_fuzzy_confirm(raw_strain: str, selected_strain: str | None) -> bool:
    return slack_strain_mapping_needs_fuzzy_confirm(raw_strain, selected_strain)


def _slack_strain_candidates_for_name(
    raw_strain: str,
    *,
    supplier_ids: list[str] | None = None,
    limit: int = 12,
) -> list[dict]:
    return slack_strain_candidates_for_name(
        sys.modules[__name__],
        raw_strain,
        supplier_ids=supplier_ids,
        limit=limit,
    )


def _slack_selected_canonical_strain(
    form,
    *,
    raw_strain: str,
    text_field: str,
    canonical_field: str,
    confirm_field: str,
    required_for_label: str,
) -> tuple[str, str | None]:
    return slack_selected_canonical_strain(
        form,
        raw_strain=raw_strain,
        text_field=text_field,
        canonical_field=canonical_field,
        confirm_field=confirm_field,
        required_for_label=required_for_label,
    )


def _slack_resolution_from_apply_form(
    form,
    *,
    derived: dict,
    message_ts: str,
) -> tuple[dict | None, str | None]:
    return slack_resolution_from_apply_form(
        sys.modules[__name__],
        form,
        derived=derived,
        message_ts=message_ts,
    )


def _first_run_for_slack_message(channel_id: str | None, message_ts: str | None) -> Run | None:
    if not channel_id or not message_ts:
        return None
    return Run.query.filter(
        Run.slack_channel_id == channel_id,
        Run.slack_message_ts == message_ts,
        Run.deleted_at.is_(None),
    ).first()


def _find_intake_purchase_candidates(manifest_key: str) -> list:
    """Match Purchases by batch_id (exact, then substring) for Slack manifest / intake reports."""
    m = (manifest_key or "").strip().upper()
    if len(m) < 2:
        return []
    q = Purchase.query.filter(Purchase.deleted_at.is_(None))
    exact = q.filter(Purchase.batch_id == m).order_by(Purchase.updated_at.desc(), Purchase.created_at.desc()).all()
    if exact:
        return exact[:25]
    return (
        q.filter(
            Purchase.batch_id.isnot(None),
            Purchase.batch_id != "",
            Purchase.batch_id.ilike(f"%{m}%"),
        )
        .order_by(Purchase.updated_at.desc(), Purchase.created_at.desc())
        .limit(25)
        .all()
    )


def _purchase_sync_biomass_pipeline(p: Purchase) -> None:
    """Legacy stub — sync removed after BiomassAvailability merge into Purchase."""
    pass


def log_audit(action, entity_type, entity_id, details=None, user_id=None):
    entry = AuditLog(
        user_id=(user_id if user_id is not None else (current_user.id if current_user.is_authenticated else None)),
        action=action, entity_type=entity_type,
        entity_id=str(entity_id), details=details
    )
    db.session.add(entry)


def _slack_enabled() -> bool:
    return slack_integration_module.slack_enabled(sys.modules[__name__])


def _slack_webhook_url() -> str | None:
    return slack_integration_module.slack_webhook_url(sys.modules[__name__])


def _slack_signing_secret() -> str | None:
    return slack_integration_module.slack_signing_secret(sys.modules[__name__])


def _slack_bot_token() -> str | None:
    return slack_integration_module.slack_bot_token(sys.modules[__name__])


def _slack_channel() -> str | None:
    return slack_integration_module.slack_channel(sys.modules[__name__])


def _post_slack_webhook(text_value: str) -> None:
    slack_integration_module._post_slack_webhook(sys.modules[__name__], text_value)


def _post_slack_api_message(text_value: str) -> None:
    slack_integration_module._post_slack_api_message(sys.modules[__name__], text_value)


def notify_slack(text_value: str) -> None:
    slack_integration_module.notify_slack(sys.modules[__name__], text_value)


def _verify_slack_signature(req) -> bool:
    return slack_integration_module.verify_slack_signature(sys.modules[__name__], req)


def _slack_web_api(token: str, method: str, params: dict) -> dict:
    return slack_integration_module.slack_web_api(sys.modules[__name__], token, method, params)


def _slack_looks_like_conversation_id(hint: str) -> bool:
    return slack_integration_module._slack_looks_like_conversation_id(hint)


def _slack_resolve_channel_id(token: str, channel_setting: str) -> str | None:
    return slack_integration_module.slack_resolve_channel_id(sys.modules[__name__], token, channel_setting)


SLACK_SYNC_CHANNEL_SLOTS = slack_integration_module.SLACK_SYNC_CHANNEL_SLOTS


def _ensure_slack_sync_configs() -> None:
    slack_integration_module.ensure_sync_configs(sys.modules[__name__])


def _slack_ingest_channel_history(
    token: str,
    channel_id: str,
    oldest: str,
    ingested_by: str,
) -> tuple[int, int, str | None, str | None]:
    return slack_integration_module.slack_ingest_channel_history(
        sys.modules[__name__],
        token,
        channel_id,
        oldest,
        ingested_by,
    )


@app.template_filter("slack_ts_la")
def slack_ts_la_template_filter(ts_str):
    return _slack_ts_to_display_datetime_str(ts_str)


def _redirect_settings_slack_imports_preserved():
    return slack_integration_module.redirect_settings_slack_imports_preserved(sys.modules[__name__])


def _hash_field_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


# HTE post-separation workflow (stored on Run when dry HTE exists).
HTE_PIPELINE_ALLOWED = frozenset({"", "awaiting_lab", "lab_clean", "lab_dirty_queued_strip", "terp_stripped"})


def _hte_pipeline_options():
    return [
        ("", "Not set"),
        ("awaiting_lab", "Awaiting lab test (HTE staged / out for testing)"),
        ("lab_clean", "Lab clean — cleared for menu / sale"),
        ("lab_dirty_queued_strip", "Lab dirty — queued for Terp Tubes (Prescott), waiting to strip"),
        ("terp_stripped", "Stripped — terpenes + retail distillate accounted"),
    ]


def _hte_pipeline_label(stage) -> str:
    s = stage or ""
    for val, lab in _hte_pipeline_options():
        if val == s:
            return lab
    return "—"


def _run_form_extras(run=None):
    root_ctx = sys.modules[__name__]
    progression = run_progression_payload(root_ctx, run) if run else run_progression_payload(root_ctx, type("DraftRun", (), {
        "run_completed_at": None,
        "flush_started_at": None,
        "flush_ended_at": None,
        "mixer_started_at": None,
        "mixer_ended_at": None,
        "run_fill_started_at": None,
    })())
    post_extraction = post_extraction_progression_payload(run) if run else post_extraction_progression_payload(type("DraftRun", (), {
        "run_completed_at": None,
        "post_extraction_pathway": None,
        "post_extraction_started_at": None,
        "post_extraction_initial_outputs_recorded_at": None,
    })())
    downstream = downstream_state_payload(run) if run else downstream_state_payload(type("DraftRun", (), {
        "thca_destination": None,
        "hte_clean_decision": None,
        "hte_filter_outcome": None,
        "hte_potency_disposition": None,
        "hte_queue_destination": None,
        "pot_pour_offgas_started_at": None,
        "pot_pour_offgas_completed_at": None,
        "thca_oven_started_at": None,
        "thca_oven_completed_at": None,
        "hte_offgas_started_at": None,
        "hte_offgas_completed_at": None,
    })())
    booth = booth_session_payload(root_ctx, run) if run else booth_session_payload(root_ctx, None)
    timing_controls = run_timing_controls_payload(root_ctx, run) if run else {
        "primary_soak": {"label": "Primary soak", "target_minutes": booth.get("timing_targets", {}).get("primary_soak_minutes"), "actual_minutes": None, "active_minutes": None, "status": "not_started", "delta_minutes": None, "policy": "warning"},
        "mixer": {"label": "Mixer", "target_minutes": booth.get("timing_targets", {}).get("mixer_minutes"), "actual_minutes": None, "active_minutes": None, "status": "not_started", "delta_minutes": None, "policy": "warning"},
        "flush": {"label": "Flush soak", "target_minutes": booth.get("timing_targets", {}).get("flush_minutes"), "actual_minutes": None, "active_minutes": None, "status": "not_started", "delta_minutes": None, "policy": "warning"},
        "final_purge": {"label": "Final purge", "target_minutes": booth.get("timing_targets", {}).get("final_purge_minutes"), "actual_minutes": None, "active_minutes": None, "status": "not_started", "delta_minutes": None, "policy": "informational"},
    }
    booth_review = {
        "status": booth.get("status", "not_started"),
        "current_stage_key": booth.get("current_stage_key", "ready_to_confirm_vacuum"),
        "current_stage_label": progression["stage_label"],
        "policy_block": progression.get("policy_block"),
        "timing_targets": booth.get("timing_targets", {}),
        "timing_controls": timing_controls,
        "flow_resumed_decision": booth.get("flow_resumed_decision", ""),
        "flow_resumed_confirmed_at": booth.get("flow_resumed_confirmed_at", ""),
        "final_clarity_decision": booth.get("final_clarity_decision", ""),
        "final_clarity_confirmed_at": booth.get("final_clarity_confirmed_at", ""),
        "booth_process_completed_at": booth.get("booth_process_completed_at", ""),
        "deviations": [],
        "history": list(booth.get("history", [])),
        "evidence": [],
        "notifications": notification_rows_for_run(root_ctx, run, limit=8) if run is not None else [],
    }
    if booth_review["flow_resumed_decision"] == "no_adjusting":
        booth_review["deviations"].append("Flow is still being adjusted.")
    if booth_review["final_clarity_decision"] == "not_yet":
        booth_review["deviations"].append("Final clarity is not yet acceptable.")
    if run is not None and getattr(run, "booth_session", None) is not None and hasattr(run.booth_session.booth_evidence, "order_by"):
        booth_review["evidence"] = [
            {
                "evidence_type": item.evidence_type,
                "evidence_label": item.evidence_type.replace("_", " ").title(),
                "captured_at": display_local_datetime(item.captured_at),
                "url": url_for("static", filename=item.file_path),
                "file_path": item.file_path,
            }
            for item in run.booth_session.booth_evidence.order_by(ExtractionBoothEvidence.captured_at.desc()).limit(12).all()
        ]
    return {
        "hte_lab_paths": _json_paths(getattr(run, "hte_lab_result_paths_json", None) if run else None),
        "hte_pipeline_options": _hte_pipeline_options(),
        "post_extraction_pathway_options": POST_EXTRACTION_PATHWAY_OPTIONS,
        "thca_destination_options": THCA_DESTINATION_OPTIONS,
        "hte_clean_decision_options": HTE_CLEAN_DECISION_OPTIONS,
        "hte_filter_outcome_options": HTE_FILTER_OUTCOME_OPTIONS,
        "hte_potency_disposition_options": HTE_POTENCY_DISPOSITION_OPTIONS,
        "hte_queue_destination_options": HTE_QUEUE_DESTINATION_OPTIONS,
        "run_execution_fields": {
            "run_fill_started_at": display_local_datetime(getattr(run, "run_fill_started_at", None) if run else None),
            "run_fill_ended_at": display_local_datetime(getattr(run, "run_fill_ended_at", None) if run else None),
            "run_fill_duration_minutes": duration_minutes(getattr(run, "run_fill_started_at", None) if run else None, getattr(run, "run_fill_ended_at", None) if run else None),
            "mixer_started_at": display_local_datetime(getattr(run, "mixer_started_at", None) if run else None),
            "mixer_ended_at": display_local_datetime(getattr(run, "mixer_ended_at", None) if run else None),
            "mixer_duration_minutes": duration_minutes(getattr(run, "mixer_started_at", None) if run else None, getattr(run, "mixer_ended_at", None) if run else None),
            "flush_started_at": display_local_datetime(getattr(run, "flush_started_at", None) if run else None),
            "flush_ended_at": display_local_datetime(getattr(run, "flush_ended_at", None) if run else None),
            "flush_duration_minutes": duration_minutes(getattr(run, "flush_started_at", None) if run else None, getattr(run, "flush_ended_at", None) if run else None),
            "run_completed_at": display_local_datetime(getattr(run, "run_completed_at", None) if run else None),
            "progression_stage_label": progression["stage_label"],
            "progression_description": progression["description"],
            "post_extraction_stage_label": post_extraction["stage_label"],
            "post_extraction_description": post_extraction["description"],
            "post_extraction_pathway_label": post_extraction.get("pathway_label") or "",
            "post_extraction_started_at": display_local_datetime(getattr(run, "post_extraction_started_at", None) if run else None),
            "post_extraction_initial_outputs_recorded_at": display_local_datetime(getattr(run, "post_extraction_initial_outputs_recorded_at", None) if run else None),
            "pot_pour_offgas_started_at": display_local_datetime(getattr(run, "pot_pour_offgas_started_at", None) if run else None),
            "pot_pour_offgas_completed_at": display_local_datetime(getattr(run, "pot_pour_offgas_completed_at", None) if run else None),
            "pot_pour_offgas_duration_minutes": downstream["pot_pour_offgas_duration_hours"],
            "pot_pour_centrifuged_at": display_local_datetime(getattr(run, "pot_pour_centrifuged_at", None) if run else None),
            "thca_oven_started_at": display_local_datetime(getattr(run, "thca_oven_started_at", None) if run else None),
            "thca_oven_completed_at": display_local_datetime(getattr(run, "thca_oven_completed_at", None) if run else None),
            "thca_oven_duration_minutes": downstream["thca_oven_duration_hours"],
            "thca_milled_at": display_local_datetime(getattr(run, "thca_milled_at", None) if run else None),
            "thca_destination_label": downstream["thca_destination_label"],
            "hte_offgas_started_at": display_local_datetime(getattr(run, "hte_offgas_started_at", None) if run else None),
            "hte_offgas_completed_at": display_local_datetime(getattr(run, "hte_offgas_completed_at", None) if run else None),
            "hte_offgas_duration_minutes": downstream["hte_offgas_duration_hours"],
            "hte_clean_decision_label": downstream["hte_clean_decision_label"],
            "hte_filter_outcome_label": downstream["hte_filter_outcome_label"],
            "hte_prescott_processed_at": display_local_datetime(getattr(run, "hte_prescott_processed_at", None) if run else None),
            "hte_potency_disposition_label": downstream["hte_potency_disposition_label"],
            "hte_queue_destination_label": downstream["hte_queue_destination_label"],
        },
        "booth_review": booth_review,
    }


def _get_field_token_value() -> str | None:
    """Read token from querystring or form."""
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


def _require_field_token():
    token = _get_field_token_value()
    if not token:
        return None, "Missing access token."
    token_hash = _hash_field_token(token)
    tok = FieldAccessToken.query.filter_by(token_hash=token_hash).first()
    if not tok:
        return None, "Invalid access token."
    if not tok.is_active:
        return None, "Access token is expired or revoked."
    # Touch last_used_at (best-effort)
    try:
        tok.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return tok, None


def field_token_required(view_fn):
    @wraps(view_fn)
    def wrapper(*args, **kwargs):
        tok, err = _require_field_token()
        if err:
            return render_template("field_error.html", message=err), 403
        return view_fn(tok, *args, **kwargs)
    return wrapper


def _exclude_unpriced_batches_enabled() -> bool:
    val = (SystemSetting.get("exclude_unpriced_batches", "0") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def _priced_run_filter():
    """
    Keep only runs where:
    - at least one input lot linked, and
    - no input lot has a missing purchase $/lb.
    """
    inputs_exist = exists(
        select(1).select_from(RunInput).where(RunInput.run_id == Run.id).correlate(Run)
    )
    missing_price_exists = exists(
        select(1).select_from(RunInput).join(
            PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(
            Purchase, PurchaseLot.purchase_id == Purchase.id
        ).where(
            RunInput.run_id == Run.id,
            Purchase.price_per_lb.is_(None),
        ).correlate(Run)
    )
    return and_(inputs_exist, ~missing_price_exists)


def _pricing_status_for_run_ids(run_ids):
    """dict[run_id] -> priced|partial|unpriced|unlinked."""
    if not run_ids:
        return {}
    total_rows = db.session.query(
        RunInput.run_id, func.count(RunInput.id)
    ).filter(
        RunInput.run_id.in_(run_ids)
    ).group_by(RunInput.run_id).all()
    total_by_run = {rid: cnt for rid, cnt in total_rows}

    priced_rows = db.session.query(
        RunInput.run_id, func.count(RunInput.id)
    ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
    ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
    ).filter(
        RunInput.run_id.in_(run_ids),
        Purchase.price_per_lb.isnot(None),
    ).group_by(RunInput.run_id).all()
    priced_by_run = {rid: cnt for rid, cnt in priced_rows}

    status = {}
    for rid in run_ids:
        total = int(total_by_run.get(rid, 0) or 0)
        priced = int(priced_by_run.get(rid, 0) or 0)
        if total == 0:
            status[rid] = "unlinked"
        elif priced == total:
            status[rid] = "priced"
        elif priced == 0:
            status[rid] = "unpriced"
        else:
            status[rid] = "partial"
    return status


def _supplier_prefix(name: str, length: int = 5) -> str:
    cleaned = "".join(ch for ch in (name or "").upper() if ch.isalnum())
    return (cleaned[:length] or "BATCH")


def _generate_batch_id(supplier_name: str, batch_date: date | None, weight_lbs: float | None) -> str:
    """
    Generate a descriptive, readable batch identifier.
    Example: FARML-15FEB26-200
    """
    d = batch_date or date.today()
    w = int(round(weight_lbs or 0))
    return f"{_supplier_prefix(supplier_name)}-{d.strftime('%d%b%y').upper()}-{w}"[:80]


def _ensure_unique_batch_id(candidate: str, exclude_purchase_id: str | None = None) -> str:
    """Ensure uniqueness by suffixing -2, -3... when needed."""
    base = (candidate or "").strip().upper()
    if not base:
        base = "BATCH"
    bid = base
    n = 2
    max_attempts = 100
    for _ in range(max_attempts):
        q = Purchase.query.filter(Purchase.batch_id == bid)
        if exclude_purchase_id:
            q = q.filter(Purchase.id != exclude_purchase_id)
        if not q.first():
            return bid
        bid = f"{base}-{n}"
        n += 1
    raise ValueError(f"Could not generate a unique batch ID for base '{base}' after {max_attempts} attempts.")


_SLACK_IMPORTS_QUERY_KEYS = frozenset({
    "start_date", "end_date", "channel_id", "promotion", "coverage",
    "kind_filter", "text_filter", "text_op", "include_hidden",
})


# ?????? Biomass Availability Pipeline ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

PIPELINE_PURCHASE_STATUSES = ("declared", "in_testing", "committed")
# Map stage filter values (used in UI) to Purchase status values
_STAGE_TO_STATUS = {
    "declared": "declared",
    "testing": "in_testing",
    "in_testing": "in_testing",
    "committed": "committed",
    "delivered": "delivered",
    "cancelled": "cancelled",
}


def _save_biomass_purchase(existing):
    import app as root
    return biomass_module.save_biomass_purchase(root, existing)

    """Save a Purchase record from the biomass pipeline form (declaration → testing → commitment flow)."""
    try:
        if existing and existing.deleted_at:
            raise ValueError("This row is archived. Restore it from the biomass list before editing.")
        prev_status = existing.status if existing else None
        p = existing or Purchase()

        supplier_id = (request.form.get("supplier_id") or "").strip()
        if not supplier_id:
            raise ValueError("Supplier is required.")
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        p.supplier_id = supplier_id

        # --- Declaration fields ---
        ad = request.form.get("availability_date", "").strip()
        if not ad:
            raise ValueError("Availability Date is required.")
        try:
            p.availability_date = datetime.strptime(ad, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Availability Date must be a valid date.")

        strain_name = request.form.get("strain_name", "").strip() or None

        dw = request.form.get("declared_weight_lbs", "").strip()
        try:
            p.declared_weight_lbs = float(dw) if dw else 0.0
        except ValueError:
            raise ValueError("Declared Weight must be a number.")
        if p.declared_weight_lbs < 0:
            raise ValueError("Declared Weight cannot be negative.")

        dpl = request.form.get("declared_price_per_lb", "").strip()
        try:
            p.declared_price_per_lb = float(dpl) if dpl else None
        except ValueError:
            raise ValueError("Declared $/lb must be a number.")
        if p.declared_price_per_lb is not None and p.declared_price_per_lb < 0:
            raise ValueError("Declared $/lb cannot be negative.")

        ep = request.form.get("estimated_potency_pct", "").strip()
        try:
            estimated_potency = float(ep) if ep else None
        except ValueError:
            raise ValueError("Estimated Potency must be a number.")
        if estimated_potency is not None and not (0 <= estimated_potency <= 100):
            raise ValueError("Estimated Potency must be between 0 and 100.")
        p.stated_potency_pct = estimated_potency

        # --- Testing fields ---
        testing_timing = (request.form.get("testing_timing") or "before_delivery").strip()
        if testing_timing not in ("before_delivery", "after_delivery"):
            raise ValueError("Testing Timing is invalid.")
        p.testing_timing = testing_timing

        testing_status = (request.form.get("testing_status") or "pending").strip()
        if testing_status not in ("pending", "completed", "not_needed"):
            raise ValueError("Testing Status is invalid.")
        p.testing_status = testing_status

        td = request.form.get("testing_date", "").strip()
        if td:
            try:
                p.testing_date = datetime.strptime(td, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Testing Date must be a valid date.")
        else:
            p.testing_date = None

        tpp = request.form.get("tested_potency_pct", "").strip()
        try:
            p.tested_potency_pct = float(tpp) if tpp else None
        except ValueError:
            raise ValueError("Tested Potency must be a number.")
        if p.tested_potency_pct is not None and not (0 <= p.tested_potency_pct <= 100):
            raise ValueError("Tested Potency must be between 0 and 100.")

        # --- Commitment fields (map to core Purchase fields) ---
        co = request.form.get("committed_on", "").strip()
        if co:
            try:
                p.purchase_date = datetime.strptime(co, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Committed On must be a valid date.")
        else:
            p.purchase_date = p.purchase_date or p.availability_date

        cdd = request.form.get("committed_delivery_date", "").strip()
        if cdd:
            try:
                p.delivery_date = datetime.strptime(cdd, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Delivery Date must be a valid date.")
        else:
            p.delivery_date = None

        cw = request.form.get("committed_weight_lbs", "").strip()
        try:
            committed_weight = float(cw) if cw else None
        except ValueError:
            raise ValueError("Committed Weight must be a number.")
        if committed_weight is not None and committed_weight < 0:
            raise ValueError("Committed Weight cannot be negative.")
        p.stated_weight_lbs = committed_weight or p.declared_weight_lbs or 0

        cpl = request.form.get("committed_price_per_lb", "").strip()
        try:
            committed_price = float(cpl) if cpl else None
        except ValueError:
            raise ValueError("Committed $/lb must be a number.")
        if committed_price is not None and committed_price < 0:
            raise ValueError("Committed $/lb cannot be negative.")
        p.price_per_lb = committed_price or p.declared_price_per_lb

        # --- Status (mapped from pipeline stage names) ---
        stage = (request.form.get("stage") or "declared").strip()
        stage_to_status = {
            "declared": "declared",
            "testing": "in_testing",
            "committed": "committed",
            "delivered": "delivered",
            "cancelled": "cancelled",
        }
        new_status = stage_to_status.get(stage)
        if not new_status:
            raise ValueError("Stage is invalid.")

        validate_delivered_requires_prior_commitment(prev_status=prev_status, new_status=new_status)

        # Approval gate for commitment transitions
        enters_commitment, _leaves_commitment = validate_pipeline_commitment_transition(
            prev_status=prev_status,
            new_status=new_status,
            can_approve_purchase=current_user.can_approve_purchase,
        )
        if enters_commitment:
            stamp_purchase_approval(purchase=p, approver_user_id=current_user.id)

        p.status = new_status
        p.notes = request.form.get("notes", "").strip() or None

        # Total cost calculation
        weight = p.actual_weight_lbs or p.stated_weight_lbs
        if weight and p.price_per_lb:
            p.total_cost = weight * p.price_per_lb

        # Auto-calculate price from potency if no price set
        if p.stated_potency_pct and not p.price_per_lb:
            rate = SystemSetting.get_float("potency_rate", 1.50)
            p.price_per_lb = rate * p.stated_potency_pct

        if not existing:
            db.session.add(p)
        db.session.flush()

        # Batch ID
        if not p.batch_id:
            sup = db.session.get(Supplier, p.supplier_id)
            supplier_name = sup.name if sup else "BATCH"
            d = p.delivery_date or p.purchase_date or p.availability_date
            w = p.actual_weight_lbs or p.stated_weight_lbs
            p.batch_id = _ensure_unique_batch_id(
                _generate_batch_id(supplier_name, d, w),
                exclude_purchase_id=p.id,
            )

        # Maintain the pipeline lot (single lot per pipeline purchase for strain tracking)
        first_lot = p.lots.first()
        if strain_name:
            if first_lot:
                first_lot.strain_name = strain_name
                first_lot.weight_lbs = p.stated_weight_lbs or p.declared_weight_lbs or 0
                first_lot.remaining_weight_lbs = first_lot.weight_lbs
                if estimated_potency:
                    first_lot.potency_pct = p.tested_potency_pct or estimated_potency
            else:
                lot = PurchaseLot(
                    purchase_id=p.id,
                    strain_name=strain_name,
                    weight_lbs=p.stated_weight_lbs or p.declared_weight_lbs or 0,
                    remaining_weight_lbs=p.stated_weight_lbs or p.declared_weight_lbs or 0,
                    potency_pct=p.tested_potency_pct or estimated_potency,
                )
                db.session.add(lot)

        if enters_commitment:
            log_audit(
                "purchase_approval",
                "purchase",
                p.id,
                details=json.dumps({
                    "approver_user_id": current_user.id,
                    "status": p.status,
                    "source": "biomass_pipeline",
                }),
            )

        log_audit("update" if existing else "create", "purchase", p.id,
                  details=json.dumps({"source": "biomass_pipeline", "status": p.status}))
        db.session.commit()
        flash("Biomass availability saved.", "success")
        return redirect(url_for("biomass_list"))
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        return render_template("biomass_form.html", item=existing, suppliers=suppliers, today=date.today())
    except Exception:
        db.session.rollback()
        app.logger.exception("Error saving biomass availability")
        flash("Error saving biomass availability. Please check your inputs and try again.", "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        return render_template("biomass_form.html", item=existing, suppliers=suppliers, today=date.today())


# ?????? API endpoints for AJAX ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????


@app.route("/api/lots/available")
@login_required
def api_lots_available():
    lots = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        Purchase.status.in_(INVENTORY_ON_HAND_PURCHASE_STATUSES),
        Purchase.purchase_approved_at.isnot(None),
    ).all()
    return jsonify([{
        "id": l.id,
        "strain": l.strain_name,
        "supplier": l.supplier_name,
        "remaining": l.remaining_weight_lbs,
        "label": l.display_label,
    } for l in lots])


# ── Initialize ───────────────────────────────────────────────────────────────

def init_db():
    import app as root
    return bootstrap_module.init_db(root)


def _seed_historical_data():
    """Import 43 runs from Gold Drop's Google Sheet (Jan 13 – Feb 6, 2026)."""
    from datetime import datetime as dt

    print("Seeding historical run data from Google Sheet...")

    RAW = [
        ("2/6","315","16","10.1","rockets x Humbolt 1 & 2","Farmlane","23.00","200","90800","3762","7627","","5710"),
        ("2/5","400","20","10.1","Bubble Gum Gushers/ Rollover","Honey Pot/ Rollover","","200","90800","3224","9557","","7110"),
        ("2/5","","","10.1","Coffee Creamer 1 & 2","Verde","","200","90800","5288","9007","","7550"),
        ("2/5","386","10","10.1","ADL #1","Canndescent","","100","45400","4454","4637","","3810"),
        ("2/4","","","10.1","Rockets x Humbolt","Farmlane/Rollover","","200","90800","4362","8107","","6490"),
        ("2/4","809","14","10.1","Rockets x Humbolt","Farmlane","","200","90800","5062","11797","","9240"),
        ("2/3","","","10.1","Rockets x Humbolt","Farmlane","","200","90800","4088","12857","","8670"),
        ("2/3","955","18","","Rockets x Humbolt","Farmlane","","200","90800","4478","11857","4120","8330"),
        ("2/2","","","","Rockets x Humbolt","Farmlane","","200","90800","5320","9777","4890","7870"),
        ("2/2","1326","8","","Rockets x Humbolt","Farmlane","","200","90800","3676","8927","3240","7210"),
        ("1/30","","","","Dosi Gelonade 4","7 Leaves","","100","45400","12772","0","",""),
        ("1/30","","","","ACME 1","ACME","","100","45400","9220","0","",""),
        ("1/30","","","","Dosi Gelonade 2&3","7 Leaves","","200","90800","4626","11067","4120","8400"),
        ("1/30","","","","Oakland Runtz x Dosi Gelonade","Clock Tower x 7 Leaves","","200","90800","2392","9327","1980","7830"),
        ("1/29","","16","","Oakland Runtz 1&2","Clock Tower","","200","90800","5262","12757","4030","9520"),
        ("1/29","2328","16","","K-Train 4&5","SmGreenTech","","200","90800","4192","6587","3780","5540"),
        ("1/28","","9","","K-Train 2&3","SmGreenTech","","200","90800","4884","7830","3726","6400"),
        ("1/28","1017","15","","Spent 4 x K-Train 1","SmGreenTech/COT","","200","90800","4436","4070","3000","3620"),
        ("1/27","","15","","Spent 2&3 COT","City of Trees","","200","90800","1816","1560","744","1430"),
        ("1/27","","15","","K-Train 4 x Spent COT","SmGreenTech/COT","","200","90800","4716","6830","2912","5080"),
        ("1/27","","15","","K-Train 2&3","SmGreenTech","","200","90800","6122","11520","5654","8380"),
        ("1/26","","","","Gello x K-Train","SmGreenTech","","200","90800","4976","10060","4266","7880"),
        ("1/26","","10","","Gello 3&4","SmGreenTech","","200","90800","6386","8270","6090","7330"),
        ("1/23","","","","Gello 1&2","SmGreenTech","","200","90800","5194","10980","4830","7820"),
        ("1/23","886","","","K-Whip 3&4","SmGreenTech","","200","90800","4512","10420","4002","7200"),
        ("1/23","","","","K-Whip 1&2","SmGreenTech","","200","90800","5278","10370","4914","8200"),
        ("1/23","1288","","","BJxHFCS 3&4","Canndescent","","200","90800","5084","8550","4942","6770"),
        ("1/22","","","","BJxHFCS 1&2","Canndescent","","200","90800","2984","8600","2724","7290"),
        ("1/22","1588","","","Citrus Project/Rollover","Rollover","","200","90800","6200","10870","5980","7090"),
        ("1/21","691","11","","Apple Strudle x Mango Mintality","ACME","","200","90800","6010","8180","5870","6480"),
        ("1/20","548","16","","Rollover","Rollover","","200","90800","4886","11790","4660","8290"),
        ("1/19","","","","Purple Punch","City of Trees/Rollover","","200","90800","4424","13820","4220","11350"),
        ("1/19","1050","","","Frosted Blue Runtz","Founding Fathers","","200","90800","5404","8960","5304","7330"),
        ("1/17","1050","","","K Whip x Pinyatti 8&9","SmGreenTech","","200","90800","5714","12510","5208","8920"),
        ("1/16","","","","K Whip x Pinyatti 7(pot pour)","SmGreenTech","","100","45400","6326","0","2621","2775"),
        ("1/16","","","","K Whip x Pinyatti 5&6","SmGreenTech","","200","90800","5420","10030","4978","7540"),
        ("1/16","1584","","","K Whip x Pinyatti 3&4","SmGreenTech","","200","90800","5230","10280","4888","8210"),
        ("1/15","","","","K Whip x Pinyatti 1&2","SmGreenTech","","200","90800","5784","10630","5520","8390"),
        ("1/15","1998","","","Cookies x Pink Gator 3&4","Farmlane","","200","90800","3654","9170","3354","7960"),
        ("1/14","","","","Cookies x Pink Gator 1&2","Farmlane","","200","90800","4494","10240","4190","7510"),
        ("1/14","2392","","","Pink Runtz X Gello 11&12","Canndescent","","200","90800","4210","9480","3870","7920"),
        ("1/13","1244","","","Pink Runtz X Gello 9&10","Canndescent","","200","90800","3510","10670","3290","8410"),
        ("1/13","1243","","","Pink Runtz X Gello 7&8","Canndescent","","200","90800","3160","9960","2650","7970"),
    ]

    SRC_MAP = {
        "Farmlane": "Farmlane", "Farmlane/Rollover": "Farmlane",
        "SmGreenTech": "SmGreenTech", "SmGreenTech/COT": "SmGreenTech",
        "Canndescent": "Canndescent", "7 Leaves": "7 Leaves",
        "ACME": "ACME", "Clock Tower": "Clock Tower",
        "Clock Tower x 7 Leaves": "Clock Tower",
        "City of Trees": "City of Trees", "City of Trees/Rollover": "City of Trees",
        "Verde": "Verde", "Honey Pot/ Rollover": "Honey Pot",
        "Founding Fathers": "Founding Fathers",
        "Rollover": "Rollover (Blends)",
    }

    def pf(s):
        if not s:
            return None
        try:
            v = float(s.replace(",", ""))
            return v if v != 0 else None
        except (ValueError, TypeError):
            return None

    def pdate(s):
        s = s.replace("-", "/")
        try:
            return dt.strptime(s, "%m/%d").date().replace(year=2026)
        except ValueError:
            return None

    sup_objs = {}
    for norm_name in set(SRC_MAP.values()):
        s = Supplier(name=norm_name)
        if norm_name == "Rollover (Blends)":
            s.notes = "Auto-created for unattributed rollover runs"
        db.session.add(s)
        db.session.flush()
        sup_objs[norm_name] = s

    purch_objs = {}
    for name, sup in sup_objs.items():
        p = Purchase(supplier_id=sup.id, purchase_date=date(2026, 1, 13),
                     status="complete", stated_weight_lbs=0)
        db.session.add(p)
        db.session.flush()
        purch_objs[name] = p

    lot_cache = {}
    count = 0
    for (dt_s, bio_house, butane, solvent, strain, source, price,
         lbs_s, grams_s, w_hte, w_thca, d_hte, d_thca) in RAW:

        run_date = pdate(dt_s)
        lbs = pf(lbs_s)
        if not run_date or not lbs:
            continue

        sup_name = SRC_MAP.get(source, "Rollover (Blends)")
        is_rollover = "Rollover" in source or "Rollover" in strain

        cache_key = (sup_name, strain)
        if cache_key not in lot_cache:
            lot = PurchaseLot(purchase_id=purch_objs[sup_name].id,
                              strain_name=strain, weight_lbs=0, remaining_weight_lbs=0)
            db.session.add(lot)
            db.session.flush()
            lot_cache[cache_key] = lot
        lot = lot_cache[cache_key]
        lot.weight_lbs += lbs
        purch_objs[sup_name].stated_weight_lbs += lbs

        grams = pf(grams_s) or (lbs * 454)
        dry_hte = pf(d_hte)
        dry_thca = pf(d_thca)
        dry_total = (dry_hte or 0) + (dry_thca or 0)

        run = Run(
            run_date=run_date, reactor_number=1, is_rollover=is_rollover,
            bio_in_house_lbs=pf(bio_house), bio_in_reactor_lbs=lbs,
            grams_ran=grams, butane_in_house_lbs=pf(butane),
            solvent_ratio=pf(solvent),
            wet_hte_g=pf(w_hte), wet_thca_g=pf(w_thca),
            dry_hte_g=dry_hte, dry_thca_g=dry_thca,
            overall_yield_pct=(dry_total / grams * 100) if grams and dry_total else None,
            thca_yield_pct=(dry_thca / grams * 100) if grams and dry_thca else None,
            hte_yield_pct=(dry_hte / grams * 100) if grams and dry_hte else None,
            run_type="standard",
            notes=f"Imported from Google Sheet. Source: {source}",
        )
        db.session.add(run)
        db.session.flush()

        inp = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=lbs)
        db.session.add(inp)

        p_val = pf(price)
        if p_val and not purch_objs[sup_name].price_per_lb:
            purch_objs[sup_name].price_per_lb = p_val

        run.calculate_cost()
        count += 1

    db.session.commit()
    print(f"  Seeded {count} historical runs across {len(sup_objs)} suppliers.")


def _register_extracted_routes(flask_app):
    root = sys.modules[__name__]
    existing = set(flask_app.view_functions)
    if "api_v1_site" not in existing:
        api_v1_module.register_routes(flask_app, root)
    if "slack_events" not in existing:
        slack_integration_module.register_routes(flask_app, root)
    if "settings" not in existing:
        settings_module.register_routes(flask_app, root)
    if "purchases_list" not in existing:
        purchases_module.register_routes(flask_app, root)
    if "biomass_list" not in existing:
        biomass_module.register_routes(flask_app, root)
    if "runs_list" not in existing:
        runs_module.register_routes(flask_app, root)
    if "dashboard" not in existing:
        dashboard_module.register_routes(flask_app, root)
    if "floor_ops" not in existing:
        floor_module.register_routes(flask_app, root)
    if "field_home" not in existing:
        field_intake_module.register_routes(flask_app, root)
    if "costs_list" not in existing:
        costs_module.register_routes(flask_app, root)
    if "inventory" not in existing:
        inventory_module.register_routes(flask_app, root)
    if "batch_edit" not in existing:
        batch_edit_module.register_routes(flask_app, root)
    if "suppliers_list" not in existing:
        suppliers_module.register_routes(flask_app, root)
    if "purchase_import" not in existing:
        purchase_import_module.register_routes(flask_app, root)
    if "strains_list" not in existing:
        strains_module.register_routes(flask_app, root)
    if "mobile_auth_login" not in existing:
        mobile_module.register_routes(flask_app, root)


_base_create_app = create_app


def create_app():
    flask_app = _base_create_app()
    _register_extracted_routes(flask_app)
    return flask_app


_register_extracted_routes(app)


with app.app_context():
    init_db()


if __name__ == "__main__":
    # Default 5050: on macOS, port 5000 is often taken by AirPlay Receiver.
    _port = int(os.environ.get("PORT", "5050"))
    print(f" * Open http://127.0.0.1:{_port}/  (set PORT=5000 if you prefer and nothing else is using it)")
    app.run(debug=True, host="0.0.0.0", port=_port)


