from __future__ import annotations

import json

from gold_drop.purchases import budget_week_purchase_metrics, purchase_week_start
from services.api_site import get_site_identity
from services.material_genealogy import (
    ACTIVE_MATERIAL_ISSUE_STATUSES,
    apply_material_issue_action,
    build_material_reporting_payload,
    build_material_lot_ancestry_payload,
    build_material_lot_descendants_payload,
    build_material_lot_detail_payload,
    build_material_lot_journey_payload,
    issue_reminder_snapshot,
    process_material_issue_reminders,
    serialize_reconciliation_issue,
)
from services.purchases_journey import build_run_journey_payload
from services.site_aggregation import build_aggregation_summary
from services.field_submissions import decorate_submission_rows
from services.supervisor_notifications import manager_can_review, summarize_notifications


DEPARTMENT_PAGES = {
    "operations": {
        "title": "Operations",
        "intro": "Run throughput, recent production performance, and extraction workflow metrics.",
        "links": [
            {"label": "Dashboard", "endpoint": "dashboard"},
            {"label": "Runs", "endpoint": "runs_list"},
        ],
    },
    "purchasing": {
        "title": "Purchasing",
        "intro": "Purchasing budget, supplier activity, and inventory commitments tied to biomass intake.",
        "links": [
            {"label": "Purchasing", "endpoint": "biomass_purchasing_dashboard"},
            {"label": "Purchases", "endpoint": "purchases_list"},
            {"label": "Suppliers", "endpoint": "suppliers_list"},
        ],
    },
    "quality": {
        "title": "Quality",
        "intro": "Supplier quality context, field approvals, and test-linked operating data.",
        "links": [
            {"label": "Suppliers", "endpoint": "suppliers_list"},
            {"label": "Field approvals", "endpoint": "field_approvals"},
            {"label": "Strains", "endpoint": "strains_list"},
        ],
    },
}


def register_routes(app, root):
    @root.login_required
    def dashboard():
        return dashboard_view(root)

    @root.login_required
    def dept_index():
        return dept_index_view(root)

    @root.login_required
    def dept_view(slug):
        return dept_view_view(root, slug)

    @root.login_required
    def biomass_purchasing_dashboard():
        return biomass_purchasing_dashboard_view(root)

    @root.login_required
    def alerts_home():
        return alerts_home_view(root)

    @root.login_required
    def journey_home():
        return journey_home_view(root)

    @root.login_required
    def material_genealogy_report():
        return material_genealogy_report_view(root)

    @root.login_required
    def material_genealogy_viewer():
        return material_genealogy_viewer_view(root)

    @root.login_required
    def material_genealogy_raw():
        return material_genealogy_raw_view(root)

    @root.login_required
    def material_genealogy_issue_queue():
        return material_genealogy_issue_queue_view(root)

    @root.login_required
    def material_genealogy_issue_update(issue_id):
        return material_genealogy_issue_update_view(root, issue_id)

    @root.login_required
    def cross_site_ops():
        return cross_site_ops_view(root)

    @root.login_required
    def cross_site_suppliers():
        return cross_site_suppliers_view(root)

    @root.login_required
    def cross_site_strains():
        return cross_site_strains_view(root)

    @root.login_required
    def cross_site_reconciliation():
        return cross_site_reconciliation_view(root)

    @root.login_required
    def supervisor_notification_ack(notification_id):
        return supervisor_notification_ack_view(root, notification_id)

    @root.login_required
    def supervisor_notification_resolve(notification_id):
        return supervisor_notification_resolve_view(root, notification_id)

    @root.login_required
    def supervisor_notification_approve(notification_id):
        return supervisor_notification_approve_view(root, notification_id)

    @root.login_required
    def supervisor_notification_rework(notification_id):
        return supervisor_notification_rework_view(root, notification_id)

    app.add_url_rule("/", endpoint="dashboard", view_func=dashboard)
    app.add_url_rule("/dept", endpoint="dept_index", view_func=dept_index)
    app.add_url_rule("/dept/", endpoint="dept_index_slash", view_func=dept_index)
    app.add_url_rule("/dept/<slug>", endpoint="dept_view", view_func=dept_view)
    app.add_url_rule("/biomass-purchasing", endpoint="biomass_purchasing_dashboard", view_func=biomass_purchasing_dashboard)
    app.add_url_rule("/alerts", endpoint="alerts_home", view_func=alerts_home)
    app.add_url_rule("/journey", endpoint="journey_home", view_func=journey_home)
    app.add_url_rule("/reports/material-genealogy", endpoint="material_genealogy_report", view_func=material_genealogy_report)
    app.add_url_rule("/journeys/material-genealogy", endpoint="material_genealogy_viewer", view_func=material_genealogy_viewer)
    app.add_url_rule("/journeys/material-genealogy/raw", endpoint="material_genealogy_raw", view_func=material_genealogy_raw)
    app.add_url_rule("/reports/material-genealogy/issues", endpoint="material_genealogy_issue_queue", view_func=material_genealogy_issue_queue)
    app.add_url_rule("/reports/material-genealogy/issues/<issue_id>/update", endpoint="material_genealogy_issue_update", view_func=material_genealogy_issue_update, methods=["POST"])
    app.add_url_rule("/cross-site", endpoint="cross_site_ops", view_func=cross_site_ops)
    app.add_url_rule("/cross-site/suppliers", endpoint="cross_site_suppliers", view_func=cross_site_suppliers)
    app.add_url_rule("/cross-site/strains", endpoint="cross_site_strains", view_func=cross_site_strains)
    app.add_url_rule("/cross-site/reconciliation", endpoint="cross_site_reconciliation", view_func=cross_site_reconciliation)
    app.add_url_rule("/supervisor-notifications/<notification_id>/ack", endpoint="supervisor_notification_ack", view_func=supervisor_notification_ack, methods=["POST"])
    app.add_url_rule("/supervisor-notifications/<notification_id>/resolve", endpoint="supervisor_notification_resolve", view_func=supervisor_notification_resolve, methods=["POST"])
    app.add_url_rule("/supervisor-notifications/<notification_id>/approve", endpoint="supervisor_notification_approve", view_func=supervisor_notification_approve, methods=["POST"])
    app.add_url_rule("/supervisor-notifications/<notification_id>/rework", endpoint="supervisor_notification_rework", view_func=supervisor_notification_rework, methods=["POST"])


