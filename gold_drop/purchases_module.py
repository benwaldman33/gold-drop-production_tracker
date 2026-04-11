from __future__ import annotations

from datetime import date, datetime


def register_routes(app, root):
    @root.login_required
    def purchases_list():
        return purchases_list_view(root)

    @root.purchase_editor_required
    def purchase_new():
        return purchase_new_view(root)

    @root.purchase_editor_required
    def purchase_edit(purchase_id):
        return purchase_edit_view(root, purchase_id)

    @root.login_required
    def purchase_approve(purchase_id):
        return purchase_approve_view(root, purchase_id)

    @root.purchase_editor_required
    def lot_new(purchase_id):
        return lot_new_view(root, purchase_id)

    app.add_url_rule("/purchases", endpoint="purchases_list", view_func=purchases_list)
    app.add_url_rule("/purchases/new", endpoint="purchase_new", view_func=purchase_new, methods=["GET", "POST"])
    app.add_url_rule("/purchases/<purchase_id>/edit", endpoint="purchase_edit", view_func=purchase_edit, methods=["GET", "POST"])
    app.add_url_rule("/purchases/<purchase_id>/approve", endpoint="purchase_approve", view_func=purchase_approve, methods=["POST"])
    app.add_url_rule("/purchases/<purchase_id>/lots/new", endpoint="lot_new", view_func=lot_new, methods=["POST"])


def _purchase_form_context(root, purchase):
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    rate = root.SystemSetting.get_float("potency_rate", 1.50)
    purchase_audit_photos = []
    purchase_support_docs = []
    if purchase:
        purchase_audit_photos = root.PhotoAsset.query.filter(
            root.PhotoAsset.purchase_id == purchase.id,
            root.PhotoAsset.source_type == "field_submission",
        ).order_by(root.PhotoAsset.uploaded_at.desc()).all()
        purchase_support_docs = root.PhotoAsset.query.filter(
            root.PhotoAsset.purchase_id == purchase.id,
            root.PhotoAsset.source_type == "purchase_upload",
        ).order_by(root.PhotoAsset.uploaded_at.desc()).all()
    return {
        "purchase": purchase,
        "suppliers": suppliers,
        "rate": rate,
        "today": date.today(),
        "purchase_audit_photos": purchase_audit_photos,
        "purchase_support_docs": purchase_support_docs,
    }


def purchases_list_view(root):
    redir = root._list_filters_clear_redirect("purchases_list")
    if redir:
        return redir
    keys = ("page", "status", "start_date", "end_date", "supplier_id", "min_potency", "max_potency", "hide_terminal")
    m = root._list_filters_merge("purchases_list", keys)
    if root.request.args.get("filter_form") == "1":
        m["hide_terminal"] = "1" if root.request.args.get("hide_terminal") == "1" else ""
        root.session[root.LIST_FILTERS_SESSION_KEY]["purchases_list"]["hide_terminal"] = m["hide_terminal"]
        root.session.modified = True
    try:
        page = int(m.get("page") or 1)
    except ValueError:
        page = 1
    status_filter = (m.get("status") or "").strip()
    start_raw = (m.get("start_date") or "").strip()
    end_raw = (m.get("end_date") or "").strip()
    supplier_filter = (m.get("supplier_id") or "").strip()
    min_pot_raw = (m.get("min_potency") or "").strip()
    max_pot_raw = (m.get("max_potency") or "").strip()
    hide_terminal = m.get("hide_terminal") == "1"
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    try:
        min_potency = float(min_pot_raw) if min_pot_raw else None
        max_potency = float(max_pot_raw) if max_pot_raw else None
    except ValueError:
        min_potency = None
        max_potency = None
    query = root.Purchase.query.filter(root.Purchase.deleted_at.is_(None))
    if status_filter:
        query = query.filter_by(status=status_filter)
    if hide_terminal:
        query = query.filter(root.Purchase.status.notin_(("complete", "cancelled")))
    if start_date:
        query = query.filter(root.Purchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(root.Purchase.purchase_date <= end_date)
    if supplier_filter:
        query = query.filter(root.Purchase.supplier_id == supplier_filter)
    if min_potency is not None:
        query = query.filter(root.Purchase.stated_potency_pct >= min_potency)
    if max_potency is not None:
        query = query.filter(root.Purchase.stated_potency_pct <= max_potency)
    pagination = query.order_by(root.Purchase.purchase_date.desc()).paginate(page=page, per_page=25, error_out=False)
    if pagination.pages and page > pagination.pages:
        page = pagination.pages
        pagination = query.order_by(root.Purchase.purchase_date.desc()).paginate(page=page, per_page=25, error_out=False)
        lf = root.session.get(root.LIST_FILTERS_SESSION_KEY)
        if isinstance(lf, dict) and isinstance(lf.get("purchases_list"), dict):
            lf["purchases_list"]["page"] = str(page)
            root.session.modified = True
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    purchases_filters_active = (
        page > 1
        or bool(status_filter)
        or bool(start_raw or end_raw or supplier_filter or min_pot_raw or max_pot_raw)
        or hide_terminal
    )
    return root.render_template(
        "purchases.html",
        purchases=pagination.items,
        pagination=pagination,
        status_filter=status_filter,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        start_date=start_raw,
        end_date=end_raw,
        min_potency=min_pot_raw,
        max_potency=max_pot_raw,
        hide_terminal=hide_terminal,
        list_filters_active=purchases_filters_active,
        clear_filters_url=root.url_for("purchases_list", clear_filters=1),
    )


def purchase_new_view(root):
    if root.request.method == "POST":
        return save_purchase(root, None)
    return root.render_template("purchase_form.html", **_purchase_form_context(root, None))


def purchase_edit_view(root, purchase_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))
    if root.request.method == "POST":
        return save_purchase(root, purchase)
    return root.render_template("purchase_form.html", **_purchase_form_context(root, purchase))


