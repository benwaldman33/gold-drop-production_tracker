from __future__ import annotations


def register_routes(app, root):
    @root.login_required
    def strains_list():
        return strains_list_view(root)

    app.add_url_rule("/strains", endpoint="strains_list", view_func=strains_list)


def strains_list_view(root):
    redir = root._list_filters_clear_redirect("strains_list")
    if redir:
        return redir
    m = root._list_filters_merge("strains_list", ("view",))
    view = (m.get("view") or "all").strip() or "all"

    query = root.db.session.query(
        root.PurchaseLot.strain_name,
        root.Supplier.name.label("supplier_name"),
        root.func.avg(root.Run.overall_yield_pct).label("avg_yield"),
        root.func.avg(root.Run.thca_yield_pct).label("avg_thca"),
        root.func.avg(root.Run.hte_yield_pct).label("avg_hte"),
        root.func.avg(root.Run.cost_per_gram_combined).label("avg_cpg"),
        root.func.count(root.Run.id).label("run_count"),
        root.func.sum(root.Run.bio_in_reactor_lbs).label("total_lbs"),
        root.func.sum(root.Run.dry_thca_g).label("total_thca_g"),
        root.func.sum(root.Run.dry_hte_g).label("total_hte_g"),
    ).join(
        root.RunInput, root.PurchaseLot.id == root.RunInput.lot_id
    ).join(
        root.Run, root.RunInput.run_id == root.Run.id
    ).join(
        root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
    ).join(
        root.Supplier, root.Purchase.supplier_id == root.Supplier.id
    ).filter(
        root.Run.is_rollover == False,
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
    )
    if root._exclude_unpriced_batches_enabled():
        query = query.filter(root._priced_run_filter())

    if view == "90":
        query = query.filter(root.Run.run_date >= root.date.today() - root.timedelta(days=90))

    results = query.group_by(
        root.PurchaseLot.strain_name, root.Supplier.name
    ).order_by(root.desc("avg_yield")).all()

    yield_kpi = root.KpiTarget.query.filter_by(kpi_name="overall_yield_pct").first()
    thca_kpi = root.KpiTarget.query.filter_by(kpi_name="thca_yield_pct").first()

    return root.render_template(
        "strains.html",
        results=results,
        view=view,
        yield_kpi=yield_kpi,
        thca_kpi=thca_kpi,
        list_filters_active=(view == "90"),
        clear_filters_url=root.url_for("strains_list", clear_filters=1),
        strain_pair_sep=root.STRAIN_PAIR_SEP,
    )