def _cross_site_ops_enabled(root) -> bool:
    return (root.SystemSetting.get("cross_site_ops_enabled", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _weekly_finance_snapshot(root):
    week_start = purchase_week_start(root.date.today())
    week_end = week_start + root.timedelta(days=6)
    weekly_dollar_budget = root.SystemSetting.get_float("weekly_dollar_budget", 0)

    week_commitment_dollars = root.db.session.query(
        root.func.sum(root.Purchase.total_cost)
    ).filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.purchase_approved_at.isnot(None),
        root.Purchase.purchase_approved_at >= root.datetime.combine(week_start, root.datetime.min.time()),
        root.Purchase.purchase_approved_at < root.datetime.combine(week_end + root.timedelta(days=1), root.datetime.min.time()),
    ).scalar() or 0

    week_purchase_dollars = root.db.session.query(
        root.func.sum(root.Purchase.total_cost)
    ).filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.purchase_date >= week_start,
        root.Purchase.purchase_date <= week_end,
    ).scalar() or 0

    return {
        "week_start": week_start,
        "week_end": week_end,
        "weekly_dollar_budget": float(weekly_dollar_budget or 0),
        "week_commitment_dollars": float(week_commitment_dollars or 0),
        "week_purchase_dollars": float(week_purchase_dollars or 0),
    }


def _department_stat_sections(root, slug: str):
    if slug == "operations":
        runs_30 = root.Run.query.filter(
            root.Run.deleted_at.is_(None),
            root.Run.run_date >= root.date.today() - root.timedelta(days=30),
        ).all()
        total_runs = len(runs_30)
        total_lbs = sum(float(r.bio_in_reactor_lbs or 0) for r in runs_30)
        avg_yield = (
            sum(float(r.overall_yield_pct or 0) for r in runs_30 if r.overall_yield_pct is not None) /
            max(1, sum(1 for r in runs_30 if r.overall_yield_pct is not None))
        ) if runs_30 else 0.0
        return [{
            "title": "30 day snapshot",
            "rows": [
                ("Runs", total_runs),
                ("Biomass processed (lbs)", f"{total_lbs:,.0f}"),
                ("Average overall yield", f"{avg_yield:.2f}%"),
            ],
        }]

    if slug == "purchasing":
        snap = _weekly_finance_snapshot(root)
        on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
            root.Purchase.purchase_approved_at.isnot(None),
        ).scalar() or 0
        return [{
            "title": "This week",
            "rows": [
                ("Weekly $ budget", f"${snap['weekly_dollar_budget']:,.0f}"),
                ("Commitments", f"${snap['week_commitment_dollars']:,.0f}"),
                ("Purchases", f"${snap['week_purchase_dollars']:,.0f}"),
                ("Inventory on hand (lbs)", f"{float(on_hand or 0):,.0f}"),
            ],
        }]

    if slug == "quality":
        pending_submissions = root.FieldPurchaseSubmission.query.filter_by(status="pending").count()
        lab_tests = root.LabTest.query.count()
        active_suppliers = root.Supplier.query.filter_by(is_active=True).count()
        return [{
            "title": "Current state",
            "rows": [
                ("Pending field approvals", pending_submissions),
                ("Lab tests recorded", lab_tests),
                ("Active suppliers", active_suppliers),
            ],
        }]

    return []


def _material_genealogy_sidebar_lots(root, *, active_material_lot_id: str | None):
    lots = (
        root.MaterialLot.query.order_by(root.MaterialLot.created_at.desc(), root.MaterialLot.id.desc())
        .limit(80)
        .all()
    )
    rows = []
    for lot in lots:
        label_bits = [lot.tracking_id or lot.id[:8], lot.lot_type.replace("_", " ")]
        if lot.strain_name_snapshot:
            label_bits.append(lot.strain_name_snapshot)
        rows.append(
            {
                "material_lot_id": lot.id,
                "tracking_id": lot.tracking_id or lot.id[:8],
                "lot_type": lot.lot_type,
                "strain_name": lot.strain_name_snapshot,
                "supplier_name": lot.supplier_name_snapshot,
                "quantity_label": f"{float(lot.quantity or 0):,.2f} {lot.unit or ''}".strip(),
                "status_label": (lot.inventory_status or "open").replace("_", " "),
                "search_text": " ".join(bit for bit in label_bits if bit).lower(),
                "url": root.url_for("material_genealogy_viewer", mode="lot", material_lot_id=lot.id),
                "active": lot.id == active_material_lot_id,
            }
        )
    return rows


def _material_genealogy_sidebar_runs(root, *, active_run_id: str | None):
    runs = (
        root.Run.query.filter(root.Run.deleted_at.is_(None))
        .order_by(root.Run.run_date.desc(), root.Run.created_at.desc(), root.Run.id.desc())
        .limit(80)
        .all()
    )
    rows = []
    for run in runs:
        source_tracking = [row.lot.tracking_id for row in run.inputs.limit(3).all() if row.lot and row.lot.tracking_id]
        search_bits = [f"reactor {run.reactor_number}", run.id]
        search_bits.extend(source_tracking)
        rows.append(
            {
                "run_id": run.id,
                "reactor_number": run.reactor_number,
                "run_date_label": run.run_date.strftime("%Y-%m-%d") if run.run_date else "Unknown date",
                "input_label": f"{float(run.bio_in_reactor_lbs or 0):,.1f} lbs",
                "source_label": ", ".join(source_tracking) if source_tracking else "No source lots linked",
                "search_text": " ".join(bit for bit in search_bits if bit).lower(),
                "url": root.url_for("material_genealogy_viewer", mode="run", run_id=run.id),
                "active": run.id == active_run_id,
            }
        )
    return rows


