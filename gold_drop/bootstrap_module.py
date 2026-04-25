from __future__ import annotations

import json

from gold_drop.slack import _default_slack_run_field_rules
from sqlalchemy.exc import OperationalError, ProgrammingError
from services.extraction_run import EXTRACTION_RUN_DEFAULTS, TIMING_POLICY_DEFAULTS
from services.supervisor_notifications import REMINDER_DEFAULTS
from services.bootstrap_helpers import (
    backfill_default_inventory_lots,
    backfill_purchase_approval,
    ensure_postgres_run_hte_columns,
    ensure_postgres_run_execution_columns,
    ensure_postgres_mobile_columns,
    ensure_postgres_slack_ingested_columns,
    ensure_sqlite_schema,
    migrate_biomass_to_purchase,
    reconcile_closed_purchase_inventory_lots,
)


def init_db(root):
    """Create tables and seed initial data."""
    try:
        root.db.create_all()
    except (OperationalError, ProgrammingError) as exc:
        root.db.session.rollback()
        err_txt = str(getattr(exc, "orig", None) or exc).lower()
        if "already exists" not in err_txt and "duplicate" not in err_txt:
            raise
    ensure_sqlite_schema(root)
    ensure_postgres_run_hte_columns(root)
    ensure_postgres_run_execution_columns(root)
    ensure_postgres_mobile_columns(root)
    ensure_postgres_slack_ingested_columns(root)
    reconcile_closed_purchase_inventory_lots(root)
    backfill_default_inventory_lots(root)
    backfill_purchase_approval(root)
    migrate_biomass_to_purchase(root)

    if not root.User.query.first():
        admin = root.User(username="admin", display_name="Admin", role="super_admin")
        admin.set_password("golddrop2026")
        root.db.session.add(admin)

        user = root.User(username="ops", display_name="VP Operations", role="user")
        user.set_password("golddrop2026")
        root.db.session.add(user)

        viewer = root.User(username="viewer", display_name="Team Viewer", role="viewer")
        viewer.set_password("golddrop2026")
        root.db.session.add(viewer)

    defaults = {
        "site_code": ("DEFAULT", "Site code for internal API and future rollup"),
        "site_name": ("Gold Drop", "Site display name for internal API and reporting"),
        "site_timezone": ("America/Los_Angeles", "IANA timezone for this site"),
        "site_region": ("", "Optional site region for future rollup and aggregation"),
        "site_environment": ("production", "Deployment environment label for internal API metadata"),
        "cross_site_ops_enabled": ("0", "Enable cross-site operations UI surfaces for this site"),
        "standalone_purchasing_enabled": ("1", "Enable standalone purchasing app workflow"),
        "standalone_receiving_enabled": ("1", "Enable standalone receiving intake app workflow"),
        "standalone_extraction_enabled": ("1", "Enable standalone extraction lab app workflow"),
        "potency_rate": ("1.50", "Potency Rate ($/lb/%pt)"),
        "num_reactors": ("2", "Number of Reactors"),
        "reactor_capacity": ("100", "Reactor Capacity (lbs)"),
        "runs_per_day": ("5", "Runs Per Day Target"),
        "operating_days": ("7", "Operating Days Per Week"),
        "daily_throughput_target": ("500", "Daily Throughput Target (lbs)"),
        "weekly_throughput_target": ("3500", "Weekly Throughput Target (lbs)"),
        "weekly_dollar_budget": ("0", "Weekly dollar budget (buyer/finance snapshot)"),
        "potential_lot_days_to_old": ("10", "Days before potential biomass moves to Old Lots"),
        "potential_lot_days_to_soft_delete": ("30", "Total days from created_at before soft-delete (potential rows)"),
        "exclude_unpriced_batches": ("0", "Exclude unpriced/unlinked runs from yield and cost analytics"),
        "cost_allocation_method": ("per_gram_uniform", "Cost allocation method for THCA vs HTE cost/gram"),
        "cost_allocation_thca_pct": ("50", "Custom cost allocation: percent of total run cost allocated to THCA"),
        "biomass_purchase_weekly_budget_usd": ("0", "Weekly biomass purchasing budget (USD)"),
        "biomass_purchase_weekly_target_lbs": ("0", "Weekly biomass purchasing volume target (lbs)"),
        "biomass_purchase_weekly_target_potency_pct": ("0", "Weekly target weighted avg potency % (purchasing)"),
        "biomass_budget_target_potency_pct": ("0", "Target weighted avg potency % (purchasing)"),
        "supervisor_notifications_enabled": ("1", "Enable in-app supervisor notifications for extraction and workflow deviations"),
        "slack_outbound_notifications_enabled": ("0", "Enable outbound Slack delivery for supervisor notifications"),
        "slack_webhook_completions_url": ("", "Slack webhook URL for completion notifications"),
        "slack_webhook_warnings_url": ("", "Slack webhook URL for warning notifications"),
        "slack_webhook_reminders_url": ("", "Slack webhook URL for reminder notifications"),
    }
    defaults.update(EXTRACTION_RUN_DEFAULTS)
    defaults.update(TIMING_POLICY_DEFAULTS)
    defaults.update(REMINDER_DEFAULTS)
    for key, (value, description) in defaults.items():
        if not root.db.session.get(root.SystemSetting, key):
            root.db.session.add(root.SystemSetting(key=key, value=value, description=description))

    if not root.db.session.get(root.SystemSetting, root.SLACK_RUN_MAPPINGS_KEY):
        root.db.session.add(root.SystemSetting(
            key=root.SLACK_RUN_MAPPINGS_KEY,
            value=json.dumps({"rules": _default_slack_run_field_rules()}),
            description="Slack derived_json -> Run field preview mappings (Phase 1 JSON)",
        ))

    kpi_defaults = [
        ("thca_yield_pct", "THCA Yield %", 7.0, 7.0, 6.0, "higher_is_better", "%"),
        ("hte_yield_pct", "HTE Yield %", 5.0, 5.0, 4.0, "higher_is_better", "%"),
        ("overall_yield_pct", "Overall Yield %", 12.0, 12.0, 10.0, "higher_is_better", "%"),
        ("cost_per_potency_point", "Cost per Potency Point", 1.50, 1.35, 1.65, "lower_is_better", "$/lb/%pt"),
        ("cost_per_gram_combined", "Cost per Gram", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("cost_per_gram_thca", "Cost per Gram (THCA)", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("cost_per_gram_hte", "Cost per Gram (HTE)", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("weekly_throughput", "Weekly Throughput", 3500, 3500, 3000, "higher_is_better", "lbs"),
    ]
    for name, display, target, green, yellow, direction, unit in kpi_defaults:
        if not root.KpiTarget.query.filter_by(kpi_name=name).first():
            root.db.session.add(root.KpiTarget(
                kpi_name=name,
                display_name=display,
                target_value=target,
                green_threshold=green,
                yellow_threshold=yellow,
                direction=direction,
                unit=unit,
            ))

    root.db.session.commit()

    missing = root.Purchase.query.filter(root.db.or_(root.Purchase.batch_id.is_(None), root.Purchase.batch_id == "")).all()
    for purchase in missing:
        supplier_name = purchase.supplier_name
        batch_date = purchase.delivery_date or purchase.purchase_date
        batch_weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
        purchase.batch_id = root._ensure_unique_batch_id(
            root._generate_batch_id(supplier_name, batch_date, batch_weight),
            exclude_purchase_id=purchase.id,
        )
    if missing:
        root.db.session.commit()
