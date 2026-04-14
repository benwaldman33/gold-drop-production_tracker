from __future__ import annotations

from gold_drop.uploads import json_paths, save_lab_files
from services.lot_allocation import (
    apply_run_allocations,
    collect_run_allocations_from_form,
    release_run_allocations,
)
from services.slack_workflow import (
    hydrate_run_from_slack_prefill,
    slack_resolution_create_declared_biomass,
    slack_resolution_materialize_supplier,
)


def register_routes(app, root):
    @root.login_required
    def runs_list():
        return runs_list_view(root)

    @root.login_required
    def run_new():
        return run_new_view(root)

    @root.editor_required
    def run_edit(run_id):
        return run_edit_view(root, run_id)

    @root.editor_required
    def run_delete(run_id):
        return run_delete_view(root, run_id)

    @root.admin_required
    def run_hard_delete(run_id):
        return run_hard_delete_view(root, run_id)

    app.add_url_rule("/runs", endpoint="runs_list", view_func=runs_list)
    app.add_url_rule("/runs/new", endpoint="run_new", view_func=run_new, methods=["GET", "POST"])
    app.add_url_rule("/runs/<run_id>/edit", endpoint="run_edit", view_func=run_edit, methods=["GET", "POST"])
    app.add_url_rule("/runs/<run_id>/delete", endpoint="run_delete", view_func=run_delete, methods=["POST"])
    app.add_url_rule("/runs/<run_id>/hard_delete", endpoint="run_hard_delete", view_func=run_hard_delete, methods=["POST"])


def runs_list_view(root):
    redir = root._list_filters_clear_redirect("runs_list")
    if redir:
        return redir
    merged = root._list_filters_merge(
        "runs_list",
        ("page", "sort", "order", "search", "start_date", "end_date", "supplier_id", "min_potency", "max_potency", "hte_stage"),
    )
    try:
        page = int(merged.get("page") or 1)
    except ValueError:
        page = 1
    sort = (merged.get("sort") or "run_date").strip() or "run_date"
    order = (merged.get("order") or "desc").strip() or "desc"
    search = (merged.get("search") or "").strip()
    start_raw = (merged.get("start_date") or "").strip()
    end_raw = (merged.get("end_date") or "").strip()
    supplier_filter = (merged.get("supplier_id") or "").strip()
    min_pot_raw = (merged.get("min_potency") or "").strip()
    max_pot_raw = (merged.get("max_potency") or "").strip()
    hte_stage = (merged.get("hte_stage") or "").strip()
    try:
        start_date = root.datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = root.datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    try:
        min_potency = float(min_pot_raw) if min_pot_raw else None
        max_potency = float(max_pot_raw) if max_pot_raw else None
    except ValueError:
        min_potency = None
        max_potency = None

    query = root.Run.query.filter(root.Run.deleted_at.is_(None))
    if search:
        query = query.join(root.RunInput, isouter=True).join(root.PurchaseLot, isouter=True).filter(
            root.db.or_(
                root.PurchaseLot.strain_name.ilike(f"%{search}%"),
                root.Run.notes.ilike(f"%{search}%"),
            )
        ).distinct()
    if start_date:
        query = query.filter(root.Run.run_date >= start_date)
    if end_date:
        query = query.filter(root.Run.run_date <= end_date)
    if min_potency is not None:
        query = query.filter(root.Run.thca_yield_pct >= min_potency)
    if max_potency is not None:
        query = query.filter(root.Run.thca_yield_pct <= max_potency)
    if supplier_filter:
        query = query.join(root.RunInput, root.RunInput.run_id == root.Run.id).join(
            root.PurchaseLot, root.PurchaseLot.id == root.RunInput.lot_id
        ).join(root.Purchase, root.Purchase.id == root.PurchaseLot.purchase_id).filter(
            root.Purchase.supplier_id == supplier_filter
        ).distinct()
    if hte_stage and hte_stage in root.HTE_PIPELINE_ALLOWED and hte_stage != "":
        query = query.filter(root.Run.hte_pipeline_stage == hte_stage)

    sort_col = getattr(root.Run, sort, root.Run.run_date)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    if pagination.pages and page > pagination.pages:
        page = pagination.pages
        pagination = query.paginate(page=page, per_page=25, error_out=False)
        lf = root.session.get(root.LIST_FILTERS_SESSION_KEY)
        if isinstance(lf, dict) and isinstance(lf.get("runs_list"), dict):
            lf["runs_list"]["page"] = str(page)
            root.session.modified = True
    run_ids = [run.id for run in pagination.items]
    pricing_status = root._pricing_status_for_run_ids(run_ids)
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    hte_label_map = dict(root._hte_pipeline_options())
    return root.render_template(
        "runs.html",
        runs=pagination.items,
        pagination=pagination,
        sort=sort,
        order=order,
        search=search,
        pricing_status=pricing_status,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        start_date=start_raw,
        end_date=end_raw,
        min_potency=min_pot_raw,
        max_potency=max_pot_raw,
        hte_stage=hte_stage,
        hte_label_map=hte_label_map,
        hte_pipeline_options=root._hte_pipeline_options(),
        list_filters_active=root._runs_list_filters_active(merged),
        clear_filters_url=root.url_for("runs_list", clear_filters=1),
    )