def _material_issue_assignment_options(root):
    users = (
        root.User.query.filter_by(is_active_user=True)
        .order_by(root.User.display_name.asc(), root.User.username.asc())
        .all()
    )
    options = [{"value": "", "label": "Unassigned"}]
    for user in users:
        if getattr(user, "can_edit", False):
            options.append({"value": user.id, "label": user.display_name})
    return options


def _material_issue_history(root, issue, *, limit: int = 5):
    rows = (
        root.AuditLog.query.filter_by(entity_type="material_reconciliation_issue", entity_id=issue.id)
        .order_by(root.AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    history = []
    for row in rows:
        details = {}
        try:
            details = root.json.loads(row.details or "{}")
        except Exception:
            details = {}
        history.append(
            {
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "action": row.action,
                "user_name": row.user.display_name if row.user else None,
                "details": details,
            }
        )
    return history


def _journey_home_payload(root):
    report = build_material_reporting_payload(root)
    queue_reporting = root.downstream_state_payload(root).get("reporting", {})
    recent_run_rows = report.get("run_yield_rows", [])[:6]
    open_mix = report.get("open_inventory_groups", [])[:6]
    released_mix = report.get("released_inventory_groups", [])[:6]
    return {
        "report": report,
        "queue_reporting": queue_reporting,
        "recent_run_rows": recent_run_rows,
        "open_mix": open_mix,
        "released_mix": released_mix,
    }


def _supervisor_notifications_redirect(root):
    target = (root.request.form.get("return_to") or root.request.args.get("return_to") or "").strip()
    if target.startswith("/"):
        return root.redirect(target)
    return root.redirect(f"{root.url_for('dashboard')}#supervisor-notifications")


def _require_supervisor_notification_access(root):
    if not manager_can_review(root.current_user):
        root.flash("Supervisor notification access required.", "error")
        return _supervisor_notifications_redirect(root)
    return None


def dashboard_view(root):
    period = root.request.args.get("period", "30")
    if period == "today":
        start_date = root.date.today()
    elif period == "7":
        start_date = root.date.today() - root.timedelta(days=7)
    elif period == "90":
        start_date = root.date.today() - root.timedelta(days=90)
    elif period == "all":
        start_date = root.date(2020, 1, 1)
    else:
        start_date = root.date.today() - root.timedelta(days=30)

    exclude_unpriced = root._exclude_unpriced_batches_enabled()
    runs_q = root.Run.query.filter(root.Run.deleted_at.is_(None), root.Run.run_date >= start_date)
    if exclude_unpriced:
        runs_q = runs_q.filter(root._priced_run_filter())
    runs = runs_q.all()

    kpi_actuals = {}
    if runs:
        yields = [r.overall_yield_pct for r in runs if r.overall_yield_pct]
        thca_yields = [r.thca_yield_pct for r in runs if r.thca_yield_pct]
        hte_yields = [r.hte_yield_pct for r in runs if r.hte_yield_pct]
        costs = [r.cost_per_gram_combined for r in runs if r.cost_per_gram_combined]
        costs_thca = [r.cost_per_gram_thca for r in runs if r.cost_per_gram_thca is not None]
        costs_hte = [r.cost_per_gram_hte for r in runs if r.cost_per_gram_hte is not None]
        total_lbs = sum(r.bio_in_reactor_lbs or 0 for r in runs)

        kpi_actuals["thca_yield_pct"] = sum(thca_yields) / len(thca_yields) if thca_yields else None
        kpi_actuals["hte_yield_pct"] = sum(hte_yields) / len(hte_yields) if hte_yields else None
        kpi_actuals["overall_yield_pct"] = sum(yields) / len(yields) if yields else None
        kpi_actuals["cost_per_gram_combined"] = sum(costs) / len(costs) if costs else None
        kpi_actuals["cost_per_gram_thca"] = sum(costs_thca) / len(costs_thca) if costs_thca else None
        kpi_actuals["cost_per_gram_hte"] = sum(costs_hte) / len(costs_hte) if costs_hte else None

        days_in_period = max((root.date.today() - start_date).days, 1)
        weeks = max(days_in_period / 7, 1)
        kpi_actuals["weekly_throughput"] = total_lbs / weeks

        daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
        on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
            root.Purchase.purchase_approved_at.isnot(None),
        ).scalar() or 0
        kpi_actuals["days_of_supply"] = on_hand / daily_target if daily_target > 0 else 0

        purchase_ids = root.db.session.query(root.Purchase.id).join(
            root.PurchaseLot, root.PurchaseLot.purchase_id == root.Purchase.id
        ).join(
            root.RunInput, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Run, root.Run.id == root.RunInput.run_id
        ).filter(
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
            root.Run.run_date >= start_date,
        ).distinct().all()
        purchase_ids = [pid for (pid,) in purchase_ids]
        purchases_in_period = root.Purchase.query.filter(root.Purchase.id.in_(purchase_ids)).all() if purchase_ids else []
        potency_costs = []
        for purchase in purchases_in_period:
            potency = purchase.tested_potency_pct or purchase.stated_potency_pct
            if purchase.price_per_lb and potency and potency > 0:
                potency_costs.append(purchase.price_per_lb / potency)
        kpi_actuals["cost_per_potency_point"] = sum(potency_costs) / len(potency_costs) if potency_costs else None

    kpis = root.KpiTarget.query.all()
    kpi_cards = []
    for kpi in kpis:
        actual = kpi_actuals.get(kpi.kpi_name)
        kpi_cards.append({
            "name": kpi.display_name,
            "target": kpi.target_value,
            "actual": actual,
            "color": kpi.evaluate(actual),
            "unit": kpi.unit or "",
            "direction": kpi.direction,
        })

    total_runs = len(runs)
    total_lbs = sum(r.bio_in_reactor_lbs or 0 for r in runs)
    total_dry_output = sum((r.dry_hte_g or 0) + (r.dry_thca_g or 0) for r in runs)
    on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
        root.PurchaseLot.remaining_weight_lbs > 0,
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        root.Purchase.purchase_approved_at.isnot(None),
    ).scalar() or 0

    week_start = root.date.today() - root.timedelta(days=root.date.today().weekday())
    wtd_runs_q = root.Run.query.filter(
        root.Run.deleted_at.is_(None),
        root.Run.run_date >= week_start,
        root.Run.run_date <= root.date.today(),
    )
    if exclude_unpriced:
        wtd_runs_q = wtd_runs_q.filter(root._priced_run_filter())
    wtd_runs = wtd_runs_q.all()
    wtd_lbs = sum(r.bio_in_reactor_lbs or 0 for r in wtd_runs)
    wtd_dry_thca = sum(r.dry_thca_g or 0 for r in wtd_runs)
    wtd_dry_hte = sum(r.dry_hte_g or 0 for r in wtd_runs)

    current_month_start = root.date.today().replace(day=1)
    prev_month_end = current_month_start - root.timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    mom_query = root.db.session.query(
        root.Supplier.id.label("supplier_id"),
        root.Supplier.name.label("supplier_name"),
        root.func.avg(root.Run.overall_yield_pct).label("avg_yield"),
    ).join(
        root.Purchase, root.Purchase.supplier_id == root.Supplier.id
    ).join(
        root.PurchaseLot, root.PurchaseLot.purchase_id == root.Purchase.id
    ).join(
        root.RunInput, root.RunInput.lot_id == root.PurchaseLot.id
    ).join(
        root.Run, root.Run.id == root.RunInput.run_id
    ).filter(
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
        root.Run.is_rollover == False,
        root.Run.run_date >= current_month_start,
        root.Run.overall_yield_pct.isnot(None),
    )
    if exclude_unpriced:
        mom_query = mom_query.filter(root._priced_run_filter())
    mom_rows = mom_query.group_by(root.Supplier.id, root.Supplier.name).all()
    best_supplier_mom = None
    if mom_rows:
        best = max(mom_rows, key=lambda row: float(row.avg_yield or 0))
        prev = root.db.session.query(root.func.avg(root.Run.overall_yield_pct)).join(
            root.RunInput, root.Run.id == root.RunInput.run_id
        ).join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
        ).filter(
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
            root.Run.is_rollover == False,
            root.Purchase.supplier_id == best.supplier_id,
            root.Run.run_date >= prev_month_start,
            root.Run.run_date <= prev_month_end,
        )
        if exclude_unpriced:
            prev = prev.filter(root._priced_run_filter())
        prev_avg = prev.scalar()
        best_supplier_mom = {
            "name": best.supplier_name,
            "current": float(best.avg_yield or 0),
            "previous": float(prev_avg or 0) if prev_avg is not None else None,
        }
        if best_supplier_mom["previous"] and best_supplier_mom["previous"] > 0:
            best_supplier_mom["pct_change"] = ((best_supplier_mom["current"] - best_supplier_mom["previous"]) / best_supplier_mom["previous"]) * 100.0
        else:
            best_supplier_mom["pct_change"] = None

    fin = _weekly_finance_snapshot(root)
    supervisor_notifications = summarize_notifications(root, limit=12) if manager_can_review(root.current_user) else {"open_count": 0, "critical_count": 0, "warning_count": 0, "info_count": 0, "rows": []}
    return root.render_template(
        "dashboard.html",
        kpi_cards=kpi_cards,
        period=period,
        total_runs=total_runs,
        total_lbs=total_lbs,
        total_dry_output=total_dry_output,
        on_hand=on_hand,
        exclude_unpriced=exclude_unpriced,
        wtd_lbs=wtd_lbs,
        wtd_dry_thca=wtd_dry_thca,
        wtd_dry_hte=wtd_dry_hte,
        best_supplier_mom=best_supplier_mom,
        week_start=fin["week_start"],
        week_end=fin["week_end"],
        weekly_dollar_budget=fin["weekly_dollar_budget"],
        week_commitment_dollars=fin["week_commitment_dollars"],
        week_purchase_dollars=fin["week_purchase_dollars"],
        supervisor_notifications=supervisor_notifications,
    )


