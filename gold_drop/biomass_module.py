from __future__ import annotations

import json
from datetime import date, datetime


def _biomass_form_context(root, item):
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    return {
        "item": item,
        "suppliers": suppliers,
        "today": date.today(),
    }


def biomass_list_view(root):
    root._apply_biomass_potential_soft_delete()
    redir = root._list_filters_clear_redirect("biomass_list")
    if redir:
        return redir
    m = root._list_filters_merge(
        "biomass_list",
        ("bucket", "stage", "start_date", "end_date", "supplier_id", "strain"),
    )
    days_to_old, days_to_soft_delete = root._potential_lot_age_days()
    bucket = (m.get("bucket") or "current").strip().lower()
    if bucket == "deleted" and not root.current_user.is_super_admin:
        bucket = "current"
        root.flash("Only Super Admins can view soft-deleted biomass rows.", "info")
    stage = (m.get("stage") or "").strip()
    start_raw = (m.get("start_date") or "").strip()
    end_raw = (m.get("end_date") or "").strip()
    supplier_filter = (m.get("supplier_id") or "").strip()
    strain_filter = (m.get("strain") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    query = root.Purchase.query.join(root.Supplier)
    query = root._biomass_bucket_filter(query, bucket, days_to_old, days_to_soft_delete)
    if stage:
        mapped_status = root._STAGE_TO_STATUS.get(stage, stage)
        query = query.filter(root.Purchase.status == mapped_status)
    if start_date:
        query = query.filter(root.Purchase.availability_date >= start_date)
    if end_date:
        query = query.filter(root.Purchase.availability_date <= end_date)
    if supplier_filter:
        query = query.filter(root.Purchase.supplier_id == supplier_filter)
    if strain_filter:
        query = query.filter(
            root.Purchase.id.in_(
                root.db.session.query(root.PurchaseLot.purchase_id).filter(
                    root.func.lower(root.PurchaseLot.strain_name).like(f"%{strain_filter.lower()}%"),
                    root.PurchaseLot.deleted_at.is_(None),
                )
            )
        )
    items = query.order_by(
        root.Purchase.availability_date.desc().nullslast(),
        root.Purchase.purchase_date.desc().nullslast(),
        root.Supplier.name.asc(),
    ).all()
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    biomass_filters_active = (
        bucket != "current"
        or bool(stage or start_raw or end_raw or supplier_filter or strain_filter)
    )
    return root.render_template(
        "biomass.html",
        items=items,
        stage_filter=stage,
        bucket_filter=bucket,
        potential_days_to_old=days_to_old,
        potential_days_to_soft_delete=days_to_soft_delete,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        start_date=start_raw,
        end_date=end_raw,
        strain_filter=strain_filter,
        list_filters_active=biomass_filters_active,
        clear_filters_url=root.url_for("biomass_list", clear_filters=1),
    )


def biomass_new_view(root):
    if root.request.method == "POST":
        return save_biomass_purchase(root, None)
    return root.render_template("biomass_form.html", **_biomass_form_context(root, None))


def biomass_edit_view(root, item_id):
    item = root.db.session.get(root.Purchase, item_id)
    if not item:
        root.flash("Biomass availability record not found.", "error")
        return root.redirect(root.url_for("biomass_list"))
    if item.deleted_at and not root.current_user.is_super_admin:
        root.flash("This biomass row was archived (soft-deleted). Super Admins can view it from the Archived list.", "error")
        return root.redirect(root.url_for("biomass_list"))
    if root.request.method == "POST":
        return save_biomass_purchase(root, item)
    return root.render_template("biomass_form.html", **_biomass_form_context(root, item))


def biomass_restore_view(root, item_id):
    item = root.db.session.get(root.Purchase, item_id)
    if not item or not item.deleted_at:
        root.flash("Nothing to restore.", "error")
        return root.redirect(root.url_for("biomass_list"))
    item.deleted_at = None
    for lot in item.lots:
        lot.deleted_at = None
    root.log_audit("restore", "purchase", item.id, details=json.dumps({"source": "biomass_pipeline_archive"}))
    root.db.session.commit()
    root.flash("Biomass row restored from archive.", "success")
    return root.redirect(root.url_for("biomass_edit", item_id=item_id))


def save_biomass_purchase(root, existing):
    try:
        if existing and existing.deleted_at:
            raise ValueError("This row is archived. Restore it from the biomass list before editing.")
        prev_status = existing.status if existing else None
        purchase = existing or root.Purchase()

        supplier_id = (root.request.form.get("supplier_id") or "").strip()
        if not supplier_id:
            raise ValueError("Supplier is required.")
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        purchase.supplier_id = supplier_id

        availability_date_raw = root.request.form.get("availability_date", "").strip()
        if not availability_date_raw:
            raise ValueError("Availability Date is required.")
        try:
            purchase.availability_date = datetime.strptime(availability_date_raw, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Availability Date must be a valid date.")

        strain_name = root.request.form.get("strain_name", "").strip() or None

        declared_weight_raw = root.request.form.get("declared_weight_lbs", "").strip()
        try:
            purchase.declared_weight_lbs = float(declared_weight_raw) if declared_weight_raw else 0.0
        except ValueError:
            raise ValueError("Declared Weight must be a number.")
        if purchase.declared_weight_lbs < 0:
            raise ValueError("Declared Weight cannot be negative.")

        declared_price_raw = root.request.form.get("declared_price_per_lb", "").strip()
        try:
            purchase.declared_price_per_lb = float(declared_price_raw) if declared_price_raw else None
        except ValueError:
            raise ValueError("Declared $/lb must be a number.")
        if purchase.declared_price_per_lb is not None and purchase.declared_price_per_lb < 0:
            raise ValueError("Declared $/lb cannot be negative.")

        estimated_potency_raw = root.request.form.get("estimated_potency_pct", "").strip()
        try:
            estimated_potency = float(estimated_potency_raw) if estimated_potency_raw else None
        except ValueError:
            raise ValueError("Estimated Potency must be a number.")
        if estimated_potency is not None and not (0 <= estimated_potency <= 100):
            raise ValueError("Estimated Potency must be between 0 and 100.")
        purchase.stated_potency_pct = estimated_potency

        testing_timing = (root.request.form.get("testing_timing") or "before_delivery").strip()
        if testing_timing not in ("before_delivery", "after_delivery"):
            raise ValueError("Testing Timing is invalid.")
        purchase.testing_timing = testing_timing

        testing_status = (root.request.form.get("testing_status") or "pending").strip()
        if testing_status not in ("pending", "completed", "not_needed"):
            raise ValueError("Testing Status is invalid.")
        purchase.testing_status = testing_status

        testing_date_raw = root.request.form.get("testing_date", "").strip()
        if testing_date_raw:
            try:
                purchase.testing_date = datetime.strptime(testing_date_raw, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Testing Date must be a valid date.")
        else:
            purchase.testing_date = None

        tested_potency_raw = root.request.form.get("tested_potency_pct", "").strip()
        try:
            purchase.tested_potency_pct = float(tested_potency_raw) if tested_potency_raw else None
        except ValueError:
            raise ValueError("Tested Potency must be a number.")
        if purchase.tested_potency_pct is not None and not (0 <= purchase.tested_potency_pct <= 100):
            raise ValueError("Tested Potency must be between 0 and 100.")

        committed_on_raw = root.request.form.get("committed_on", "").strip()
        if committed_on_raw:
            try:
                purchase.purchase_date = datetime.strptime(committed_on_raw, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Committed On must be a valid date.")
        else:
            purchase.purchase_date = purchase.purchase_date or purchase.availability_date

        committed_delivery_raw = root.request.form.get("committed_delivery_date", "").strip()
        if committed_delivery_raw:
            try:
                purchase.delivery_date = datetime.strptime(committed_delivery_raw, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Delivery Date must be a valid date.")
        else:
            purchase.delivery_date = None

        committed_weight_raw = root.request.form.get("committed_weight_lbs", "").strip()
        try:
            committed_weight = float(committed_weight_raw) if committed_weight_raw else None
        except ValueError:
            raise ValueError("Committed Weight must be a number.")
        if committed_weight is not None and committed_weight < 0:
            raise ValueError("Committed Weight cannot be negative.")
        purchase.stated_weight_lbs = committed_weight or purchase.declared_weight_lbs or 0

        committed_price_raw = root.request.form.get("committed_price_per_lb", "").strip()
        try:
            committed_price = float(committed_price_raw) if committed_price_raw else None
        except ValueError:
            raise ValueError("Committed $/lb must be a number.")
        if committed_price is not None and committed_price < 0:
            raise ValueError("Committed $/lb cannot be negative.")
        purchase.price_per_lb = committed_price or purchase.declared_price_per_lb

        stage = (root.request.form.get("stage") or "declared").strip()
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

        if new_status == "delivered" and prev_status not in ("committed", "delivered", None):
            raise ValueError(
                "Material cannot be marked as Delivered without first being Committed. "
                "Move the batch to Committed, then to Delivered."
            )

        enters_commitment = new_status == "committed" and prev_status not in ("committed", "delivered")
        leaves_commitment = prev_status in ("committed", "delivered") and new_status not in ("committed", "delivered")
        if enters_commitment or leaves_commitment:
            if not root.current_user.can_approve_purchase:
                raise ValueError(
                    "Only Super Admin or users with purchase approval permission can move a batch "
                    "to or from Committed / Delivered."
                )
        if enters_commitment:
            purchase.purchase_approved_at = datetime.utcnow()
            purchase.purchase_approved_by_user_id = root.current_user.id

        purchase.status = new_status
        purchase.notes = root.request.form.get("notes", "").strip() or None

        weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
        if weight and purchase.price_per_lb:
            purchase.total_cost = weight * purchase.price_per_lb

        if purchase.stated_potency_pct and not purchase.price_per_lb:
            rate = root.SystemSetting.get_float("potency_rate", 1.50)
            purchase.price_per_lb = rate * purchase.stated_potency_pct

        if not existing:
            root.db.session.add(purchase)
        root.db.session.flush()

        if not purchase.batch_id:
            supplier = root.db.session.get(root.Supplier, purchase.supplier_id)
            supplier_name = supplier.name if supplier else "BATCH"
            batch_date = purchase.delivery_date or purchase.purchase_date or purchase.availability_date
            batch_weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
            purchase.batch_id = root._ensure_unique_batch_id(
                root._generate_batch_id(supplier_name, batch_date, batch_weight),
                exclude_purchase_id=purchase.id,
            )

        first_lot = purchase.lots.first()
        if strain_name:
            if first_lot:
                first_lot.strain_name = strain_name
                first_lot.weight_lbs = purchase.stated_weight_lbs or purchase.declared_weight_lbs or 0
                first_lot.remaining_weight_lbs = first_lot.weight_lbs
                if estimated_potency:
                    first_lot.potency_pct = purchase.tested_potency_pct or estimated_potency
            else:
                lot = root.PurchaseLot(
                    purchase_id=purchase.id,
                    strain_name=strain_name,
                    weight_lbs=purchase.stated_weight_lbs or purchase.declared_weight_lbs or 0,
                    remaining_weight_lbs=purchase.stated_weight_lbs or purchase.declared_weight_lbs or 0,
                    potency_pct=purchase.tested_potency_pct or estimated_potency,
                )
                root.db.session.add(lot)

        if enters_commitment:
            root.log_audit(
                "purchase_approval",
                "purchase",
                purchase.id,
                details=json.dumps({
                    "approver_user_id": root.current_user.id,
                    "status": purchase.status,
                    "source": "biomass_pipeline",
                }),
            )

        root.log_audit(
            "update" if existing else "create",
            "purchase",
            purchase.id,
            details=json.dumps({"source": "biomass_pipeline", "status": purchase.status}),
        )
        root.db.session.commit()
        root.flash("Biomass availability saved.", "success")
        return root.redirect(root.url_for("biomass_list"))
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return root.render_template("biomass_form.html", **_biomass_form_context(root, existing))
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("Error saving biomass availability")
        root.flash("Error saving biomass availability. Please check your inputs and try again.", "error")
        return root.render_template("biomass_form.html", **_biomass_form_context(root, existing))


def biomass_delete_view(root, item_id):
    item = root.db.session.get(root.Purchase, item_id)
    if item:
        deleted_at = datetime.utcnow()
        item.deleted_at = deleted_at
        item.deleted_by = root.current_user.id
        for lot in item.lots:
            lot.deleted_at = deleted_at
            lot.deleted_by = root.current_user.id
        root.log_audit("delete", "purchase", item.id, details=json.dumps({"mode": "soft", "source": "biomass_pipeline"}))
        root.db.session.commit()
        root.flash("Biomass record deleted.", "success")
    return root.redirect(root.url_for("biomass_list"))