def run_new_view(root):
    if root.request.method == "POST":
        if not root.current_user.can_edit:
            root.flash("Saving runs requires User or Super Admin access.", "error")
            return root.redirect(root.url_for("dashboard"))
        return save_run(root, None)

    slack_prefill = root.session.get(root.SLACK_RUN_PREFILL_SESSION_KEY)
    scan_prefill = None if slack_prefill else root.session.get(root.SCAN_RUN_PREFILL_SESSION_KEY)
    if not root.current_user.can_edit and not (slack_prefill and root.current_user.can_slack_import):
        root.flash("Edit access required.", "error")
        return root.redirect(root.url_for("dashboard"))

    today = root.date.today()
    if slack_prefill:
        if not root.current_user.can_slack_import:
            root.session.pop(root.SLACK_RUN_PREFILL_SESSION_KEY, None)
            root.flash("Slack import access is not enabled for your account.", "error")
            return root.redirect(root.url_for("dashboard"))
        display_run = hydrate_run_from_slack_prefill(root, slack_prefill, today)
        res = slack_prefill.get("resolution") or {}
        hints: list[str] = []
        if res.get("biomass_declared"):
            hints.append("Saving will add a declared biomass pipeline row (strain / weight from the Slack apply form).")
        if (res.get("supplier_mode") or "").strip() == "create" and (res.get("new_supplier_name") or "").strip():
            hints.append("Saving will create a new supplier record from the Slack apply form.")
        slack_meta = {
            "ingested_message_id": slack_prefill.get("ingested_message_id"),
            "channel_id": slack_prefill.get("channel_id"),
            "message_ts": slack_prefill.get("message_ts"),
            "allow_duplicate": bool(slack_prefill.get("allow_duplicate")),
            "resolution_hints": hints,
            "lot_candidates": list(slack_prefill.get("lot_candidates") or []),
            "suggested_allocations": list(slack_prefill.get("suggested_allocations") or []),
        }
    else:
        display_run = None
        slack_meta = None

    scan_meta = None
    if scan_prefill:
        display_run = display_run or root.Run()
        scan_meta = {
            "tracking_id": (scan_prefill.get("tracking_id") or "").strip(),
            "purchase_id": (scan_prefill.get("purchase_id") or "").strip(),
            "batch_id": (scan_prefill.get("batch_id") or "").strip(),
            "supplier_name": (scan_prefill.get("supplier_name") or "").strip(),
            "strain_name": (scan_prefill.get("strain_name") or "").strip(),
            "remaining_weight_lbs": float(scan_prefill.get("remaining_weight_lbs") or 0),
            "suggested_allocations": list(scan_prefill.get("suggested_allocations") or []),
        }

    lots = _available_lots_query(root).all()
    lot_rows = list(slack_meta.get("suggested_allocations") or []) if slack_meta else list(scan_meta.get("suggested_allocations") or []) if scan_meta else []
    return root.render_template(
        "run_form.html",
        run=display_run,
        lots=lots,
        lot_rows=lot_rows,
        today=today,
        slack_meta=slack_meta,
        scan_meta=scan_meta,
        can_save_run=bool(root.current_user.can_edit),
        **root._run_form_extras(display_run),
    )


def run_edit_view(root, run_id):
    run = root.db.session.get(root.Run, run_id)
    if not run or run.deleted_at is not None:
        root.flash("Run not found.", "error")
        return root.redirect(root.url_for("runs_list"))
    if root.request.method == "POST":
        return save_run(root, run)

    lots = root.PurchaseLot.query.join(root.Purchase).filter(
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.db.or_(
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.PurchaseLot.id.in_([inp.lot_id for inp in run.inputs]),
        ),
    ).all()
    lot_rows = [{"lot_id": inp.lot_id, "weight_lbs": inp.weight_lbs} for inp in run.inputs]
    return root.render_template(
        "run_form.html",
        run=run,
        lots=lots,
        lot_rows=lot_rows,
        today=root.date.today(),
        slack_meta=None,
        scan_meta=None,
        can_save_run=True,
        **root._run_form_extras(run),
    )