def supervisor_notification_ack_view(root, notification_id):
    denied = _require_supervisor_notification_access(root)
    if denied is not None:
        return denied
    row = root.db.session.get(root.SupervisorNotification, notification_id)
    if row is None:
        root.flash("Supervisor notification not found.", "error")
        return _supervisor_notifications_redirect(root)
    row.status = "acknowledged"
    row.acknowledged_at = root.datetime.now(root.timezone.utc)
    row.acknowledged_by_user_id = root.current_user.id
    root.db.session.commit()
    root.flash("Supervisor notification acknowledged.", "success")
    return _supervisor_notifications_redirect(root)


def supervisor_notification_resolve_view(root, notification_id):
    denied = _require_supervisor_notification_access(root)
    if denied is not None:
        return denied
    row = root.db.session.get(root.SupervisorNotification, notification_id)
    if row is None:
        root.flash("Supervisor notification not found.", "error")
        return _supervisor_notifications_redirect(root)
    row.status = "resolved"
    row.resolved_at = root.datetime.now(root.timezone.utc)
    row.resolved_by_user_id = root.current_user.id
    row.resolution_note = (root.request.form.get("resolution_note") or "").strip() or row.resolution_note
    root.db.session.commit()
    root.flash("Supervisor notification resolved.", "success")
    return _supervisor_notifications_redirect(root)


