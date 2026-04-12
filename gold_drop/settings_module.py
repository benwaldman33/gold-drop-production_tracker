from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gold_drop.purchases import (
    biomass_budget_snapshot_for_purchase,
    enforce_weekly_biomass_purchase_limits,
)
from services.field_submissions import (
    decorate_submission_rows,
    field_approval_return_redirect,
    field_submission_error_redirect,
    load_lots,
    promote_submission_photos,
    submission_total_weight,
)


def register_routes(app, root):
    @root.admin_required
    def settings():
        return settings_view(root)

    @root.login_required
    def field_approvals():
        return field_approvals_view(root)

    @root.field_purchase_approval_required
    def field_submission_approve(submission_id):
        return field_submission_approve_view(root, submission_id)

    @root.field_purchase_approval_required
    def field_submission_reject(submission_id):
        return field_submission_reject_view(root, submission_id)

    @root.admin_required
    def settings_backfill_photo_assets():
        return settings_backfill_photo_assets_view(root)

    app.add_url_rule("/settings", endpoint="settings", view_func=settings, methods=["GET", "POST"])
    app.add_url_rule("/field-approvals", endpoint="field_approvals", view_func=field_approvals)
    app.add_url_rule(
        "/settings/field_submissions/<submission_id>/approve",
        endpoint="field_submission_approve",
        view_func=field_submission_approve,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/field_submissions/<submission_id>/reject",
        endpoint="field_submission_reject",
        view_func=field_submission_reject,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/backfill_photo_assets",
        endpoint="settings_backfill_photo_assets",
        view_func=settings_backfill_photo_assets,
        methods=["POST"],
    )


def settings_redirect(root):
    anchor = (root.request.form.get("return_to") or root.request.args.get("return_to") or "").strip()
    target = root.url_for("settings")
    if anchor:
        if not anchor.startswith("#"):
            anchor = f"#{anchor.lstrip('#')}"
        target = f"{target}{anchor}"
    return root.redirect(target)


