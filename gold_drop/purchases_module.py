from __future__ import annotations

from datetime import date, datetime, timezone

from gold_drop.list_state import LIST_FILTERS_SESSION_KEY, list_filters_clear_redirect, list_filters_merge
from gold_drop.purchases import biomass_budget_snapshot_for_purchase, enforce_weekly_biomass_purchase_limits
from gold_drop.uploads import save_purchase_support_docs
from services.lot_labels import build_lot_label_payload, build_purchase_label_payloads
from services.lot_allocation import ensure_lot_tracking_fields, ensure_purchase_lot_tracking
from services.purchase_helpers import (
    create_photo_asset,
    ensure_unique_batch_id,
    generate_batch_id,
    maintain_purchase_inventory_lots,
    normalize_photo_category,
    photo_asset_exists,
)


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

    @root.login_required
    def lot_label(lot_id):
        return lot_label_view(root, lot_id)

    @root.login_required
    def purchase_labels(purchase_id):
        return purchase_labels_view(root, purchase_id)

    @root.login_required
    def scan_lot(tracking_id):
        return scan_lot_view(root, tracking_id)

    @root.purchase_editor_required
    def purchase_delete(purchase_id):
        return purchase_delete_view(root, purchase_id)

    @root.admin_required
    def purchase_hard_delete(purchase_id):
        return purchase_hard_delete_view(root, purchase_id)

    app.add_url_rule("/purchases", endpoint="purchases_list", view_func=purchases_list)
    app.add_url_rule("/purchases/new", endpoint="purchase_new", view_func=purchase_new, methods=["GET", "POST"])
    app.add_url_rule("/purchases/<purchase_id>/edit", endpoint="purchase_edit", view_func=purchase_edit, methods=["GET", "POST"])
    app.add_url_rule("/purchases/<purchase_id>/approve", endpoint="purchase_approve", view_func=purchase_approve, methods=["POST"])
    app.add_url_rule("/purchases/<purchase_id>/lots/new", endpoint="lot_new", view_func=lot_new, methods=["POST"])
    app.add_url_rule("/lots/<lot_id>/label", endpoint="lot_label", view_func=lot_label)
    app.add_url_rule("/purchases/<purchase_id>/labels", endpoint="purchase_labels", view_func=purchase_labels)
    app.add_url_rule("/scan/lot/<tracking_id>", endpoint="scan_lot", view_func=scan_lot)
    app.add_url_rule("/purchases/<purchase_id>/delete", endpoint="purchase_delete", view_func=purchase_delete, methods=["POST"])
    app.add_url_rule(
        "/purchases/<purchase_id>/hard_delete",
        endpoint="purchase_hard_delete",
        view_func=purchase_hard_delete,
        methods=["POST"],
    )


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


def _purchase_allocation_state(purchase):
    active_lots = [lot for lot in purchase.lots if getattr(lot, "deleted_at", None) is None]
    total_weight = float(sum(float(lot.weight_lbs or 0) for lot in active_lots))
    total_remaining = float(sum(float(lot.remaining_weight_lbs or 0) for lot in active_lots))
    total_allocated = max(0.0, total_weight - total_remaining)
    if not active_lots:
        return "no_lots", "Needs lots", total_weight, total_allocated, total_remaining
    if total_allocated <= 0.01:
        return "unallocated", "On hand", total_weight, total_allocated, total_remaining
    if total_remaining <= 0.01:
        return "fully_allocated", "Fully allocated", total_weight, total_allocated, total_remaining
    return "partially_allocated", "Partially allocated", total_weight, total_allocated, total_remaining


