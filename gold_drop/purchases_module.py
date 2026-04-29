from __future__ import annotations

from datetime import date, datetime, timezone

from gold_drop.list_state import LIST_FILTERS_SESSION_KEY, list_filters_clear_redirect, list_filters_merge
from gold_drop.purchases import biomass_budget_snapshot_for_purchase, enforce_weekly_biomass_purchase_limits
from gold_drop.uploads import save_purchase_support_docs
from services.extraction_charge import (
    build_charge_prefill_payload,
    create_extraction_charge,
    default_charge_datetime_local,
    parse_charge_datetime,
    reactor_count,
    validate_chargeable_lot,
)
from services.lot_labels import build_lot_label_payload, build_purchase_label_payloads
from services.lot_allocation import ensure_lot_tracking_fields, ensure_purchase_lot_tracking

MOVEMENT_OPTIONS = [
    {"code": "vault", "label": "Move to vault", "default_location": "Vault", "floor_state": "vault"},
    {"code": "reactor_staging", "label": "Move to reactor staging", "default_location": "Reactor staging", "floor_state": "reactor_staging"},
    {"code": "quarantine", "label": "Move to quarantine", "default_location": "Quarantine", "floor_state": "quarantine"},
    {"code": "inventory_return", "label": "Return to inventory", "default_location": "Inventory return", "floor_state": "inventory"},
    {"code": "custom", "label": "Custom location", "default_location": "", "floor_state": "custom"},
]
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

    @root.purchase_editor_required
    def lot_split(lot_id):
        return lot_split_view(root, lot_id)

    @root.editor_required
    def lot_edit(lot_id):
        return lot_edit_view(root, lot_id)

    @root.login_required
    def lot_label(lot_id):
        return lot_label_view(root, lot_id)

    @root.editor_required
    def lot_charge(lot_id):
        return lot_charge_view(root, lot_id)

    @root.login_required
    def purchase_labels(purchase_id):
        return purchase_labels_view(root, purchase_id)

    @root.login_required
    def scan_lot(tracking_id):
        return scan_lot_view(root, tracking_id)

    @root.editor_required
    def scan_lot_charge(tracking_id):
        return scan_lot_charge_view(root, tracking_id)

    @root.editor_required
    def scan_lot_start_run(tracking_id):
        return scan_lot_start_run_view(root, tracking_id)

    @root.editor_required
    def scan_lot_confirm_movement(tracking_id):
        return scan_lot_confirm_movement_view(root, tracking_id)

    @root.editor_required
    def scan_lot_confirm_testing(tracking_id):
        return scan_lot_confirm_testing_view(root, tracking_id)

    @root.editor_required
    def scan_lot_confirm_milled(tracking_id):
        return scan_lot_confirm_milled_view(root, tracking_id)

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
    app.add_url_rule("/lots/<lot_id>/split", endpoint="lot_split", view_func=lot_split, methods=["POST"])
    app.add_url_rule("/lots/<lot_id>/edit", endpoint="lot_edit", view_func=lot_edit, methods=["GET", "POST"])
    app.add_url_rule("/lots/<lot_id>/label", endpoint="lot_label", view_func=lot_label)
    app.add_url_rule("/lots/<lot_id>/charge", endpoint="lot_charge", view_func=lot_charge, methods=["GET", "POST"])
    app.add_url_rule("/purchases/<purchase_id>/labels", endpoint="purchase_labels", view_func=purchase_labels)
    app.add_url_rule("/scan/lot/<tracking_id>", endpoint="scan_lot", view_func=scan_lot)
    app.add_url_rule("/scan/lot/<tracking_id>/charge", endpoint="scan_lot_charge", view_func=scan_lot_charge, methods=["GET", "POST"])
    app.add_url_rule("/scan/lot/<tracking_id>/start-run", endpoint="scan_lot_start_run", view_func=scan_lot_start_run, methods=["POST"])
    app.add_url_rule(
        "/scan/lot/<tracking_id>/confirm-movement",
        endpoint="scan_lot_confirm_movement",
        view_func=scan_lot_confirm_movement,
        methods=["POST"],
    )
    app.add_url_rule(
        "/scan/lot/<tracking_id>/confirm-testing",
        endpoint="scan_lot_confirm_testing",
        view_func=scan_lot_confirm_testing,
        methods=["POST"],
    )
    app.add_url_rule(
        "/scan/lot/<tracking_id>/confirm-milled",
        endpoint="scan_lot_confirm_milled",
        view_func=scan_lot_confirm_milled,
        methods=["POST"],
    )
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
    purchase_delivery_photos = []
    purchase_support_docs = []
    purchase_origin_summary = None
    if purchase:
        last_receiving_edit = root.AuditLog.query.filter(
            root.AuditLog.entity_type == "purchase",
            root.AuditLog.entity_id == purchase.id,
            root.AuditLog.action == "receive_edit",
        ).order_by(root.AuditLog.timestamp.desc()).first()
        receiving_locked = root.RunInput.query.join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).filter(
            root.PurchaseLot.purchase_id == purchase.id,
            root.PurchaseLot.deleted_at.is_(None),
        ).count() > 0
        purchase_audit_photos = root.PhotoAsset.query.filter(
            root.PhotoAsset.purchase_id == purchase.id,
            root.PhotoAsset.source_type.in_(("field_submission", "mobile_api", "desk_purchase_intake")),
            root.or_(root.PhotoAsset.photo_context.is_(None), root.PhotoAsset.photo_context == "opportunity"),
        ).order_by(root.PhotoAsset.uploaded_at.desc()).all()
        purchase_delivery_photos = root.PhotoAsset.query.filter(
            root.PhotoAsset.purchase_id == purchase.id,
            root.PhotoAsset.source_type == "mobile_api",
            root.PhotoAsset.photo_context == "delivery",
        ).order_by(root.PhotoAsset.uploaded_at.desc()).all()
        purchase_support_docs = root.PhotoAsset.query.filter(
            root.PhotoAsset.purchase_id == purchase.id,
            root.PhotoAsset.source_type == "purchase_upload",
        ).order_by(root.PhotoAsset.uploaded_at.desc()).all()
        purchase_origin_summary = {
            "source_label": "Mobile app" if purchase.created_by_user_id else "Back office",
            "created_by_name": purchase.created_by_user.display_name if purchase.created_by_user else None,
            "delivery_recorded_by_name": purchase.delivery_recorded_by.display_name if purchase.delivery_recorded_by else None,
            "opportunity_photo_count": len(purchase_audit_photos),
            "delivery_photo_count": len(purchase_delivery_photos),
            "receiving_editable": bool(
                purchase.deleted_at is None
                and (purchase.status or "").strip().lower() == "delivered"
                and not receiving_locked
            ),
            "receiving_locked_reason": (
                "Locked after downstream processing started." if receiving_locked
                else ("Receiving is still awaiting confirmation." if (purchase.status or "").strip().lower() != "delivered" else None)
            ),
            "last_receiving_edit_at": last_receiving_edit.timestamp if last_receiving_edit else None,
            "last_receiving_edit_by_name": last_receiving_edit.user.display_name if last_receiving_edit and last_receiving_edit.user else None,
        }
    return {
        "purchase": purchase,
        "suppliers": suppliers,
        "rate": rate,
        "today": date.today(),
        "purchase_audit_photos": purchase_audit_photos,
        "purchase_delivery_photos": purchase_delivery_photos,
        "purchase_support_docs": purchase_support_docs,
        "purchase_origin_summary": purchase_origin_summary,
    }