def settings_view(root):
    if root.request.method == "POST":
        form_type = root.request.form.get("form_type")

        if form_type == "system":
            settings_map = {
                "potency_rate": "Potency Rate ($/lb/%pt)",
                "num_reactors": "Number of Reactors",
                "reactor_capacity": "Reactor Capacity (lbs)",
                "runs_per_day": "Runs Per Day Target",
                "operating_days": "Operating Days Per Week",
                "daily_throughput_target": "Daily Throughput Target (lbs)",
                "weekly_throughput_target": "Weekly Throughput Target (lbs)",
            }
            for key, desc in settings_map.items():
                val = root.request.form.get(key, "").strip()
                if val:
                    existing = root.db.session.get(root.SystemSetting, key)
                    if existing:
                        existing.value = val
                    else:
                        root.db.session.add(root.SystemSetting(key=key, value=val, description=desc))

            method = (root.request.form.get("cost_allocation_method") or "per_gram_uniform").strip()
            if method not in ("per_gram_uniform", "split_50_50", "custom_split"):
                method = "per_gram_uniform"
            existing = root.db.session.get(root.SystemSetting, "cost_allocation_method")
            if existing:
                existing.value = method
            else:
                root.db.session.add(root.SystemSetting(
                    key="cost_allocation_method",
                    value=method,
                    description="Cost allocation method for THCA vs HTE cost/gram",
                ))

            pct_raw = (root.request.form.get("cost_allocation_thca_pct") or "").strip()
            try:
                pct = float(pct_raw) if pct_raw else 50.0
            except ValueError:
                pct = 50.0
            pct = max(0.0, min(100.0, pct))
            existing = root.db.session.get(root.SystemSetting, "cost_allocation_thca_pct")
            if existing:
                existing.value = str(pct)
            else:
                root.db.session.add(root.SystemSetting(
                    key="cost_allocation_thca_pct",
                    value=str(pct),
                    description="Custom cost allocation: percent of total run cost allocated to THCA",
                ))

            exclude_val = "1" if root.request.form.get("exclude_unpriced_batches") else "0"
            existing = root.db.session.get(root.SystemSetting, "exclude_unpriced_batches")
            if existing:
                existing.value = exclude_val
            else:
                root.db.session.add(root.SystemSetting(
                    key="exclude_unpriced_batches",
                    value=exclude_val,
                    description="Exclude unpriced/unlinked runs from yield and cost analytics",
                ))
            wb_raw = (root.request.form.get("weekly_dollar_budget") or "").strip()
            try:
                wb_val = float(wb_raw) if wb_raw else 0.0
            except ValueError:
                wb_val = 0.0
            if wb_val < 0:
                wb_val = 0.0
            wb_existing = root.db.session.get(root.SystemSetting, "weekly_dollar_budget")
            if wb_existing:
                wb_existing.value = str(wb_val)
            else:
                root.db.session.add(root.SystemSetting(
                    key="weekly_dollar_budget",
                    value=str(wb_val),
                    description="Weekly dollar budget for buyer/finance snapshot (Dashboard)",
                ))

            n1_raw = (root.request.form.get("potential_lot_days_to_old") or "").strip()
            n2_raw = (root.request.form.get("potential_lot_days_to_soft_delete") or "").strip()
            try:
                n1 = int(float(n1_raw)) if n1_raw else 10
            except ValueError:
                n1 = 10
            try:
                n2 = int(float(n2_raw)) if n2_raw else 30
            except ValueError:
                n2 = 30
            if n1 < 1:
                n1 = 1
            if n2 < n1:
                n2 = n1
                root.flash("Potential lot 'days to soft-delete' was raised to match 'days to Old Lots' (must be >=).", "info")
            for key, val, desc in (
                ("potential_lot_days_to_old", str(n1), "Days before potential biomass moves to Old Lots"),
                ("potential_lot_days_to_soft_delete", str(n2), "Total days from created_at before soft-delete (potential rows)"),
            ):
                ex = root.db.session.get(root.SystemSetting, key)
                if ex:
                    ex.value = val
                else:
                    root.db.session.add(root.SystemSetting(key=key, value=val, description=desc))

            tz_raw = (root.request.form.get("app_display_timezone") or "").strip()
            tz_ok = True
            if tz_raw:
                try:
                    ZoneInfo(tz_raw)
                    tz_ex = root.db.session.get(root.SystemSetting, "app_display_timezone")
                    if tz_ex:
                        tz_ex.value = tz_raw
                    else:
                        root.db.session.add(root.SystemSetting(
                            key="app_display_timezone",
                            value=tz_raw,
                            description="IANA timezone: Slack message times, imports date filters, derived slack_message_date",
                        ))
                except ZoneInfoNotFoundError:
                    root.flash(f"Unknown timezone {tz_raw!r}; timezone was not changed.", "error")
                    tz_ok = False

            root.db.session.commit()
            root.flash("System settings updated." if tz_ok else "System settings saved; fix the timezone name and save again.", "success" if tz_ok else "info")

        elif form_type == "kpi":
            kpi_ids = root.request.form.getlist("kpi_ids[]")
            for kid in kpi_ids:
                kpi = root.db.session.get(root.KpiTarget, kid)
                if kpi:
                    kpi.target_value = float(root.request.form.get(f"target_{kid}", kpi.target_value))
                    kpi.green_threshold = float(root.request.form.get(f"green_{kid}", kpi.green_threshold))
                    kpi.yellow_threshold = float(root.request.form.get(f"yellow_{kid}", kpi.yellow_threshold))
                    kpi.updated_by = root.current_user.id
            root.db.session.commit()
            root.flash("KPI targets updated.", "success")

        elif form_type == "biomass_budget":
            usd_raw = (root.request.form.get("biomass_purchase_weekly_budget_usd") or "").strip()
            lbs_raw = (root.request.form.get("biomass_purchase_weekly_target_lbs") or "").strip()
            pot_raw = (root.request.form.get("biomass_purchase_weekly_target_potency_pct") or "").strip()
            try:
                usd = float(usd_raw) if usd_raw else 0.0
                lbs_t = float(lbs_raw) if lbs_raw else 0.0
                pot = float(pot_raw) if pot_raw else 0.0
            except ValueError:
                root.flash("Invalid biomass purchasing targets.", "error")
                return settings_redirect(root)
            usd = max(0.0, usd)
            lbs_t = max(0.0, lbs_t)
            pot = max(0.0, pot)

            def _upsert_budget(key, val, desc):
                row = root.db.session.get(root.SystemSetting, key)
                if row:
                    row.value = str(val)
                else:
                    root.db.session.add(root.SystemSetting(key=key, value=str(val), description=desc))

            _upsert_budget("biomass_purchase_weekly_budget_usd", usd, "Weekly biomass purchasing budget (USD)")
            _upsert_budget("biomass_purchase_weekly_target_lbs", lbs_t, "Weekly biomass purchasing volume target (lbs)")
            _upsert_budget("biomass_purchase_weekly_target_potency_pct", pot, "Weekly target weighted avg potency % (purchasing)")
            row_legacy = root.db.session.get(root.SystemSetting, "biomass_budget_target_potency_pct")
            if row_legacy:
                row_legacy.value = str(pot)
            elif pot > 0:
                root.db.session.add(root.SystemSetting(
                    key="biomass_budget_target_potency_pct",
                    value=str(pot),
                    description="Legacy mirror: target potency % (purchasing)",
                ))
            root.db.session.commit()
            root.flash("Biomass purchasing targets updated.", "success")

        elif form_type == "user":
            username = root.request.form.get("new_username", "").strip().lower()
            password = root.request.form.get("new_password", "").strip()
            display = root.request.form.get("new_display", "").strip()
            role = root.request.form.get("new_role", "viewer")
            allowed_roles = frozenset({"viewer", "user", "super_admin", "super_buyer"})
            if role not in allowed_roles:
                role = "viewer"
            if username and password and display:
                if root.User.query.filter_by(username=username).first():
                    root.flash("Username already exists.", "error")
                else:
                    if len(password) < 8:
                        root.flash("Password must be at least 8 characters.", "error")
                        return settings_redirect(root)
                    u = root.User(username=username, display_name=display, role=role)
                    u.set_password(password)
                    if role != "super_admin":
                        u.is_slack_importer = bool(root.request.form.get("new_slack_importer"))
                        u.is_purchase_approver = bool(root.request.form.get("new_purchase_approver"))
                    root.db.session.add(u)
                    root.db.session.commit()
                    root.flash(f"User '{display}' created.", "success")

        elif form_type == "password_self":
            current_pw = root.request.form.get("current_password", "")
            new_pw = root.request.form.get("new_password", "").strip()
            confirm_pw = root.request.form.get("confirm_password", "").strip()
            if not root.current_user.check_password(current_pw):
                root.flash("Current password is incorrect.", "error")
                return settings_redirect(root)
            if len(new_pw) < 8:
                root.flash("New password must be at least 8 characters.", "error")
                return settings_redirect(root)
            if new_pw != confirm_pw:
                root.flash("New password and confirmation do not match.", "error")
                return settings_redirect(root)
            root.current_user.set_password(new_pw)
            root.log_audit("password_change", "user", root.current_user.id, details=json.dumps({"username": root.current_user.username}))
            root.db.session.commit()
            root.flash("Password updated.", "success")

        elif form_type == "password_user":
            user_id = (root.request.form.get("user_id") or "").strip()
            new_pw = root.request.form.get("new_password", "").strip()
            confirm_pw = root.request.form.get("confirm_password", "").strip()
            u = root.db.session.get(root.User, user_id) if user_id else None
            if not u:
                root.flash("User not found.", "error")
                return settings_redirect(root)
            if len(new_pw) < 8:
                root.flash("New password must be at least 8 characters.", "error")
                return settings_redirect(root)
            if new_pw != confirm_pw:
                root.flash("New password and confirmation do not match.", "error")
                return settings_redirect(root)
            u.set_password(new_pw)
            root.log_audit("password_reset", "user", u.id, details=json.dumps({"username": u.username}))
            root.db.session.commit()
            root.flash(f"Password updated for '{u.display_name}'.", "success")

        elif form_type == "slack":
            root.slack_integration_module.handle_settings_form(root)

        return settings_redirect(root)

    root.slack_integration_module.ensure_sync_configs(root)
    slack_sync_slots = root.SlackChannelSyncConfig.query.order_by(root.SlackChannelSyncConfig.slot_index).all()
    system_settings = {s.key: s.value for s in root.SystemSetting.query.all()}
    kpis = root.KpiTarget.query.all()
    users = root.User.query.order_by(root.User.created_at.asc()).all()
    field_tokens = root.FieldAccessToken.query.order_by(root.FieldAccessToken.created_at.desc()).all()
    pending_field_submissions = root.FieldPurchaseSubmission.query.filter_by(status="pending").order_by(
        root.FieldPurchaseSubmission.submitted_at.desc()
    ).all()
    reviewed_field_submissions = root.FieldPurchaseSubmission.query.filter(
        root.FieldPurchaseSubmission.status.in_(("approved", "rejected"))
    ).order_by(root.FieldPurchaseSubmission.submitted_at.desc()).all()
    decorate_submission_rows(pending_field_submissions + reviewed_field_submissions)

    last_field_link = root.session.pop("last_field_link", None)
    last_field_sms = root.session.pop("last_field_sms", None)
    last_field_email_subject = root.session.pop("last_field_email_subject", None)
    last_field_email_body = root.session.pop("last_field_email_body", None)

    slack_sync_days_pref = root.session.get("slack_sync_days", 90)
    try:
        slack_sync_days_pref = int(slack_sync_days_pref)
    except (TypeError, ValueError):
        slack_sync_days_pref = 90
    slack_sync_days_pref = max(1, min(365, slack_sync_days_pref))

    pending_submissions_total_lbs = sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in pending_field_submissions)
    reviewed_approved_total_lbs = sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in reviewed_field_submissions if s.status == "approved")
    reviewed_rejected_total_lbs = sum(float(getattr(s, "total_weight_lbs", 0) or 0) for s in reviewed_field_submissions if s.status == "rejected")

    tz_choice_vals = [c[0] for c in root.APP_DISPLAY_TIMEZONE_CHOICES]
    return root.render_template(
        "settings.html",
        system_settings=system_settings,
        app_timezone_choices=root.APP_DISPLAY_TIMEZONE_CHOICES,
        app_timezone_choice_values=tz_choice_vals,
        slack_sync_slots=slack_sync_slots,
        slack_sync_days_pref=slack_sync_days_pref,
        kpis=kpis,
        users=users,
        field_tokens=field_tokens,
        field_submissions=pending_field_submissions,
        reviewed_field_submissions=reviewed_field_submissions,
        submission_return_to="#settings-field-intake",
        show_submission_approval_buttons=True,
        pending_submissions_total_lbs=pending_submissions_total_lbs,
        reviewed_approved_total_lbs=reviewed_approved_total_lbs,
        reviewed_rejected_total_lbs=reviewed_rejected_total_lbs,
        server_now=datetime.now(timezone.utc),
        last_field_link=last_field_link,
        last_field_sms=last_field_sms,
        last_field_email_subject=last_field_email_subject,
        last_field_email_body=last_field_email_body,
    )