def supervisor_notification_approve_view(root, notification_id):
    denied = _require_supervisor_notification_access(root)
    if denied is not None:
        return denied
    row = root.db.session.get(root.SupervisorNotification, notification_id)
    if row is None:
        root.flash("Supervisor notification not found.", "error")
        return _supervisor_notifications_redirect(root)
    override_reason = (root.request.form.get("override_reason") or "").strip()
    if not override_reason:
        root.flash("Override reason is required to approve a deviation.", "error")
        return _supervisor_notifications_redirect(root)
    now = root.datetime.now(root.timezone.utc)
    row.override_decision = "approved_deviation"
    row.override_reason = override_reason
    row.override_at = now
    row.override_by_user_id = root.current_user.id
    row.status = "resolved"
    row.resolved_at = now
    row.resolved_by_user_id = root.current_user.id
    row.resolution_note = override_reason
    root.db.session.commit()
    root.flash("Deviation approved and recorded.", "success")
    return _supervisor_notifications_redirect(root)


def supervisor_notification_rework_view(root, notification_id):
    denied = _require_supervisor_notification_access(root)
    if denied is not None:
        return denied
    row = root.db.session.get(root.SupervisorNotification, notification_id)
    if row is None:
        root.flash("Supervisor notification not found.", "error")
        return _supervisor_notifications_redirect(root)
    override_reason = (root.request.form.get("override_reason") or "").strip()
    if not override_reason:
        root.flash("Override reason is required to require rework.", "error")
        return _supervisor_notifications_redirect(root)
    now = root.datetime.now(root.timezone.utc)
    row.override_decision = "require_rework"
    row.override_reason = override_reason
    row.override_at = now
    row.override_by_user_id = root.current_user.id
    row.status = "acknowledged"
    row.acknowledged_at = row.acknowledged_at or now
    row.acknowledged_by_user_id = row.acknowledged_by_user_id or root.current_user.id
    row.resolution_note = None
    root.db.session.commit()
    root.flash("Rework required and recorded.", "success")
    return _supervisor_notifications_redirect(root)


def dept_index_view(root):
    return root.render_template("dept_index.html", departments=DEPARTMENT_PAGES)


def dept_view_view(root, slug):
    cfg = DEPARTMENT_PAGES.get(slug)
    if not cfg:
        root.abort(404)
    stat_sections = _department_stat_sections(root, slug)
    return root.render_template("dept_view.html", slug=slug, dept=cfg, stat_sections=stat_sections)


def biomass_purchasing_dashboard_view(root):
    today = root.date.today()
    current_monday = purchase_week_start(today)
    weekly_budget_usd = root.SystemSetting.get_float("biomass_purchase_weekly_budget_usd", 0)
    weekly_target_lbs = root.SystemSetting.get_float("biomass_purchase_weekly_target_lbs", 0)
    target_pot = root.SystemSetting.get_float("biomass_purchase_weekly_target_potency_pct", 0)
    if target_pot <= 0:
        target_pot = root.SystemSetting.get_float("biomass_budget_target_potency_pct", 0)

    weeks = []
    for offset in (-2, -1, 0, 1, 2):
        ws = current_monday + root.timedelta(weeks=offset)
        we = ws + root.timedelta(days=6)
        metrics = budget_week_purchase_metrics(ws, we)
        avg_pot = (metrics["weighted_pot_sum"] / metrics["lbs"]) if metrics["lbs"] > 1e-9 else None
        if offset == -2:
            bucket_label = "2 wks ago"
        elif offset == -1:
            bucket_label = "Last week"
        elif offset == 0:
            bucket_label = "This week"
        elif offset == 1:
            bucket_label = "Next week"
        else:
            bucket_label = "In 2 wks"
        weeks.append({
            "offset": offset,
            "bucket_label": bucket_label,
            "week_start": ws,
            "week_end": we,
            "range_label": f"{ws.strftime('%b %d')} - {we.strftime('%b %d, %Y')}",
            "is_current": offset == 0,
            "is_past": ws < current_monday,
            "is_future": ws > current_monday,
            **metrics,
            "avg_potency_pct": avg_pot,
            "spend_variance_usd": (metrics["spend"] - weekly_budget_usd) if weekly_budget_usd > 0 else None,
            "lbs_variance": (metrics["lbs"] - weekly_target_lbs) if weekly_target_lbs > 0 else None,
            "potency_variance_pct": (avg_pot - target_pot) if (target_pot > 0 and avg_pot is not None) else None,
        })

    pending = root.FieldPurchaseSubmission.query.filter_by(status="pending").order_by(root.FieldPurchaseSubmission.submitted_at.desc()).all()
    reviewed = root.FieldPurchaseSubmission.query.filter(
        root.FieldPurchaseSubmission.status.in_(("approved", "rejected"))
    ).order_by(root.FieldPurchaseSubmission.submitted_at.desc()).all()
    decorate_submission_rows(pending + reviewed)
    return root.render_template(
        "biomass_purchasing_dashboard.html",
        weeks=weeks,
        weekly_budget_usd=weekly_budget_usd,
        weekly_target_lbs=weekly_target_lbs,
        weekly_target_potency_pct=target_pot if target_pot > 0 else None,
        field_submissions=pending,
        reviewed_field_submissions=reviewed,
        submission_return_to="biomass-purchasing",
        show_submission_approval_buttons=root.current_user.can_approve_field_purchases,
        pending_submissions_total_lbs=sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in pending),
        reviewed_approved_total_lbs=sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in reviewed if s.status == "approved"),
        reviewed_rejected_total_lbs=sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in reviewed if s.status == "rejected"),
    )