def _safe_purchase_return_url(root, raw: str, default_endpoint: str = "purchases_list") -> str:
    path = (raw or "").strip()
    if not path.startswith("/") or "\n" in path or "\r" in path or len(path) > 512:
        return root.url_for(default_endpoint)
    return path


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
    is_opportunity = not purchase.is_approved and (purchase.status or "").strip().lower() == "ordered"
    exceptions: list[str] = []
    if not purchase.is_approved:
        exceptions.append("Approval required")
    if not active_lots and float(purchase.stated_weight_lbs or 0) > 0:
        exceptions.append("No inventory lots")
    if active_lots and tracking_ready < len(active_lots):
        exceptions.append("Tracking incomplete")
    if purchase.price_per_lb in (None, 0):
        exceptions.append("Missing price")
    purchase._display_status_key = "opportunity" if is_opportunity else (purchase.status or "")
    purchase._display_status_label = "Opportunity" if is_opportunity else (purchase.status or "").replace("_", " ")
    purchase._allocation_state_key = "pending_approval" if is_opportunity else state_key
    purchase._allocation_state_label = "Pending approval" if is_opportunity else state_label
    purchase._lot_count = len(active_lots)
    purchase._tracking_ready_count = tracking_ready
    purchase._total_weight = total_weight
    purchase._total_allocated = total_allocated
    purchase._total_remaining = total_remaining
    purchase._exceptions = exceptions
    purchase._intake_origin_label = "Mobile app" if purchase.created_by_user_id else "Back office"
    purchase._created_by_name = purchase.created_by_user.display_name if purchase.created_by_user else None
    purchase._delivery_recorded_by_name = purchase.delivery_recorded_by.display_name if purchase.delivery_recorded_by else None
    if is_opportunity:
        purchase._next_action = "Approve opportunity"
    elif not purchase.is_approved:
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
        m["hide_terminal"] = "1" if root.request.args.get("hide_terminal") == "1" else "0"
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
    hide_terminal = m.get("hide_terminal") != "0"
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
    elif hide_terminal:
        query = root._filter_operational_purchases(query)
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
        or not hide_terminal
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
    return_to = _safe_purchase_return_url(root, root.request.values.get("return_to") or "")
    if return_to == root.url_for("purchases_list"):
        fallback_edit_url = root.url_for("purchase_edit", purchase_id=purchase_id)
    else:
        fallback_edit_url = return_to
    if not root.current_user.can_approve_purchase:
        root.flash("Only users with purchase approval permission can approve purchases.", "error")
        return root.redirect(fallback_edit_url)
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))
    if purchase.is_approved:
        root.flash("Purchase is already approved.", "info")
        return root.redirect(fallback_edit_url)
    purchase.purchase_approved_at = datetime.now(timezone.utc)
    purchase.purchase_approved_by_user_id = root.current_user.id
    ensure_purchase_lot_tracking(purchase)
    root.log_audit("approve", "purchase", purchase.id)
    root.db.session.commit()
    root.flash(f"Purchase {purchase.batch_id or purchase.id} approved.", "success")
    return root.redirect(return_to if return_to != root.url_for("purchases_list") else fallback_edit_url)