def field_approvals_view(root):
    if not root.current_user.can_approve_field_purchases:
        root.flash("You don't have access to field purchase approvals.", "error")
        return root.redirect(root.url_for("dashboard"))
    pending_field_submissions = root.FieldPurchaseSubmission.query.filter_by(status="pending").order_by(
        root.FieldPurchaseSubmission.submitted_at.desc()
    ).all()
    reviewed_field_submissions = root.FieldPurchaseSubmission.query.filter(
        root.FieldPurchaseSubmission.status.in_(("approved", "rejected"))
    ).order_by(root.FieldPurchaseSubmission.submitted_at.desc()).all()
    decorate_submission_rows(pending_field_submissions + reviewed_field_submissions)
    pending_submissions_total_lbs = sum(
        float(getattr(submission, "total_weight_lbs", 0) or 0) for submission in pending_field_submissions
    )
    reviewed_approved_total_lbs = sum(
        float(getattr(submission, "total_weight_lbs", 0) or 0)
        for submission in reviewed_field_submissions
        if submission.status == "approved"
    )
    reviewed_rejected_total_lbs = sum(
        float(getattr(submission, "total_weight_lbs", 0) or 0)
        for submission in reviewed_field_submissions
        if submission.status == "rejected"
    )
    return root.render_template(
        "field_approvals.html",
        field_submissions=pending_field_submissions,
        reviewed_field_submissions=reviewed_field_submissions,
        submission_return_to="",
        show_submission_approval_buttons=True,
        pending_submissions_total_lbs=pending_submissions_total_lbs,
        reviewed_approved_total_lbs=reviewed_approved_total_lbs,
        reviewed_rejected_total_lbs=reviewed_rejected_total_lbs,
    )