def _annotate_purchase_row(purchase):
    state_key, state_label, total_weight, total_allocated, total_remaining = _purchase_allocation_state(purchase)
    active_lots = [lot for lot in purchase.lots if getattr(lot, "deleted_at", None) is None]
    tracking_ready = sum(1 for lot in active_lots if getattr(lot, "tracking_id", None))
    exceptions: list[str] = []
    if not purchase.is_approved:
        exceptions.append("Approval required")
    if not active_lots and float(purchase.stated_weight_lbs or 0) > 0:
        exceptions.append("No inventory lots")
    if active_lots and tracking_ready < len(active_lots):
        exceptions.append("Tracking incomplete")
    if purchase.price_per_lb in (None, 0):
        exceptions.append("Missing price")
    purchase._allocation_state_key = state_key
    purchase._allocation_state_label = state_label
    purchase._lot_count = len(active_lots)
    purchase._tracking_ready_count = tracking_ready
    purchase._total_weight = total_weight
    purchase._total_allocated = total_allocated
    purchase._total_remaining = total_remaining
    purchase._exceptions = exceptions
    if not purchase.is_approved:
        purchase._next_action = "Approve purchase"
    elif state_key == "no_lots":
        purchase._next_action = "Add lots"
    elif state_key == "partially_allocated":
        purchase._next_action = "Review journey"
    else:
        purchase._next_action = "Manage inventory"
    return purchase


def purchases_list_view(root):
    redir = list_filters_clear_redirect("purchases_list")
    if redir:
        return redir
    keys = ("page", "status", "start_date", "end_date", "supplier_id", "min_potency", "max_potency", "hide_terminal")
    m = list_filters_merge("purchases_list", keys)
    if root.request.args.get("filter_form") == "1":
        m["hide_terminal"] = "1" if root.request.args.get("hide_terminal") == "1" else ""
        root.session[LIST_FILTERS_SESSION_KEY]["purchases_list"]["hide_terminal"] = m["hide_terminal"]
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
    summary_pool = [_annotate_purchase_row(purchase) for purchase in query.all()]
    pagination = query.order_by(root.Purchase.purchase_date.desc()).paginate(page=page, per_page=25, error_out=False)
    if pagination.pages and page > pagination.pages:
        page = pagination.pages
        pagination = query.order_by(root.Purchase.purchase_date.desc()).paginate(page=page, per_page=25, error_out=False)
        lf = root.session.get(LIST_FILTERS_SESSION_KEY)
        if isinstance(lf, dict) and isinstance(lf.get("purchases_list"), dict):
            lf["purchases_list"]["page"] = str(page)
            root.session.modified = True
    pagination.items = [_annotate_purchase_row(purchase) for purchase in pagination.items]
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    purchases_filters_active = (
        page > 1
        or bool(status_filter)
        or bool(start_raw or end_raw or supplier_filter or min_pot_raw or max_pot_raw)
        or hide_terminal
    )
    summary_counts = {
        "visible": len(summary_pool),
        "unapproved": sum(1 for purchase in summary_pool if not purchase.is_approved),
        "partially_allocated": sum(1 for purchase in summary_pool if purchase._allocation_state_key == "partially_allocated"),
        "needs_review": sum(1 for purchase in summary_pool if purchase._exceptions),
        "remaining_lbs": float(sum(purchase._total_remaining for purchase in summary_pool)),
    }
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
        summary_counts=summary_counts,
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
    purchase.purchase_approved_at = datetime.now(timezone.utc)
    purchase.purchase_approved_by_user_id = root.current_user.id
    ensure_purchase_lot_tracking(purchase)
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
            purchase.batch_id = ensure_unique_batch_id(
                generate_batch_id(supplier_name, batch_date, batch_weight),
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
                    ensure_lot_tracking_fields(lot)
                    root.db.session.add(lot)

        maintain_purchase_inventory_lots(purchase, root.INVENTORY_ON_HAND_PURCHASE_STATUSES)

        support_files = root.request.files.getlist("purchase_supporting_files")
        if support_files and any(getattr(f, "filename", None) for f in support_files if f):
            saved_docs = save_purchase_support_docs(support_files, prefix=f"purchase-{purchase.id}")
            support_category = normalize_photo_category(
                root.request.form.get("purchase_support_category", ""),
                fallback="supporting_doc",
            )
            support_title = (root.request.form.get("purchase_support_title") or "").strip() or None
            support_tags_raw = (root.request.form.get("purchase_support_tags") or "").strip()
            support_tags = [tag.strip().lower() for tag in support_tags_raw.split(",") if tag.strip()]
            for path in saved_docs:
                if not photo_asset_exists(
                    file_path=path,
                    source_type="purchase_upload",
                    category=support_category,
                    purchase_id=purchase.id,
                ):
                    create_photo_asset(
                        path,
                        source_type="purchase_upload",
                        category=support_category,
                        tags=support_tags,
                        title=support_title,
                        supplier_id=purchase.supplier_id,
                        purchase_id=purchase.id,
                        uploaded_by=root.current_user.id,
                    )

        new_snapshot = biomass_budget_snapshot_for_purchase(purchase)
        enforce_weekly_biomass_purchase_limits(purchase, new_snapshot, enforce_cap=True)

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
    ensure_lot_tracking_fields(lot)
    root.db.session.add(lot)
    root.log_audit("create", "lot", lot.id)
    root.db.session.commit()
    root.flash("Lot added.", "success")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))