def alerts_home_view(root):
    supervisor_notifications = summarize_notifications(root, limit=12) if manager_can_review(root.current_user) else {"open_count": 0, "critical_count": 0, "warning_count": 0, "info_count": 0, "rows": []}
    active_issues = (
        root.MaterialReconciliationIssue.query.filter(root.MaterialReconciliationIssue.status.in_(ACTIVE_MATERIAL_ISSUE_STATUSES))
        .order_by(root.MaterialReconciliationIssue.detected_at.desc())
        .limit(12)
        .all()
    )
    issue_rows = [serialize_reconciliation_issue(root, issue) for issue in active_issues]
    return root.render_template(
        "alerts_home.html",
        supervisor_notifications=supervisor_notifications,
        issue_rows=issue_rows,
        issue_counts={
            "open": root.MaterialReconciliationIssue.query.filter_by(status="open").count(),
            "investigating": root.MaterialReconciliationIssue.query.filter_by(status="investigating").count(),
            "needs_follow_up": root.MaterialReconciliationIssue.query.filter_by(status="needs_follow_up").count(),
            "critical": root.MaterialReconciliationIssue.query.filter_by(severity="critical").count(),
        },
    )


def journey_home_view(root):
    process_material_issue_reminders(root)
    payload = _journey_home_payload(root)
    return root.render_template(
        "journey_home.html",
        journey=payload,
    )


def material_genealogy_report_view(root):
    process_material_issue_reminders(root)
    payload = root._build_material_reporting_payload(root)
    return root.render_template("material_genealogy_report.html", report=payload)


def material_genealogy_viewer_view(root):
    process_material_issue_reminders(root)
    mode = (root.request.args.get("mode") or "lot").strip().lower()
    if mode not in {"lot", "run"}:
        mode = "lot"

    selected_material_lot_id = (root.request.args.get("material_lot_id") or "").strip() or None
    selected_run_id = (root.request.args.get("run_id") or "").strip() or None

    selected_material_lot = root.db.session.get(root.MaterialLot, selected_material_lot_id) if selected_material_lot_id else None
    selected_run = root.db.session.get(root.Run, selected_run_id) if selected_run_id else None
    if selected_run is not None and selected_run.deleted_at is not None:
        selected_run = None

    sidebar_lots = _material_genealogy_sidebar_lots(root, active_material_lot_id=selected_material_lot_id)
    sidebar_runs = _material_genealogy_sidebar_runs(root, active_run_id=selected_run_id)

    if mode == "lot" and selected_material_lot is None and sidebar_lots:
        selected_material_lot_id = sidebar_lots[0]["material_lot_id"]
        selected_material_lot = root.db.session.get(root.MaterialLot, selected_material_lot_id)
        for row in sidebar_lots:
            row["active"] = row["material_lot_id"] == selected_material_lot_id
    if mode == "run" and selected_run is None and sidebar_runs:
        selected_run_id = sidebar_runs[0]["run_id"]
        selected_run = root.db.session.get(root.Run, selected_run_id)
        for row in sidebar_runs:
            row["active"] = row["run_id"] == selected_run_id

    lot_view = None
    run_view = None
    if selected_material_lot is not None:
        lot_detail = build_material_lot_detail_payload(root, selected_material_lot)
        lot_journey = build_material_lot_journey_payload(root, selected_material_lot)
        correction_history = [
            row for row in (lot_detail.get("downstream_transformations") or [])
            if (row.get("transformation_type") or "").startswith("correction_")
        ]
        lot_view = {
            "detail": lot_detail,
            "journey": lot_journey,
            "open_run_url": lot_detail["material_lot"]["links"].get("run_url"),
            "open_purchase_url": lot_detail["material_lot"]["links"].get("purchase_url"),
            "open_run_journey_url": root.url_for("material_genealogy_viewer", mode="run", run_id=selected_material_lot.parent_run_id)
            if selected_material_lot.parent_run_id
            else None,
            "correction_url": root.url_for(
                "material_lot_correct",
                lot_id=selected_material_lot.id,
                return_to=root.url_for("material_genealogy_viewer", mode="lot", material_lot_id=selected_material_lot.id),
            ),
            "correction_history": correction_history,
        }
    if selected_run is not None:
        run_journey = build_run_journey_payload(selected_run)
        run_issues = [
            issue
            for issue in selected_run.material_reconciliation_issues.order_by(root.MaterialReconciliationIssue.detected_at.desc()).all()
        ]
        run_view = {
            "journey": run_journey,
            "material_lot_urls": {
                lot["material_lot_id"]: root.url_for("material_genealogy_viewer", mode="lot", material_lot_id=lot["material_lot_id"])
                for lot in run_journey.get("material_lots", [])
            },
            "issues": [serialize_reconciliation_issue(root, issue) for issue in run_issues],
        }

    return root.render_template(
        "material_genealogy_viewer.html",
        mode=mode,
        sidebar_lots=sidebar_lots,
        sidebar_runs=sidebar_runs,
        lot_view=lot_view,
        run_view=run_view,
    )