def purchase_approve_view(root, purchase_id):
    if not root.current_user.can_approve_purchase:
        root.flash("Only users with purchase approval permission can approve purchases.", "error")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))
    if purchase.is_approved:
        root.flash("Purchase is already approved.", "info")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))
    purchase.purchase_approved_at = datetime.utcnow()
    purchase.purchase_approved_by_user_id = root.current_user.id
    root.log_audit("approve", "purchase", purchase.id)
    root.db.session.commit()
    root.flash(f"Purchase {purchase.batch_id or purchase.id} approved.", "success")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))


def save_purchase(root, existing):
    try:
        purchase = existing or root.Purchase()
        purchase.supplier_id = root.request.form["supplier_id"]
        purchase.purchase_date = datetime.strptime(root.request.form["purchase_date"], "%Y-%m-%d").date()
        delivery_date_raw = root.request.form.get("delivery_date", "").strip()
        purchase.delivery_date = datetime.strptime(delivery_date_raw, "%Y-%m-%d").date() if delivery_date_raw else None
        new_status = root.request.form.get("status", "ordered")
        if new_status in root.INVENTORY_ON_HAND_PURCHASE_STATUSES and not purchase.is_approved:
            raise ValueError(
                f"Cannot set status to \"{new_status.replace('_', ' ').title()}\" - "
                "this purchase has not been approved yet. Approve it first, then change status."
            )
        purchase.status = new_status
        purchase.stated_weight_lbs = float(root.request.form.get("stated_weight_lbs") or 0)
        actual_weight_raw = root.request.form.get("actual_weight_lbs", "").strip()
        purchase.actual_weight_lbs = float(actual_weight_raw) if actual_weight_raw else None
        stated_potency_raw = root.request.form.get("stated_potency_pct", "").strip()
        purchase.stated_potency_pct = float(stated_potency_raw) if stated_potency_raw else None
        tested_potency_raw = root.request.form.get("tested_potency_pct", "").strip()
        purchase.tested_potency_pct = float(tested_potency_raw) if tested_potency_raw else None
        price_per_lb_raw = root.request.form.get("price_per_lb", "").strip()
        purchase.price_per_lb = float(price_per_lb_raw) if price_per_lb_raw else None
        purchase.storage_note = root.request.form.get("storage_note", "").strip() or None
        purchase.license_info = root.request.form.get("license_info", "").strip() or None
        queue_placement = (root.request.form.get("queue_placement") or "").strip().lower()
        purchase.queue_placement = queue_placement if queue_placement in ("aggregate", "indoor", "outdoor") else None
        purchase.coa_status_text = root.request.form.get("coa_status_text", "").strip() or None
        purchase.clean_or_dirty = root.request.form.get("clean_or_dirty") or None
        purchase.indoor_outdoor = root.request.form.get("indoor_outdoor") or None
        harvest_date_raw = root.request.form.get("harvest_date", "").strip()
        purchase.harvest_date = datetime.strptime(harvest_date_raw, "%Y-%m-%d").date() if harvest_date_raw else None
        purchase.notes = root.request.form.get("notes", "").strip() or None

        if purchase.stated_potency_pct and not purchase.price_per_lb:
            rate = root.SystemSetting.get_float("potency_rate", 1.50)
            purchase.price_per_lb = rate * purchase.stated_potency_pct

        weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
        if weight and purchase.price_per_lb:
            purchase.total_cost = weight * purchase.price_per_lb

        if purchase.tested_potency_pct and purchase.stated_potency_pct and purchase.actual_weight_lbs:
            rate = root.SystemSetting.get_float("potency_rate", 1.50)
            purchase.true_up_amount = (
                (purchase.tested_potency_pct - purchase.stated_potency_pct) * rate * purchase.actual_weight_lbs
            )
            if not purchase.true_up_status:
                purchase.true_up_status = "pending"

        if not existing:
            root.db.session.add(purchase)
        root.db.session.flush()

        batch_in = (root.request.form.get("batch_id") or "").strip()
        if batch_in:
            candidate = batch_in.upper()
            conflict = root.Purchase.query.filter(
                root.Purchase.batch_id == candidate,
                root.Purchase.id != purchase.id,
            ).first()
            if conflict:
                raise ValueError(f"Batch ID '{candidate}' already exists. Please choose a unique Batch ID.")
            purchase.batch_id = candidate
        else:
            supplier = root.db.session.get(root.Supplier, purchase.supplier_id)
            supplier_name = supplier.name if supplier else "BATCH"
            batch_date = purchase.delivery_date or purchase.purchase_date
            batch_weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
            purchase.batch_id = root._ensure_unique_batch_id(
                root._generate_batch_id(supplier_name, batch_date, batch_weight),
                exclude_purchase_id=purchase.id,
            )

        if not existing:
            lot_strains = root.request.form.getlist("lot_strains[]")
            lot_weights = root.request.form.getlist("lot_weights[]")
            for strain, weight_value in zip(lot_strains, lot_weights):
                if strain and weight_value:
                    lot = root.PurchaseLot(
                        purchase_id=purchase.id,
                        strain_name=strain.strip(),
                        weight_lbs=float(weight_value),
                        remaining_weight_lbs=float(weight_value),
                    )
                    root.db.session.add(lot)

        root._maintain_purchase_inventory_lots(purchase)

        support_files = root.request.files.getlist("purchase_supporting_files")
        if support_files and any(getattr(f, "filename", None) for f in support_files if f):
            saved_docs = root._save_purchase_support_docs(support_files, prefix=f"purchase-{purchase.id}")
            support_category = root._normalize_photo_category(
                root.request.form.get("purchase_support_category", ""),
                fallback="supporting_doc",
            )
            support_title = (root.request.form.get("purchase_support_title") or "").strip() or None
            support_tags_raw = (root.request.form.get("purchase_support_tags") or "").strip()
            support_tags = [tag.strip().lower() for tag in support_tags_raw.split(",") if tag.strip()]
            for path in saved_docs:
                if not root._photo_asset_exists(
                    file_path=path,
                    source_type="purchase_upload",
                    category=support_category,
                    purchase_id=purchase.id,
                ):
                    root._create_photo_asset(
                        path,
                        source_type="purchase_upload",
                        category=support_category,
                        tags=support_tags,
                        title=support_title,
                        supplier_id=purchase.supplier_id,
                        purchase_id=purchase.id,
                        uploaded_by=root.current_user.id,
                    )

        new_snapshot = root._biomass_budget_snapshot_for_purchase(purchase)
        root._enforce_weekly_biomass_purchase_limits(purchase, new_snapshot, enforce_cap=True)

        root.log_audit("update" if existing else "create", "purchase", purchase.id)
        root.db.session.commit()
        root.flash("Purchase saved.", "success")
        return root.redirect(root.url_for("purchases_list"))
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return root.render_template("purchase_form.html", **_purchase_form_context(root, existing))
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("Error saving purchase")
        root.flash("Error saving purchase. Please check your inputs and try again.", "error")
        return root.render_template("purchase_form.html", **_purchase_form_context(root, existing))


def lot_new_view(root, purchase_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))

    lot = root.PurchaseLot(
        purchase_id=purchase_id,
        strain_name=root.request.form["strain_name"].strip(),
        weight_lbs=float(root.request.form["weight_lbs"]),
        remaining_weight_lbs=float(root.request.form["weight_lbs"]),
        potency_pct=float(root.request.form.get("potency_pct") or 0) or None,
        milled="milled" in root.request.form,
        location=root.request.form.get("location", "").strip() or None,
    )
    root.db.session.add(lot)
    root.log_audit("create", "lot", lot.id)
    root.db.session.commit()
    root.flash("Lot added.", "success")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))