def save_run(root, existing_run):
    today = root.date.today()
    slack_meta = None
    scan_meta = None
    if root.request.form.get("slack_ingested_message_id"):
        slack_meta = {
            "ingested_message_id": (root.request.form.get("slack_ingested_message_id") or "").strip(),
            "channel_id": (root.request.form.get("slack_channel_id") or "").strip(),
            "message_ts": (root.request.form.get("slack_message_ts") or "").strip(),
            "allow_duplicate": root.request.form.get("slack_apply_allow_duplicate") == "1",
        }
    elif not existing_run:
        scan_prefill = root.session.get(root.SCAN_RUN_PREFILL_SESSION_KEY) or {}
        if scan_prefill:
            scan_meta = {
                "tracking_id": (scan_prefill.get("tracking_id") or "").strip(),
                "purchase_id": (scan_prefill.get("purchase_id") or "").strip(),
                "batch_id": (scan_prefill.get("batch_id") or "").strip(),
                "supplier_name": (scan_prefill.get("supplier_name") or "").strip(),
                "strain_name": (scan_prefill.get("strain_name") or "").strip(),
                "remaining_weight_lbs": float(scan_prefill.get("remaining_weight_lbs") or 0),
                "suggested_allocations": list(scan_prefill.get("suggested_allocations") or []),
            }

    try:
        if existing_run:
            run = existing_run
            release_run_allocations(root, run)
            root.RunInput.query.filter_by(run_id=run.id).delete()
        else:
            run = root.Run()

        run.run_date = root.datetime.strptime(root.request.form["run_date"], "%Y-%m-%d").date()
        run.reactor_number = int(root.request.form["reactor_number"])
        run.load_source_reactors = (root.request.form.get("load_source_reactors") or "").strip() or None
        run.is_rollover = "is_rollover" in root.request.form
        run.bio_in_reactor_lbs = float(root.request.form.get("bio_in_reactor_lbs") or 0)
        run.bio_in_house_lbs = _available_lots_sum(root)
        run.butane_in_house_lbs = float(root.request.form.get("butane_in_house_lbs") or 0) or None
        run.solvent_ratio = float(root.request.form.get("solvent_ratio") or 0) or None
        run.system_temp = float(root.request.form.get("system_temp") or 0) or None
        run.wet_hte_g = float(root.request.form.get("wet_hte_g") or 0) or None
        run.wet_thca_g = float(root.request.form.get("wet_thca_g") or 0) or None
        run.dry_hte_g = float(root.request.form.get("dry_hte_g") or 0) or None
        run.dry_thca_g = float(root.request.form.get("dry_thca_g") or 0) or None
        run.decarb_sample_done = "decarb_sample_done" in root.request.form
        run.fuel_consumption = float(root.request.form.get("fuel_consumption") or 0) or None
        run.notes = root.request.form.get("notes", "").strip() or None
        run.run_type = root.request.form.get("run_type", "standard")

        if not existing_run:
            run.created_by = root.current_user.id

        run.calculate_yields()

        if not existing_run and slack_meta and slack_meta.get("channel_id") and slack_meta.get("message_ts"):
            dup = root._first_run_for_slack_message(slack_meta["channel_id"], slack_meta["message_ts"])
            if dup and not slack_meta.get("allow_duplicate"):
                root.flash(
                    "A run is already linked to this Slack message. Re-open the apply flow and confirm if you need a duplicate.",
                    "error",
                )
                return root.render_template(
                    "run_form.html",
                    run=run,
                    lots=_available_lots_query(root).all(),
                    today=today,
                    slack_meta=slack_meta,
                    can_save_run=True,
                    **root._run_form_extras(run),
                )

        if not existing_run:
            root.db.session.add(run)
        root.db.session.flush()

        stage_raw = (root.request.form.get("hte_pipeline_stage") or "").strip()
        if stage_raw not in root.HTE_PIPELINE_ALLOWED:
            raise ValueError("Invalid HTE pipeline stage.")
        run.hte_pipeline_stage = stage_raw or None

        def _opt_float(name):
            raw = (root.request.form.get(name) or "").strip()
            return float(raw) if raw else None

        run.hte_terpenes_recovered_g = _opt_float("hte_terpenes_recovered_g")
        run.hte_distillate_retail_g = _opt_float("hte_distillate_retail_g")

        paths = list(json_paths(run.hte_lab_result_paths_json))
        for rem in root.request.form.getlist("remove_hte_lab_paths[]"):
            if rem in paths:
                paths.remove(rem)
        new_files = root.request.files.getlist("hte_lab_files[]")
        if new_files:
            paths.extend(save_lab_files(new_files, prefix=f"hte-run-{run.id[:8]}"))
        run.hte_lab_result_paths_json = root.json.dumps(paths) if paths else None

        allocations = collect_run_allocations_from_form(root)
        total_allocated = apply_run_allocations(
            root,
            run,
            allocations,
            allocation_source="slack" if slack_meta else "manual",
            allocation_confidence=1.0 if slack_meta else None,
            slack_ingested_message_id=slack_meta.get("ingested_message_id") if slack_meta else None,
        )
        if abs(total_allocated - float(run.bio_in_reactor_lbs or 0)) > 0.1:
            raise ValueError(
                "Allocated source lots must match Lbs in Reactor."
            )

        run.calculate_cost()

        slack_prefill_snapshot = (root.session.get(root.SLACK_RUN_PREFILL_SESSION_KEY) or {}) if not existing_run else {}
        resolution = slack_prefill_snapshot.get("resolution")
        if not existing_run and slack_meta and resolution:
            mode = (resolution.get("supplier_mode") or "").strip()
            need_supplier_materialize = mode == "create" or bool(resolution.get("biomass_declared"))
            if need_supplier_materialize:
                sid = slack_resolution_materialize_supplier(root, resolution, slack_meta)
                if resolution.get("biomass_declared") and sid:
                    slack_resolution_create_declared_biomass(root, resolution, sid, slack_meta, run.run_date)

        audit_details = None
        if not existing_run and slack_meta and slack_meta.get("channel_id") and slack_meta.get("message_ts"):
            run.slack_channel_id = slack_meta["channel_id"]
            run.slack_message_ts = slack_meta["message_ts"]
            run.slack_import_applied_at = root.datetime.now(root.timezone.utc)
            audit_payload = {
                "slack_import": True,
                "slack_ingested_message_id": slack_meta.get("ingested_message_id"),
                "channel_id": run.slack_channel_id,
                "message_ts": run.slack_message_ts,
                "duplicate_apply": bool(slack_meta.get("allow_duplicate")),
                "prefill_keys": sorted(slack_prefill_snapshot.get("filled") or []),
            }
            if resolution:
                audit_payload["slack_resolution"] = {
                    "supplier_mode": resolution.get("supplier_mode"),
                    "biomass_declared": bool(resolution.get("biomass_declared")),
                }
            audit_details = root.json.dumps(audit_payload)

        root.log_audit("update" if existing_run else "create", "run", run.id, details=audit_details)
        root.db.session.commit()
        if not existing_run and slack_meta and slack_meta.get("channel_id") and slack_meta.get("message_ts"):
            root.session.pop(root.SLACK_RUN_PREFILL_SESSION_KEY, None)
        if not existing_run and scan_meta:
            root.session.pop(root.SCAN_RUN_PREFILL_SESSION_KEY, None)
        root.flash("Run saved successfully.", "success")
        return root.redirect(root.url_for("runs_list"))
    except Exception as exc:
        root.db.session.rollback()
        root.flash(f"Error saving run: {str(exc)}", "error")
        current = existing_run if existing_run else run
        return root.render_template(
            "run_form.html",
            run=current,
            lots=_available_lots_query(root).all(),
            today=today,
            slack_meta=slack_meta,
            scan_meta=scan_meta,
            can_save_run=True,
            **root._run_form_extras(current),
        )