def save_purchase(root, existing):
    try:
        purchase = existing or root.Purchase()
        purchase.supplier_id = root.request.form["supplier_id"]
        purchase.purchase_date = datetime.strptime(root.request.form["purchase_date"], "%Y-%m-%d").date()
        availability_date_raw = root.request.form.get("availability_date", "").strip()
        purchase.availability_date = datetime.strptime(availability_date_raw, "%Y-%m-%d").date() if availability_date_raw else None
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
        purchase.testing_notes = root.request.form.get("testing_notes", "").strip() or None
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


def lot_split_view(root, lot_id):
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None or not lot.purchase or lot.purchase.deleted_at is not None:
        root.flash("Lot not found.", "error")
        return root.redirect(root.url_for("purchases_list"))

    purchase_id = lot.purchase_id
    try:
        remaining_weight = float(lot.remaining_weight_lbs or 0)
        total_weight = float(lot.weight_lbs or 0)
        split_weight = float(root.request.form.get("split_weight_lbs") or 0)
        if remaining_weight <= 0:
            raise ValueError("Only lots with remaining inventory can be split.")
        if split_weight <= 0:
            raise ValueError("Split weight must be greater than zero.")
        if split_weight >= remaining_weight:
            raise ValueError("Split weight must be less than the lot's remaining weight.")

        strain_name = (root.request.form.get("strain_name") or "").strip() or lot.strain_name
        location = (root.request.form.get("location") or "").strip() or lot.location
        notes = (root.request.form.get("notes") or "").strip() or lot.notes
        potency_raw = (root.request.form.get("potency_pct") or "").strip()
        potency_pct = float(potency_raw) if potency_raw else lot.potency_pct

        lot.weight_lbs = total_weight - split_weight
        lot.remaining_weight_lbs = remaining_weight - split_weight

        new_lot = root.PurchaseLot(
            purchase_id=lot.purchase_id,
            strain_name=strain_name,
            weight_lbs=split_weight,
            remaining_weight_lbs=split_weight,
            potency_pct=potency_pct,
            milled=lot.milled,
            floor_state=lot.floor_state,
            location=location,
            notes=notes,
        )
        ensure_lot_tracking_fields(new_lot)
        root.db.session.add(new_lot)
        root.db.session.flush()
        root.log_audit(
            "split",
            "lot",
            lot.id,
            details=root.json.dumps(
                {
                    "new_lot_id": new_lot.id,
                    "purchase_id": purchase_id,
                    "split_weight_lbs": split_weight,
                    "original_tracking_id": lot.tracking_id,
                    "new_tracking_id": new_lot.tracking_id,
                }
            ),
        )
        root.db.session.commit()
        root.flash("Lot split saved.", "success")
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("Error splitting lot")
        root.flash("Error splitting lot. Please check your inputs and try again.", "error")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))