def material_genealogy_raw_view(root):
    entity_type = (root.request.args.get("entity_type") or "").strip().lower()
    payload_kind = (root.request.args.get("payload") or "journey").strip().lower()

    payload = None
    if entity_type == "run":
        run_id = (root.request.args.get("run_id") or "").strip()
        run = root.db.session.get(root.Run, run_id) if run_id else None
        if run is None or run.deleted_at is not None:
            root.abort(404)
        if payload_kind != "journey":
            root.abort(400)
        payload = build_run_journey_payload(run)
    elif entity_type == "material_lot":
        material_lot_id = (root.request.args.get("material_lot_id") or "").strip()
        material_lot = root.db.session.get(root.MaterialLot, material_lot_id) if material_lot_id else None
        if material_lot is None:
            root.abort(404)
        if payload_kind == "detail":
            payload = build_material_lot_detail_payload(root, material_lot)
        elif payload_kind == "journey":
            payload = build_material_lot_journey_payload(root, material_lot)
        elif payload_kind == "ancestry":
            payload = build_material_lot_ancestry_payload(root, material_lot)
        elif payload_kind == "descendants":
            payload = build_material_lot_descendants_payload(root, material_lot)
        else:
            root.abort(400)
    else:
        root.abort(400)

    return root.Response(
        json.dumps(payload, indent=2, sort_keys=True),
        mimetype="application/json",
    )


def material_genealogy_issue_queue_view(root):
    if not getattr(root.current_user, "can_edit", False):
        root.flash("Edit access is required for genealogy issue management.", "error")
        return root.redirect(root.url_for("material_genealogy_report"))

    process_material_issue_reminders(root)
    status_filter = (root.request.args.get("status") or "active").strip().lower()
    severity_filter = (root.request.args.get("severity") or "all").strip().lower()
    owner_filter = (root.request.args.get("owner") or "all").strip()
    age_filter = (root.request.args.get("age") or "all").strip().lower()
    query = root.MaterialReconciliationIssue.query.order_by(
        root.MaterialReconciliationIssue.detected_at.desc(),
        root.MaterialReconciliationIssue.id.desc(),
    )
    if status_filter == "active":
        query = query.filter(root.MaterialReconciliationIssue.status.in_(ACTIVE_MATERIAL_ISSUE_STATUSES))
    elif status_filter == "resolved":
        query = query.filter(root.MaterialReconciliationIssue.status == "resolved")
    if severity_filter in {"warning", "critical"}:
        query = query.filter(root.MaterialReconciliationIssue.severity == severity_filter)
    if owner_filter == "unassigned":
        query = query.filter(root.MaterialReconciliationIssue.assignee_user_id.is_(None))
    elif owner_filter not in {"", "all"}:
        query = query.filter(root.MaterialReconciliationIssue.assignee_user_id == owner_filter)

    issues = query.limit(200).all()
    status_counts = {
        "open": root.MaterialReconciliationIssue.query.filter_by(status="open").count(),
        "investigating": root.MaterialReconciliationIssue.query.filter_by(status="investigating").count(),
        "needs_follow_up": root.MaterialReconciliationIssue.query.filter_by(status="needs_follow_up").count(),
        "resolved": root.MaterialReconciliationIssue.query.filter_by(status="resolved").count(),
    }
    severity_counts = {
        "warning": root.MaterialReconciliationIssue.query.filter_by(severity="warning").count(),
        "critical": root.MaterialReconciliationIssue.query.filter_by(severity="critical").count(),
    }
    issue_rows = []
    now = root.datetime.now(root.timezone.utc)
    for issue in issues:
        reminder = issue_reminder_snapshot(root, issue, now=now)
        age_days = reminder["age_days"] if issue.detected_at is not None else None
        if age_filter == "overdue" and not reminder["overdue"]:
            continue
        if age_filter == "7_plus" and reminder["age_days"] < 7:
            continue
        if age_filter == "30_plus" and reminder["age_days"] < 30:
            continue
        issue_rows.append(
            {
                "issue": serialize_reconciliation_issue(root, issue),
                "run_view_url": root.url_for("material_genealogy_viewer", mode="run", run_id=issue.run_id) if issue.run_id else None,
                "lot_view_url": root.url_for("material_genealogy_viewer", mode="lot", material_lot_id=issue.material_lot_id) if issue.material_lot_id else None,
                "assignee_name": issue.assignee_user.display_name if issue.assignee_user else None,
                "assigned_at": issue.assigned_at.isoformat() if issue.assigned_at else None,
                "age_days": age_days,
                "reminder": reminder,
                "history": _material_issue_history(root, issue),
            }
        )

    return root.render_template(
        "material_genealogy_issue_queue.html",
        issues=issue_rows,
        status_filter=status_filter,
        severity_filter=severity_filter,
        owner_filter=owner_filter,
        age_filter=age_filter,
        status_counts=status_counts,
        severity_counts=severity_counts,
        overdue_count=sum(1 for row in issue_rows if row["reminder"]["overdue"]),
        assignment_options=_material_issue_assignment_options(root),
    )


def material_genealogy_issue_update_view(root, issue_id):
    if not getattr(root.current_user, "can_edit", False):
        root.flash("Edit access is required for genealogy issue management.", "error")
        return root.redirect(root.url_for("material_genealogy_report"))

    issue = root.db.session.get(root.MaterialReconciliationIssue, issue_id)
    if issue is None:
        root.abort(404)

    action = (root.request.form.get("action") or "save").strip().lower()
    requested_assignee_id = (root.request.form.get("assignee_user_id") or "").strip()
    working_note = (root.request.form.get("working_note") or "").strip() or None
    assignee = root.db.session.get(root.User, requested_assignee_id) if requested_assignee_id else None
    if requested_assignee_id and (assignee is None or not assignee.is_active_user or not getattr(assignee, "can_edit", False)):
        root.flash("Choose a valid issue owner.", "error")
        return root.redirect(root.url_for("material_genealogy_issue_queue"))

    try:
        apply_material_issue_action(
            root,
            issue,
            action=action,
            note=working_note,
            assignee_user_id=assignee.id if assignee is not None else "",
            acting_user_id=getattr(root.current_user, "id", None),
        )
        root.db.session.commit()
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("material_genealogy_issue_queue"))

    flash_map = {
        "resolved": "Genealogy issue resolved.",
        "reopen": "Genealogy issue reopened.",
        "investigating": "Genealogy issue marked investigating.",
        "needs_follow_up": "Genealogy issue marked for follow-up.",
        "save": "Genealogy issue updated.",
    }
    root.flash(flash_map.get(action, "Genealogy issue updated."), "success")
    return root.redirect(
        root.url_for(
            "material_genealogy_issue_queue",
            status=root.request.form.get("return_status") or "active",
            severity=root.request.form.get("return_severity") or "all",
            owner=root.request.form.get("return_owner") or "all",
            age=root.request.form.get("return_age") or "all",
        )
    )


