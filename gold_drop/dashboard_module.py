from __future__ import annotations


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

    app.add_url_rule("/", endpoint="dashboard", view_func=dashboard)
    app.add_url_rule("/dept", endpoint="dept_index", view_func=dept_index)
    app.add_url_rule("/dept/", endpoint="dept_index_slash", view_func=dept_index)
    app.add_url_rule("/dept/<slug>", endpoint="dept_view", view_func=dept_view)
    app.add_url_rule("/biomass-purchasing", endpoint="biomass_purchasing_dashboard", view_func=biomass_purchasing_dashboard)


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

    fin = root._weekly_finance_snapshot()
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
    )


def dept_index_view(root):
    return root.render_template("dept_index.html", departments=root.DEPARTMENT_PAGES)


def dept_view_view(root, slug):
    cfg = root.DEPARTMENT_PAGES.get(slug)
    if not cfg:
        root.abort(404)
    stat_sections = root._department_stat_sections(slug)
    return root.render_template("dept_view.html", slug=slug, dept=cfg, stat_sections=stat_sections)


def biomass_purchasing_dashboard_view(root):
    today = root.date.today()
    current_monday = root._purchase_week_start(today)
    weekly_budget_usd = root.SystemSetting.get_float("biomass_purchase_weekly_budget_usd", 0)
    weekly_target_lbs = root.SystemSetting.get_float("biomass_purchase_weekly_target_lbs", 0)
    target_pot = root.SystemSetting.get_float("biomass_purchase_weekly_target_potency_pct", 0)
    if target_pot <= 0:
        target_pot = root.SystemSetting.get_float("biomass_budget_target_potency_pct", 0)

    weeks = []
    for offset in (-2, -1, 0, 1, 2):
        ws = current_monday + root.timedelta(weeks=offset)
        we = ws + root.timedelta(days=6)
        metrics = root._budget_week_purchase_metrics(ws, we)
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
    root._decorate_field_submission_rows(pending + reviewed)
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