def lot_label_view(root, lot_id):
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None:
        root.flash("Lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    ensure_lot_tracking_fields(lot)
    root.db.session.commit()
    label = build_lot_label_payload(lot)
    return root.render_template("lot_label_print.html", labels=[label], purchase=lot.purchase)


def purchase_labels_view(root, purchase_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))
    ensure_purchase_lot_tracking(purchase)
    root.db.session.commit()
    labels = build_purchase_label_payloads(purchase)
    if not labels:
        root.flash("This purchase does not have any active lots to label.", "warning")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))
    return root.render_template("lot_label_print.html", labels=labels, purchase=purchase)


def scan_lot_view(root, tracking_id):
    lot = root.PurchaseLot.query.filter(
        root.PurchaseLot.tracking_id == tracking_id,
        root.PurchaseLot.deleted_at.is_(None),
    ).first()
    if not lot or not lot.purchase or lot.purchase.deleted_at is not None:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    return root.redirect(root.url_for("purchases_bp.purchase_journey", purchase_id=lot.purchase.id, lot=tracking_id))


def purchase_delete_view(root, purchase_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))

    has_run_inputs = (
        root.db.session.query(root.RunInput.id)
        .join(root.PurchaseLot)
        .join(root.Run)
        .filter(
            root.PurchaseLot.purchase_id == purchase.id,
            root.PurchaseLot.deleted_at.is_(None),
            root.Run.deleted_at.is_(None),
        )
        .first()
        is not None
    )
    if has_run_inputs:
        root.flash("Cannot delete purchase that is used in active runs. Delete those runs first.", "error")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))

    deleted_at = root.datetime.now(root.timezone.utc)
    purchase.deleted_at = deleted_at
    purchase.deleted_by = root.current_user.id
    for lot in purchase.lots:
        lot.deleted_at = deleted_at
        lot.deleted_by = root.current_user.id

    root.log_audit("delete", "purchase", purchase.id, details=root.json.dumps({"mode": "soft"}))
    root.db.session.commit()
    root.notify_slack(f"Purchase soft-deleted: {purchase.batch_id or purchase.id}.")
    root.flash("Purchase deleted.", "success")
    return root.redirect(root.url_for("purchases_list"))


def purchase_hard_delete_view(root, purchase_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))

    has_any_run_inputs = (
        root.db.session.query(root.RunInput.id)
        .join(root.PurchaseLot)
        .filter(root.PurchaseLot.purchase_id == purchase.id)
        .first()
        is not None
    )
    if has_any_run_inputs:
        root.flash("Cannot hard-delete purchase that has run history.", "error")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))

    root.log_audit("delete", "purchase", purchase.id, details=root.json.dumps({"mode": "hard"}))
    root.db.session.delete(purchase)
    root.db.session.commit()
    root.notify_slack(f"Purchase hard-deleted: {purchase.batch_id or purchase.id}.")
    root.flash("Purchase permanently deleted.", "success")
    return root.redirect(root.url_for("purchases_list"))