def lot_label_view(root, lot_id):
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None:
        root.flash("Lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    ensure_lot_tracking_fields(lot)
    root.db.session.commit()
    label = build_lot_label_payload(lot)
    raw_return_to = root.request.args.get("return_to") or ""
    return_to = _safe_purchase_return_url(root, raw_return_to, default_endpoint="purchases_list")
    if not raw_return_to.strip():
        return_to = root.url_for("purchase_edit", purchase_id=lot.purchase.id)
    if return_to == root.url_for("inventory") or return_to.startswith(f"{root.url_for('inventory')}?"):
        return_label = "Back to inventory"
    elif return_to == root.url_for("purchases_list") or return_to.startswith(f"{root.url_for('purchases_list')}?"):
        return_label = "Back to purchases"
    else:
        return_label = "Back to purchase"
    barcode_only = _is_barcode_only_label_request(root)
    return root.render_template(
        "lot_label_print.html",
        labels=[label],
        purchase=lot.purchase,
        return_to=return_to,
        return_label=return_label,
        barcode_only=barcode_only,
    )


def lot_edit_view(root, lot_id):
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot or lot.deleted_at is not None or not lot.purchase or lot.purchase.deleted_at is not None:
        root.flash("Lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    raw_return_to = root.request.values.get("return_to") or root.request.referrer or ""
    return_to = _safe_purchase_return_url(root, raw_return_to, default_endpoint="inventory")
    if root.request.method == "POST":
        try:
            lot.strain_name = (root.request.form.get("strain_name") or "").strip() or lot.strain_name
            potency_raw = (root.request.form.get("potency_pct") or "").strip()
            lot.potency_pct = float(potency_raw) if potency_raw else None
            lot.location = (root.request.form.get("location") or "").strip() or None
            floor_state = (root.request.form.get("floor_state") or "").strip()
            lot.floor_state = floor_state or "inventory"
            lot.milled = root.request.form.get("milled_state") == "milled"
            lot.notes = (root.request.form.get("notes") or "").strip() or None
            root.log_audit(
                "update",
                "lot",
                lot.id,
                details=root.json.dumps(
                    {
                        "source": "lot_edit",
                        "purchase_id": lot.purchase_id,
                        "return_to": return_to,
                    }
                ),
            )
            root.db.session.commit()
            root.flash("Lot updated.", "success")
            return root.redirect(return_to)
        except ValueError:
            root.db.session.rollback()
            root.flash("Enter a valid potency percentage.", "error")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("Error updating lot")
            root.flash("Error updating lot. Please check your inputs and try again.", "error")
    return root.render_template("lot_edit.html", lot=lot, purchase=lot.purchase, return_to=return_to)


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
    raw_return_to = root.request.args.get("return_to") or ""
    return_to = _safe_purchase_return_url(root, raw_return_to, default_endpoint="purchases_list")
    if not raw_return_to.strip():
        return_to = root.url_for("purchase_edit", purchase_id=purchase.id)
    journey_url = root.url_for("purchases_bp.purchase_journey", purchase_id=purchase.id)
    return_label = "Back to journey" if return_to == journey_url else "Back to purchase"
    if return_to == root.url_for("purchase_edit", purchase_id=purchase.id):
        return_label = "Back to purchase"
    elif return_to == root.url_for("purchases_list") or return_to.startswith(f"{root.url_for('purchases_list')}?"):
        return_label = "Back to purchases"
    barcode_only = _is_barcode_only_label_request(root)
    return root.render_template(
        "lot_label_print.html",
        labels=labels,
        purchase=purchase,
        return_to=return_to,
        return_label=return_label,
        barcode_only=barcode_only,
    )


def _is_barcode_only_label_request(root) -> bool:
    mode = (root.request.args.get("mode") or "").strip().lower()
    barcode_only = (root.request.args.get("barcode_only") or "").strip().lower()
    return mode in {"barcode", "barcodes", "barcode_only"} or barcode_only in {"1", "true", "yes", "on"}


def _get_scannable_lot(root, tracking_id):
    lot = root.PurchaseLot.query.filter(
        root.PurchaseLot.tracking_id == tracking_id,
        root.PurchaseLot.deleted_at.is_(None),
    ).first()
    if not lot or not lot.purchase or lot.purchase.deleted_at is not None:
        return None
    return lot


def _record_lot_scan_event(root, lot, action: str, *, context: dict | None = None):
    event = root.LotScanEvent(
        lot_id=lot.id,
        tracking_id_snapshot=lot.tracking_id or "",
        action=action,
        user_id=getattr(root.current_user, "id", None),
    )
    event.set_context(context or {})
    root.db.session.add(event)
    return event


def _charge_form_prefill(root, lot):
    remaining_weight_lbs = float(lot.remaining_weight_lbs or 0)
    run_start_mode = (root.request.args.get("run_start_mode") or "").strip()
    requested_weight_raw = (root.request.args.get("requested_weight_lbs") or "").strip()
    scale_device_id = (root.request.args.get("scale_device_id") or "").strip()
    reactor_number = (root.request.args.get("reactor_number") or "").strip()
    charged_weight_lbs = ""
    if run_start_mode == "full_remaining":
        charged_weight_lbs = f"{remaining_weight_lbs:.1f}"
    elif run_start_mode == "partial":
        charged_weight_lbs = requested_weight_raw
    testing_status = (getattr(lot.purchase, "testing_status", None) or "pending").strip()
    warnings: list[str] = []
    if testing_status not in {"completed", "not_needed"}:
        warnings.append("Testing is not marked complete or waived. Extraction is allowed, but review this lot's current testing state before charging.")
    if not getattr(lot, "milled", False):
        warnings.append("Lot prep is still marked not milled.")
    if (getattr(lot, "floor_state", None) or "inventory").strip() != "reactor_staging":
        warnings.append("Lot is not currently marked in reactor staging.")
    return {
        "run_start_mode": run_start_mode,
        "requested_weight_lbs": charged_weight_lbs,
        "scale_device_id": scale_device_id,
        "reactor_number": reactor_number,
        "charged_at": default_charge_datetime_local(),
        "warnings": warnings,
    }


def _render_charge_form(root, lot, *, entry_mode: str, back_url: str):
    prefill = _charge_form_prefill(root, lot)
    return root.render_template(
        "extraction_charge_form.html",
        lot=lot,
        purchase=lot.purchase,
        entry_mode=entry_mode,
        back_url=back_url,
        charge_defaults=prefill,
        reactor_options=list(range(1, max(int(reactor_count(root) or 1), 1) + 1)),
    )


def _submit_charge_form(root, lot, *, entry_mode: str):
    back_url = (
        root.url_for("scan_lot", tracking_id=lot.tracking_id)
        if entry_mode == "scan"
        else root.url_for("purchase_edit", purchase_id=lot.purchase.id)
    )
    charged_weight_raw = (root.request.form.get("charged_weight_lbs") or "").strip()
    reactor_raw = (root.request.form.get("reactor_number") or "").strip()
    charged_at_raw = (root.request.form.get("charged_at") or "").strip()
    notes = (root.request.form.get("notes") or "").strip() or None
    scale_device_id = (root.request.form.get("scale_device_id") or "").strip()

    try:
        validate_chargeable_lot(root, lot)
        charged_weight_lbs = float(charged_weight_raw)
        reactor_number = int(reactor_raw)
        charged_at = parse_charge_datetime(charged_at_raw)

        lot_scan_event = None
        if entry_mode == "scan":
            lot_scan_event = _record_lot_scan_event(
                root,
                lot,
                "extraction_charge",
                context={
                    "purchase_id": lot.purchase.id,
                    "charged_weight_lbs": charged_weight_lbs,
                    "reactor_number": reactor_number,
                    "charged_at": charged_at.isoformat(),
                    "source_mode": "scan",
                },
            )
            root.db.session.flush()

        charge = create_extraction_charge(
            root,
            lot=lot,
            charged_weight_lbs=charged_weight_lbs,
            reactor_number=reactor_number,
            charged_at=charged_at,
            source_mode="scan" if entry_mode == "scan" else "main_app",
            notes=notes,
            lot_scan_event_id=lot_scan_event.id if lot_scan_event else None,
        )
        root.session[root.SCAN_RUN_PREFILL_SESSION_KEY] = build_charge_prefill_payload(
            root,
            lot,
            charge,
            scale_device_id=scale_device_id,
        )
        root.db.session.commit()
        root.flash(
            f"Extraction charge recorded for {charged_weight_lbs:.1f} lbs into Reactor {reactor_number}. Finish the run details next.",
            "success",
        )
        return root.redirect(root.url_for("run_new", return_to=back_url))
    except Exception as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return _render_charge_form(root, lot, entry_mode=entry_mode, back_url=back_url)


def scan_lot_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    _record_lot_scan_event(
        root,
        lot,
        "scan_open",
        context={"purchase_id": lot.purchase.id},
    )
    root.db.session.commit()
    recent_events = lot.scan_events.order_by(root.LotScanEvent.created_at.desc()).limit(8).all()
    return root.render_template(
        "lot_scan.html",
        lot=lot,
        purchase=lot.purchase,
        recent_events=recent_events,
        movement_options=MOVEMENT_OPTIONS,
        scale_devices=root.ScaleDevice.query.filter_by(is_active=True).order_by(root.ScaleDevice.name.asc()).all(),
    )


def scan_lot_start_run_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    remaining_weight_lbs = float(lot.remaining_weight_lbs or 0)
    run_start_mode = (root.request.form.get("run_start_mode") or "blank").strip()
    requested_weight_raw = (root.request.form.get("requested_weight_lbs") or "").strip()
    scale_device_id = (root.request.form.get("scale_device_id") or "").strip()
    planned_weight_lbs = None

    if run_start_mode == "full_remaining":
        planned_weight_lbs = remaining_weight_lbs
    elif run_start_mode == "partial":
        try:
            planned_weight_lbs = float(requested_weight_raw)
        except ValueError:
            root.flash("Enter a valid partial amount before starting the run.", "error")
            return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
        if planned_weight_lbs <= 0:
            root.flash("Partial run amount must be greater than zero.", "error")
            return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
        if planned_weight_lbs > remaining_weight_lbs + 1e-9:
            root.flash(f"Partial run amount cannot exceed the lot's {remaining_weight_lbs:.1f} lbs remaining.", "error")
            return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
    else:
        run_start_mode = "scale_capture" if run_start_mode == "scale_capture" else "blank"

    _record_lot_scan_event(
        root,
        lot,
        "start_run",
        context={
            "purchase_id": lot.purchase.id,
            "run_start_mode": run_start_mode,
            "planned_weight_lbs": planned_weight_lbs,
            "scale_device_id": scale_device_id or None,
        },
    )
    root.db.session.commit()
    params = {
        "run_start_mode": run_start_mode,
        "scale_device_id": scale_device_id or "",
    }
    if planned_weight_lbs is not None:
        params["requested_weight_lbs"] = f"{planned_weight_lbs:.1f}"
    root.flash("Review reactor, weight, and charge time before opening the run form.", "success")
    return root.redirect(root.url_for("scan_lot_charge", tracking_id=tracking_id, **params))


def lot_charge_view(root, lot_id):
    lot = root.db.session.get(root.PurchaseLot, lot_id)
    if not lot:
        root.flash("Lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    try:
        validate_chargeable_lot(root, lot)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("purchase_edit", purchase_id=lot.purchase.id if lot.purchase else None))
    if root.request.method == "POST":
        return _submit_charge_form(root, lot, entry_mode="main_app")
    return _render_charge_form(root, lot, entry_mode="main_app", back_url=root.url_for("purchase_edit", purchase_id=lot.purchase.id))


def scan_lot_charge_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    try:
        validate_chargeable_lot(root, lot)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
    if root.request.method == "POST":
        return _submit_charge_form(root, lot, entry_mode="scan")
    return _render_charge_form(root, lot, entry_mode="scan", back_url=root.url_for("scan_lot", tracking_id=tracking_id))


def scan_lot_confirm_movement_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    movement_code = (root.request.form.get("movement_code") or "custom").strip()
    option_map = {item["code"]: item for item in MOVEMENT_OPTIONS}
    selected = option_map.get(movement_code, option_map["custom"])
    location_detail = (root.request.form.get("location") or "").strip()
    new_location = location_detail or (selected.get("default_location") or "").strip()
    if not new_location:
        root.flash("Enter a storage location before confirming movement.", "error")
        return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
    lot.location = new_location
    lot.floor_state = selected.get("floor_state") or "inventory"
    _record_lot_scan_event(
        root,
        lot,
        "confirm_movement",
        context={
            "purchase_id": lot.purchase.id,
            "movement_code": movement_code,
            "movement_label": selected["label"],
            "floor_state": lot.floor_state,
            "location": new_location,
        },
    )
    root.db.session.commit()
    root.flash(f"{selected['label']} confirmed: {new_location}.", "success")
    return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))