def cross_site_ops_view(root):
    if not _cross_site_ops_enabled(root):
        root.abort(404)

    from gold_drop import api_v1_module as api_module

    period = (root.request.args.get("period") or "30").strip().lower()
    if period not in {"today", "7", "30", "90", "all"}:
        period = "30"

    slack_payload, slack_error = api_module._slack_imports_summary_payload(root)
    if slack_error is not None:
        slack_payload = {
            "total_messages": 0,
            "bucket_counts": {},
            "linked_count": 0,
            "unlinked_count": 0,
            "coverage_counts": {},
        }

    payload = build_aggregation_summary(
        get_site_identity(),
        local_dashboard=api_module._dashboard_summary_payload(root, period),
        local_inventory=api_module._inventory_summary_payload(root, supplier_id=None, strain=None),
        local_exceptions=api_module._exceptions_summary_payload(root),
        local_slack=slack_payload,
    )
    sites = payload.get("sites") or []
    stale_sites = [
        site for site in sites
        if site.get("source") == "remote_cache" and site.get("status") not in {"success", "local"}
    ]
    return root.render_template(
        "cross_site_ops.html",
        page_title="Cross-Site Ops",
        period=period,
        payload=payload,
        sites=sites,
        stale_sites=stale_sites,
    )


def cross_site_suppliers_view(root):
    if not _cross_site_ops_enabled(root):
        root.abort(404)

    from gold_drop import api_v1_module as api_module

    query_text = (root.request.args.get("q") or "").strip()
    with root.app.test_request_context(
        "/internal/cross-site/suppliers",
        query_string={"q": query_text, "limit": "500", "offset": "0"},
    ):
        payload = api_module.api_v1_aggregation_suppliers.__wrapped__().get_json()["data"]

    rows = sorted(
        payload,
        key=lambda item: float(((item.get("all_time") or {}).get("yield")) or 0),
        reverse=True,
    )
    best_row = rows[0] if rows else None
    incomplete_count = sum(1 for row in rows if row.get("profile_incomplete"))
    return root.render_template(
        "cross_site_suppliers.html",
        page_title="Cross-Site Supplier Comparison",
        query_text=query_text,
        rows=rows,
        best_row=best_row,
        incomplete_count=incomplete_count,
    )


def cross_site_strains_view(root):
    if not _cross_site_ops_enabled(root):
        root.abort(404)

    from gold_drop import api_v1_module as api_module

    query_text = (root.request.args.get("q") or "").strip()
    supplier_name = (root.request.args.get("supplier_name") or "").strip()
    with root.app.test_request_context(
        "/internal/cross-site/strains",
        query_string={"q": query_text, "supplier_name": supplier_name, "limit": "500", "offset": "0"},
    ):
        payload = api_module.api_v1_aggregation_strains.__wrapped__().get_json()["data"]

    rows = sorted(
        payload,
        key=lambda item: float(item.get("avg_yield") or 0),
        reverse=True,
    )
    best_row = rows[0] if rows else None
    return root.render_template(
        "cross_site_strains.html",
        page_title="Cross-Site Strain Comparison",
        query_text=query_text,
        supplier_name=supplier_name,
        rows=rows,
        best_row=best_row,
    )


def cross_site_reconciliation_view(root):
    if not _cross_site_ops_enabled(root):
        root.abort(404)

    from gold_drop import api_v1_module as api_module

    slack_payload, slack_error = api_module._slack_imports_summary_payload(root)
    if slack_error is not None:
        slack_payload = {
            "total_messages": 0,
            "bucket_counts": {},
            "linked_count": 0,
            "unlinked_count": 0,
            "coverage_counts": {},
        }

    payload = build_aggregation_summary(
        get_site_identity(),
        local_dashboard=api_module._dashboard_summary_payload(root, "30"),
        local_inventory=api_module._inventory_summary_payload(root, supplier_id=None, strain=None),
        local_exceptions=api_module._exceptions_summary_payload(root),
        local_slack=slack_payload,
    )
    sites = payload.get("sites") or []
    rows = []
    for site in sites:
        exceptions = site.get("exceptions") or {}
        slack_imports = site.get("slack_imports") or {}
        rows.append(
            {
                "site": site,
                "total_exceptions": int(exceptions.get("total_exceptions") or 0),
                "total_messages": int(slack_imports.get("total_messages") or 0),
                "needs_manual_match": int((slack_imports.get("bucket_counts") or {}).get("needs_manual_match") or 0),
                "blocked": int((slack_imports.get("bucket_counts") or {}).get("blocked") or 0),
                "coverage_none": int((slack_imports.get("coverage_counts") or {}).get("none") or 0),
            }
        )
    rows.sort(key=lambda row: (row["total_exceptions"], row["needs_manual_match"], row["blocked"]), reverse=True)
    return root.render_template(
        "cross_site_reconciliation.html",
        page_title="Cross-Site Reconciliation",
        rows=rows,
    )