def run_delete_view(root, run_id):
    run = root.db.session.get(root.Run, run_id)
    if run and run.deleted_at is None:
        release_run_allocations(root, run)
        run.deleted_at = root.datetime.now(root.timezone.utc)
        run.deleted_by = root.current_user.id
        root.log_audit("delete", "run", run.id, details=root.json.dumps({"mode": "soft"}))
        root.db.session.commit()
        root.notify_slack(f"Run soft-deleted: {run.id}.")
        root.flash("Run deleted.", "success")
    return root.redirect(root.url_for("runs_list"))


def run_hard_delete_view(root, run_id):
    run = root.db.session.get(root.Run, run_id)
    if not run:
        root.flash("Run not found.", "error")
        return root.redirect(root.url_for("runs_list"))
    if run.deleted_at is None:
        release_run_allocations(root, run)
    root.log_audit("delete", "run", run.id, details=root.json.dumps({"mode": "hard"}))
    root.db.session.delete(run)
    root.db.session.commit()
    root.notify_slack(f"Run hard-deleted: {run.id}.")
    root.flash("Run permanently deleted.", "success")
    return root.redirect(root.url_for("runs_list"))


def _available_lots_query(root):
    return root.PurchaseLot.query.join(root.Purchase).filter(
        root.PurchaseLot.remaining_weight_lbs > 0,
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        root.Purchase.purchase_approved_at.isnot(None),
    )


def _available_lots_sum(root):
    return root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
        root.PurchaseLot.remaining_weight_lbs > 0,
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        root.Purchase.purchase_approved_at.isnot(None),
    ).scalar() or 0