def field_submission_approve_view(root, submission_id):
    submission = root.db.session.get(root.FieldPurchaseSubmission, submission_id)
    if not submission:
        root.flash("Submission not found.", "error")
        return field_submission_error_redirect(root)
    if submission.status != "pending":
        root.flash("Submission has already been reviewed.", "error")
        return field_submission_error_redirect(root)

    lots = load_lots(submission.lots_json)
    total_weight = submission_total_weight(lots)
    if total_weight < 0:
        root.flash("Submission lot weights are invalid.", "error")
        return field_submission_error_redirect(root)

    purchase = root.Purchase(
        supplier_id=submission.supplier_id,
        purchase_date=submission.purchase_date,
        delivery_date=submission.delivery_date,
        harvest_date=submission.harvest_date,
        status="committed",
        stated_weight_lbs=(total_weight if total_weight > 0 else 0.0),
        stated_potency_pct=submission.estimated_potency_pct,
        price_per_lb=submission.price_per_lb,
        storage_note=submission.storage_note,
        license_info=submission.license_info,
        queue_placement=submission.queue_placement,
        coa_status_text=submission.coa_status_text,
        notes=(submission.notes or "") + (
            f"\n\nApproved from field submission {submission.id}"
            if submission.notes else f"Approved from field submission {submission.id}"
        ),
        purchase_approved_at=datetime.now(timezone.utc),
        purchase_approved_by_user_id=root.current_user.id,
    )
    root.db.session.add(purchase)
    root.db.session.flush()

    for lot_row in lots:
        strain_name = (lot_row.get("strain") or "").strip()
        weight_value = lot_row.get("weight_lbs")
        weight_lbs = float(weight_value) if weight_value is not None else 0.0
        if weight_lbs <= 0:
            continue
        root.db.session.add(root.PurchaseLot(
            purchase_id=purchase.id,
            strain_name=(strain_name or "Unspecified"),
            weight_lbs=weight_lbs,
            remaining_weight_lbs=weight_lbs,
        ))

    supplier = root.db.session.get(root.Supplier, purchase.supplier_id)
    supplier_name = supplier.name if supplier else "BATCH"
    batch_date = purchase.delivery_date or purchase.purchase_date
    purchase.batch_id = root._ensure_unique_batch_id(
        root._generate_batch_id(supplier_name, batch_date, (total_weight if total_weight > 0 else 0.0)),
        exclude_purchase_id=purchase.id,
    )

    if purchase.price_per_lb:
        purchase.total_cost = purchase.stated_weight_lbs * purchase.price_per_lb

    promote_submission_photos(submission, purchase.id, root.current_user.id)

    submission.status = "approved"
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewed_by = root.current_user.id
    submission.review_notes = (root.request.form.get("review_notes") or "").strip() or None
    submission.approved_purchase_id = purchase.id

    try:
        enforce_weekly_biomass_purchase_limits(
            purchase,
            biomass_budget_snapshot_for_purchase(purchase),
            enforce_cap=True,
        )
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return field_submission_error_redirect(root)

    root.log_audit(
        "approve",
        "field_purchase_submission",
        submission.id,
        details=json.dumps({"purchase_id": purchase.id}),
    )
    root.log_audit(
        "create",
        "purchase",
        purchase.id,
        details=json.dumps({"source": "field_submission", "submission_id": submission.id}),
    )
    root.db.session.commit()
    root.notify_slack(
        f"Field submission approved for {submission.supplier.name if submission.supplier else 'supplier'}; "
        f"purchase {purchase.batch_id or purchase.id} created."
    )
    root.flash("Submission approved and converted to a Purchase.", "success")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))