def scan_lot_confirm_testing_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    purchase = lot.purchase
    testing_status = (root.request.form.get("testing_status") or "").strip()
    if testing_status not in ("pending", "completed", "not_needed"):
        root.flash("Choose a valid testing status.", "error")
        return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
    purchase.testing_status = testing_status
    if testing_status == "completed" and not purchase.testing_date:
        purchase.testing_date = root.date.today()
    elif testing_status != "completed":
        purchase.testing_date = None
    _record_lot_scan_event(
        root,
        lot,
        "confirm_testing",
        context={"purchase_id": lot.purchase.id, "testing_status": testing_status},
    )
    root.db.session.commit()
    root.flash(f"Testing status updated to {testing_status.replace('_', ' ')}.", "success")
    return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))


def scan_lot_confirm_milled_view(root, tracking_id):
    lot = _get_scannable_lot(root, tracking_id)
    if not lot:
        root.flash("Tracked lot not found.", "error")
        return root.redirect(root.url_for("inventory"))
    milled_state = (root.request.form.get("milled_state") or "").strip().lower()
    if milled_state not in {"milled", "not_milled"}:
        root.flash("Choose a valid prep state.", "error")
        return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))
    lot.milled = milled_state == "milled"
    _record_lot_scan_event(
        root,
        lot,
        "confirm_milled",
        context={
            "purchase_id": lot.purchase.id,
            "milled": bool(lot.milled),
        },
    )
    root.db.session.commit()
    root.flash(f"Lot prep updated to {'milled' if lot.milled else 'not milled'}.", "success")
    return root.redirect(root.url_for("scan_lot", tracking_id=tracking_id))


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