def field_submission_reject_view(root, submission_id):
    submission = root.db.session.get(root.FieldPurchaseSubmission, submission_id)
    if not submission:
        root.flash("Submission not found.", "error")
        return field_submission_error_redirect(root)
    if submission.status != "pending":
        root.flash("Submission has already been reviewed.", "error")
        return field_submission_error_redirect(root)
    submission.status = "rejected"
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewed_by = root.current_user.id
    submission.review_notes = (root.request.form.get("review_notes") or "").strip() or None
    root.log_audit(
        "reject",
        "field_purchase_submission",
        submission.id,
        details=json.dumps({"notes": submission.review_notes}),
    )
    root.db.session.commit()
    root.notify_slack(
        f"Field submission rejected for {submission.supplier.name if submission.supplier else 'supplier'}."
    )
    root.flash("Submission rejected.", "success")
    return field_approval_return_redirect(root)


def settings_backfill_photo_assets_view(root):
    try:
        submissions = root.FieldPurchaseSubmission.query.filter(
            root.FieldPurchaseSubmission.status == "approved",
            root.FieldPurchaseSubmission.approved_purchase_id.isnot(None),
        ).all()

        supplier_attachments_added = 0
        assets_added = 0
        touched_submissions = 0

        for submission in submissions:
            supplier_id = submission.supplier_id
            purchase_id = submission.approved_purchase_id
            if not supplier_id or not purchase_id:
                continue

            counts = promote_submission_photos(submission, purchase_id, root.current_user.id)
            if counts["supplier_attachments_added"] or counts["assets_added"]:
                touched_submissions += 1
            supplier_attachments_added += counts["supplier_attachments_added"]
            assets_added += counts["assets_added"]

        root.db.session.commit()
        root.flash(
            f"Photo backfill complete. Updated {touched_submissions} submissions, added "
            f"{supplier_attachments_added} supplier attachment(s) and {assets_added} photo asset(s).",
            "success",
        )
    except Exception as exc:
        root.db.session.rollback()
        root.app.logger.exception("Photo backfill failed")
        root.flash(f"Photo backfill failed: {exc}", "error")
    return settings_redirect(root)
