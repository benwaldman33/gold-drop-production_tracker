from __future__ import annotations

import os

from flask import current_app, request, url_for

from gold_drop.uploads import json_paths, save_lab_files, save_photo_library_files
from services.photo_assets import create_photo_asset, normalize_photo_category
from services.supplier_duplicates import supplier_duplicate_candidates
from services.supplier_merge import execute_supplier_merge, supplier_merge_preview
from services.access_control import has_permission
from supplier_import import (
    SUPPLIER_IMPORT_FIELDS,
    parse_supplier_spreadsheet_upload_for_mapping,
    supplier_import_field_choices,
    supplier_import_rows_from_mapping,
)


def remove_upload_if_unreferenced(root, file_path: str) -> None:
    if not file_path:
        return
    if root.PhotoAsset.query.filter_by(file_path=file_path).first():
        return
    if not (
        file_path.startswith("uploads/library/")
        or file_path.startswith("uploads/purchases/")
    ):
        return
    abs_path = os.path.join(current_app.static_folder, file_path.replace("/", os.sep))
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except OSError:
        pass


def safe_internal_redirect(form_key: str = "next", default_endpoint: str = "photos_library", **default_kwargs) -> str:
    url = (request.form.get(form_key) or "").strip()
    if url.startswith("/") and not url.startswith("//"):
        return url
    return url_for(default_endpoint, **default_kwargs)


def photos_library_filters_from_hidden_form() -> dict:
    out = {}
    q = (request.form.get("ret_q") or "").strip()
    if q:
        out["q"] = q
    sid = (request.form.get("ret_supplier_id") or "").strip()
    if sid:
        out["supplier_id"] = sid
    pid = (request.form.get("ret_purchase_id") or "").strip()
    if pid:
        out["purchase_id"] = pid
    category = (request.form.get("ret_category") or "").strip()
    if category:
        out["category"] = category
    return out


def register_routes(app, root):
    @root.login_required
    def suppliers_list():
        return suppliers_list_view(root)

    @root.editor_required
    def supplier_new():
        return supplier_new_view(root)

    @root.editor_required
    def supplier_edit(sid):
        return supplier_edit_view(root, sid)

    @root.editor_required
    def supplier_import():
        return supplier_import_view(root)

    @root.editor_required
    def supplier_import_preview():
        return supplier_import_preview_view(root)

    @root.editor_required
    def supplier_import_commit():
        return supplier_import_commit_view(root)

    @root.editor_required
    def supplier_import_sample():
        return supplier_import_sample_view(root)

    @root.editor_required
    def supplier_lab_test_delete(sid, test_id):
        return supplier_lab_test_delete_view(root, sid, test_id)

    @root.editor_required
    def supplier_attachment_delete(sid, attachment_id):
        return supplier_attachment_delete_view(root, sid, attachment_id)

    @root.login_required
    def photos_library():
        return photos_library_view(root)

    @root.editor_required
    def photos_upload():
        return photos_upload_view(root)

    @root.editor_required
    def photo_asset_delete(asset_id):
        return photo_asset_delete_view(root, asset_id)

    @root.purchase_editor_required
    def purchase_support_doc_delete(purchase_id, asset_id):
        return purchase_support_doc_delete_view(root, purchase_id, asset_id)

    app.add_url_rule("/suppliers", endpoint="suppliers_list", view_func=suppliers_list)
    app.add_url_rule("/suppliers/new", endpoint="supplier_new", view_func=supplier_new, methods=["GET", "POST"])
    app.add_url_rule("/suppliers/<sid>/edit", endpoint="supplier_edit", view_func=supplier_edit, methods=["GET", "POST"])
    app.add_url_rule("/suppliers/import", endpoint="supplier_import", view_func=supplier_import, methods=["GET", "POST"])
    app.add_url_rule("/suppliers/import/preview", endpoint="supplier_import_preview", view_func=supplier_import_preview, methods=["GET", "POST"])
    app.add_url_rule("/suppliers/import/commit", endpoint="supplier_import_commit", view_func=supplier_import_commit, methods=["POST"])
    app.add_url_rule("/suppliers/import/sample.csv", endpoint="supplier_import_sample", view_func=supplier_import_sample)
    app.add_url_rule("/suppliers/<sid>/lab_tests/<test_id>/delete", endpoint="supplier_lab_test_delete", view_func=supplier_lab_test_delete, methods=["POST"])
    app.add_url_rule("/suppliers/<sid>/attachments/<attachment_id>/delete", endpoint="supplier_attachment_delete", view_func=supplier_attachment_delete, methods=["POST"])
    app.add_url_rule("/photos", endpoint="photos_library", view_func=photos_library)
    app.add_url_rule("/photos/upload", endpoint="photos_upload", view_func=photos_upload, methods=["POST"])
    app.add_url_rule("/photos/<asset_id>/delete", endpoint="photo_asset_delete", view_func=photo_asset_delete, methods=["POST"])
    app.add_url_rule("/purchases/<purchase_id>/supporting_docs/<asset_id>/delete", endpoint="purchase_support_doc_delete", view_func=purchase_support_doc_delete, methods=["POST"])


def supplier_import_staging_path(root, token: str) -> str:
    safe = "".join(c for c in (token or "") if c.isalnum() or c in "-_")
    if len(safe) < 8:
        raise ValueError("Invalid staging token.")
    return root.os.path.join(root.tempfile.gettempdir(), f"gdp_suppimp_{safe}.json")


def supplier_import_load_staging(root, token: str) -> dict | None:
    try:
        path = supplier_import_staging_path(root, token)
    except ValueError:
        return None
    if not root.os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return root.json.load(f)
    except (OSError, root.json.JSONDecodeError):
        return None


def supplier_import_clear_staging(root, token: str) -> None:
    try:
        path = supplier_import_staging_path(root, token)
        if root.os.path.isfile(path):
            root.os.remove(path)
    except (OSError, ValueError):
        pass


def supplier_import_parse_optional_bool(value: str) -> bool | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "active"}:
        return True
    if text in {"0", "false", "no", "n", "inactive"}:
        return False
    return None


def supplier_import_validate_row(root, raw: dict):
    errors: list[str] = []
    supplier_name = (raw.get("name") or "").strip()
    if not supplier_name:
        errors.append("Supplier name is required.")

    email = (raw.get("contact_email") or "").strip()
    if email and "@" not in email:
        errors.append("Contact email must look like an email address.")

    is_active = None
    is_active_raw = (raw.get("is_active") or "").strip()
    if is_active_raw:
        is_active = supplier_import_parse_optional_bool(is_active_raw)
        if is_active is None:
            errors.append("Active must be yes/no, true/false, or 1/0.")

    duplicate_candidates = supplier_duplicate_candidates(root, supplier_name)
    exact_match = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == supplier_name.lower()).first()
    if errors:
        return errors, None

    return [], {
        "name": supplier_name,
        "contact_name": (raw.get("contact_name") or "").strip() or None,
        "contact_phone": (raw.get("contact_phone") or "").strip() or None,
        "contact_email": email or None,
        "location": (raw.get("location") or "").strip() or None,
        "notes": (raw.get("notes") or "").strip() or None,
        "is_active": True if is_active is None else bool(is_active),
        "exact_match_supplier_id": exact_match.id if exact_match else None,
        "duplicate_candidates": duplicate_candidates,
    }


def supplier_import_build_staged_rows(root, staged: dict) -> list[dict]:
    rows = supplier_import_rows_from_mapping(
        staged.get("data_rows") or [],
        staged.get("mapping") or {},
        int(staged.get("header_row_index") or 0),
    )
    staged_rows = []
    for raw_row in rows:
        row_copy = dict(raw_row)
        sheet_row = row_copy.pop("_sheet_row", "")
        errs, norm = supplier_import_validate_row(root, row_copy)
        action = "create"
        if norm and norm.get("exact_match_supplier_id"):
            action = "update"
        staged_rows.append(
            {
                "sheet_row": sheet_row,
                "raw": row_copy,
                "errors": errs,
                "normalized": norm,
                "action": action,
            }
        )
    return staged_rows


def supplier_import_commit_norm(root, norm: dict, *, update_existing: bool) -> None:
    supplier = None
    if norm.get("exact_match_supplier_id"):
        supplier = root.db.session.get(root.Supplier, norm["exact_match_supplier_id"])
    if supplier and not update_existing:
        raise ValueError(f"Supplier {supplier.name} already exists. Turn on update existing suppliers to overwrite matching names.")
    is_new = supplier is None
    if supplier is None:
        supplier = root.Supplier(name=norm["name"])
        root.db.session.add(supplier)
        root.db.session.flush()

    supplier.name = norm["name"]
    supplier.contact_name = norm.get("contact_name")
    supplier.contact_phone = norm.get("contact_phone")
    supplier.contact_email = norm.get("contact_email")
    supplier.location = norm.get("location")
    supplier.notes = norm.get("notes")
    supplier.is_active = bool(norm.get("is_active", True))

    root.log_audit("create" if is_new else "update", "supplier", supplier.id)
    root.db.session.commit()


def supplier_import_view(root):
    denied = _require_supplier_import_access(root)
    if denied is not None:
        return denied
    if root.request.method == "GET":
        return root.render_template("supplier_import.html")
    f = root.request.files.get("spreadsheet")
    if not f or not getattr(f, "filename", None):
        root.flash("Choose a .csv, .xlsx, or .xlsm file to upload.", "error")
        return root.redirect(root.url_for("supplier_import"))
    raw = f.read()
    if not raw:
        root.flash("The file is empty.", "error")
        return root.redirect(root.url_for("supplier_import"))
    try:
        staged = parse_supplier_spreadsheet_upload_for_mapping(f.filename, raw)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("supplier_import"))

    token = root.secrets.token_urlsafe(32)
    payload = {
        "filename": root.secure_filename(f.filename) or "upload",
        "parse_warnings": staged["warnings"],
        "headers": staged["headers"],
        "mapping": staged["mapping"],
        "header_row_index": staged["header_row_index"],
        "data_rows": staged["data_rows"],
    }
    try:
        with open(supplier_import_staging_path(root, token), "w", encoding="utf-8") as out:
            root.json.dump(payload, out)
    except OSError:
        root.flash("Could not stage import file; try again.", "error")
        return root.redirect(root.url_for("supplier_import"))

    root.session["supplier_import_token"] = token
    for warning in staged["warnings"]:
        root.flash(warning, "warning")
    return root.redirect(root.url_for("supplier_import_preview"))


def supplier_import_preview_view(root):
    denied = _require_supplier_import_access(root)
    if denied is not None:
        return denied
    token = (root.session.get("supplier_import_token") or "").strip()
    data = supplier_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("supplier_import"))
    if root.request.method == "POST":
        new_mapping: dict[str, str] = {}
        for header in data.get("headers") or []:
            idx = str(header.get("index"))
            field_name = (root.request.form.get(f"map_{idx}") or "").strip()
            if field_name:
                new_mapping[idx] = field_name
        data["mapping"] = new_mapping
        try:
            with open(supplier_import_staging_path(root, token), "w", encoding="utf-8") as out:
                root.json.dump(data, out)
        except OSError:
            root.flash("Could not update import mapping; try again.", "error")
            return root.redirect(root.url_for("supplier_import_preview"))

    staged_rows = supplier_import_build_staged_rows(root, data)
    ok_count = sum(1 for row in staged_rows if not row.get("errors"))
    mapped_headers = [
        {
            "index": header.get("index"),
            "header": header.get("header"),
            "normalized": header.get("normalized"),
            "field": (data.get("mapping") or {}).get(str(header.get("index")), ""),
            "field_label": SUPPLIER_IMPORT_FIELDS.get((data.get("mapping") or {}).get(str(header.get("index")), ""), {}).get("label", ""),
        }
        for header in data.get("headers") or []
    ]
    mapped_preview_columns = [h for h in mapped_headers if h.get("field")]
    return root.render_template(
        "supplier_import_preview.html",
        staged=data,
        staged_rows=staged_rows,
        ok_count=ok_count,
        field_choices=supplier_import_field_choices(),
        mapped_headers=mapped_headers,
        mapped_preview_columns=mapped_preview_columns,
    )


def supplier_import_commit_view(root):
    denied = _require_supplier_import_access(root)
    if denied is not None:
        return denied
    token = (root.session.get("supplier_import_token") or "").strip()
    data = supplier_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("supplier_import"))
    staged_rows = supplier_import_build_staged_rows(root, data)
    selected = {int(x) for x in root.request.form.getlist("row_idx") if str(x).isdigit()}
    if not selected:
        root.flash("No rows selected to import.", "warning")
        return root.redirect(root.url_for("supplier_import_preview"))

    update_existing = root.request.form.get("update_existing") == "1"
    imported = 0
    failed = 0
    fail_msgs = []
    for i, row in enumerate(staged_rows):
        if i not in selected:
            continue
        if row.get("errors"):
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: skipped (validation errors).")
            continue
        norm = row.get("normalized")
        if not norm:
            failed += 1
            continue
        try:
            supplier_import_commit_norm(root, norm, update_existing=update_existing)
            imported += 1
        except ValueError as exc:
            root.db.session.rollback()
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: {exc}")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("supplier import row failed")
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: unexpected error.")

    supplier_import_clear_staging(root, token)
    root.session.pop("supplier_import_token", None)
    if imported:
        root.flash(f"Imported {imported} supplier row(s).", "success")
    if failed:
        root.flash(f"{failed} row(s) not imported.", "warning")
    for msg in fail_msgs[:15]:
        root.flash(msg, "error")
    if len(fail_msgs) > 15:
        root.flash(f"...and {len(fail_msgs) - 15} more errors (see logs).", "error")
    return root.redirect(root.url_for("suppliers_list"))


def supplier_import_sample_view(root):
    denied = _require_supplier_import_access(root)
    if denied is not None:
        return denied
    lines = [
        "Supplier,Contact Name,Contact Phone,Contact Email,Location,Notes,Active",
        "Example Farm,Jamie Buyer,555-0101,jamie@example.com,Salinas,Main flower supplier,yes",
    ]
    body = "\n".join(lines) + "\n"
    return root.Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=supplier_import_sample.csv"},
    )


def _require_supplier_import_access(root):
    if has_permission(root, root.current_user, "purchasing.import"):
        return None
    root.flash("Purchasing import access required.", "error")
    return root.redirect(root.url_for("suppliers_list"))


def supplier_incomplete_profile_fields(root, supplier):
    if not supplier:
        return []
    missing: list[str] = []
    if not (supplier.contact_name or "").strip():
        missing.append("contact_name")
    if not (supplier.contact_phone or "").strip():
        missing.append("contact_phone")
    if not (supplier.contact_email or "").strip():
        missing.append("contact_email")
    if not (supplier.location or "").strip():
        missing.append("location")
    return missing


def suppliers_list_view(root):
    visibility = (request.args.get("visibility") or "active").strip().lower()
    suppliers_query = root.Supplier.query
    if visibility == "active":
        suppliers_query = suppliers_query.filter(
            root.Supplier.is_active.is_(True),
            root.Supplier.merged_into_supplier_id.is_(None),
        )
    elif visibility == "inactive":
        suppliers_query = suppliers_query.filter(
            root.or_(
                root.Supplier.is_active.is_(False),
                root.Supplier.merged_into_supplier_id.is_not(None),
            )
        )
    suppliers = suppliers_query.order_by(root.Supplier.name).all()
    exclude_unpriced = root._exclude_unpriced_batches_enabled()
    supplier_stats = []
    for supplier in suppliers:
        runs_q = root.db.session.query(
            root.func.avg(root.Run.overall_yield_pct),
            root.func.avg(root.Run.thca_yield_pct),
            root.func.avg(root.Run.hte_yield_pct),
            root.func.avg(root.Run.cost_per_gram_combined),
            root.func.count(root.Run.id),
            root.func.sum(root.Run.bio_in_reactor_lbs),
            root.func.sum(root.Run.dry_thca_g),
            root.func.sum(root.Run.dry_hte_g),
        ).join(
            root.RunInput, root.Run.id == root.RunInput.run_id
        ).join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
        ).filter(
            root.Purchase.supplier_id == supplier.id,
            root.Run.is_rollover == False,
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
        )
        if exclude_unpriced:
            runs_q = runs_q.filter(root._priced_run_filter())
        all_time = runs_q.first()
        ninety = runs_q.filter(root.Run.run_date >= root.date.today() - root.timedelta(days=90)).first()
        last_run = root.db.session.query(root.Run).join(
            root.RunInput, root.Run.id == root.RunInput.run_id
        ).join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
        ).filter(
            root.Purchase.supplier_id == supplier.id,
            root.Run.is_rollover == False,
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
        )
        if exclude_unpriced:
            last_run = last_run.filter(root._priced_run_filter())
        last_run = last_run.order_by(root.Run.run_date.desc()).first()
        supplier_stats.append({
            "supplier": supplier,
            "profile_incomplete": bool(supplier_incomplete_profile_fields(root, supplier)),
            "all_time": {
                "yield": all_time[0], "thca": all_time[1], "hte": all_time[2],
                "cpg": all_time[3], "runs": all_time[4], "lbs": all_time[5] or 0,
                "total_thca": all_time[6] or 0, "total_hte": all_time[7] or 0,
            },
            "ninety_day": {
                "yield": ninety[0], "thca": ninety[1], "hte": ninety[2],
                "cpg": ninety[3], "runs": ninety[4],
            },
            "last_batch": {
                "yield": last_run.overall_yield_pct if last_run else None,
                "thca": last_run.thca_yield_pct if last_run else None,
                "hte": last_run.hte_yield_pct if last_run else None,
                "cpg": last_run.cost_per_gram_combined if last_run else None,
                "date": last_run.run_date if last_run else None,
            },
        })

    yield_kpi = root.KpiTarget.query.filter_by(kpi_name="overall_yield_pct").first()
    thca_kpi = root.KpiTarget.query.filter_by(kpi_name="thca_yield_pct").first()
    current_month_start = root.date.today().replace(day=1)
    prev_month_end = current_month_start - root.timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    month_rows = root.db.session.query(
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
        month_rows = month_rows.filter(root._priced_run_filter())
    month_rows = month_rows.group_by(root.Supplier.id, root.Supplier.name).all()
    best_supplier_mom = None
    if month_rows:
        best = max(month_rows, key=lambda row: float(row.avg_yield or 0))
        prev_q = root.db.session.query(root.func.avg(root.Run.overall_yield_pct)).join(
            root.RunInput, root.Run.id == root.RunInput.run_id
        ).join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
        ).filter(
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.supplier_id == best.supplier_id,
            root.Run.is_rollover == False,
            root.Run.run_date >= prev_month_start,
            root.Run.run_date <= prev_month_end,
            root.Run.overall_yield_pct.isnot(None),
        )
        if exclude_unpriced:
            prev_q = prev_q.filter(root._priced_run_filter())
        prev_avg = prev_q.scalar()
        best_supplier_mom = {
            "name": best.supplier_name,
            "current": float(best.avg_yield or 0),
            "previous": float(prev_avg) if prev_avg is not None else None,
        }
        if best_supplier_mom["previous"] and best_supplier_mom["previous"] > 0:
            best_supplier_mom["pct_change"] = ((best_supplier_mom["current"] - best_supplier_mom["previous"]) / best_supplier_mom["previous"]) * 100.0
        else:
            best_supplier_mom["pct_change"] = None

    return root.render_template(
        "suppliers.html",
        supplier_stats=supplier_stats,
        yield_kpi=yield_kpi,
        thca_kpi=thca_kpi,
        best_supplier_mom=best_supplier_mom,
        visibility=visibility,
    )


def supplier_new_view(root):
    form_data = {}
    if root.request.method == "POST":
        form_data = {
            "name": root.request.form.get("name", "").strip(),
            "contact_name": root.request.form.get("contact_name", "").strip(),
            "contact_phone": root.request.form.get("contact_phone", "").strip(),
            "contact_email": root.request.form.get("contact_email", "").strip(),
            "location": root.request.form.get("location", "").strip(),
            "notes": root.request.form.get("notes", "").strip(),
            "confirm_new_supplier": root.request.form.get("confirm_new_supplier") == "1",
        }
        duplicate_candidates = supplier_duplicate_candidates(root, form_data["name"])
        if duplicate_candidates and root.request.form.get("confirm_new_supplier") != "1":
            return root.render_template(
                "supplier_form.html",
                supplier=None,
                supplier_incomplete_fields=[],
                form_data=form_data,
                duplicate_candidates=duplicate_candidates,
            )
        supplier = root.Supplier(
            name=form_data["name"],
            contact_name=form_data["contact_name"] or None,
            contact_phone=form_data["contact_phone"] or None,
            contact_email=form_data["contact_email"] or None,
            location=form_data["location"] or None,
            notes=form_data["notes"] or None,
        )
        root.db.session.add(supplier)
        root.log_audit("create", "supplier", supplier.id)
        root.db.session.commit()
        incomplete = supplier_incomplete_profile_fields(root, supplier)
        if incomplete:
            root.flash("Supplier saved, but contact / location information is incomplete. Complete the highlighted fields when you can.", "warning")
            return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
        root.flash("Supplier added.", "success")
        return root.redirect(root.url_for("suppliers_list"))
    return root.render_template("supplier_form.html", supplier=None, supplier_incomplete_fields=[], form_data=form_data, duplicate_candidates=[])


def supplier_edit_view(root, sid):
    supplier = root.db.session.get(root.Supplier, sid)
    if not supplier:
        root.flash("Supplier not found.", "error")
        return root.redirect(root.url_for("suppliers_list"))
    merge_candidates = root.Supplier.query.filter(
        root.Supplier.id != supplier.id,
        root.Supplier.is_active.is_(True),
        root.Supplier.merged_into_supplier_id.is_(None),
    ).order_by(root.Supplier.name.asc()).all()
    if root.request.method == "POST":
        form_type = (root.request.form.get("form_type") or "supplier").strip()
        if form_type == "supplier":
            supplier.name = root.request.form["name"].strip()
            supplier.contact_name = root.request.form.get("contact_name", "").strip() or None
            supplier.contact_phone = root.request.form.get("contact_phone", "").strip() or None
            supplier.contact_email = root.request.form.get("contact_email", "").strip() or None
            supplier.location = root.request.form.get("location", "").strip() or None
            supplier.notes = root.request.form.get("notes", "").strip() or None
            supplier.is_active = "is_active" in root.request.form
            root.log_audit("update", "supplier", supplier.id)
            root.db.session.commit()
            incomplete = supplier_incomplete_profile_fields(root, supplier)
            if incomplete:
                root.flash("Supplier updated, but some profile fields are still incomplete. See the red dialog and highlighted fields.", "warning")
            else:
                root.flash("Supplier updated.", "success")
        elif form_type == "merge":
            if not root.current_user.is_super_admin:
                root.flash("Admin access required.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            target_id = (root.request.form.get("merge_target_supplier_id") or "").strip()
            if not target_id:
                root.flash("Choose a target supplier to merge into.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            target = root.db.session.get(root.Supplier, target_id)
            if not target:
                root.flash("Target supplier not found.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            try:
                preview = supplier_merge_preview(root, supplier, target)
            except ValueError as exc:
                root.flash(str(exc), "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            merge_action = (root.request.form.get("merge_action") or "preview").strip()
            merge_notes = (root.request.form.get("merge_notes") or "").strip() or None
            if merge_action == "execute":
                if root.request.form.get("merge_confirm") != "1":
                    root.flash("Confirm the merge before running it.", "error")
                    return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
                try:
                    summary = execute_supplier_merge(
                        root,
                        supplier,
                        target,
                        merged_by_user_id=root.current_user.id,
                        merge_notes=merge_notes,
                    )
                except ValueError as exc:
                    root.flash(str(exc), "error")
                    return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
                root.flash(
                    f"Supplier merged into {target.name}. Reassigned {summary['counts']['purchases']} purchase(s) and archived the duplicate supplier.",
                    "success",
                )
                return root.redirect(root.url_for("supplier_edit", sid=target.id))
            return root.render_template(
                "supplier_form.html",
                supplier=supplier,
                purchases=root.Purchase.query.filter(root.Purchase.deleted_at.is_(None), root.Purchase.supplier_id == supplier.id).order_by(root.Purchase.purchase_date.desc()).all(),
                lab_tests=root.LabTest.query.filter_by(supplier_id=supplier.id).order_by(root.LabTest.test_date.desc()).all(),
                attachments=root.SupplierAttachment.query.filter_by(supplier_id=supplier.id).order_by(root.SupplierAttachment.uploaded_at.desc()).all(),
                supplier_incomplete_fields=supplier_incomplete_profile_fields(root, supplier),
                merge_candidates=merge_candidates,
                merge_preview=preview,
                merge_target_id=target.id,
                merge_notes=merge_notes,
            )
        elif form_type == "lab_test":
            td = (root.request.form.get("test_date") or "").strip()
            if not td:
                root.flash("Lab test date is required.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            try:
                test_date = root.datetime.strptime(td, "%Y-%m-%d").date()
            except ValueError:
                root.flash("Lab test date is invalid.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            files = root.request.files.getlist("lab_files")
            saved_paths = save_lab_files(files, prefix=f"lab-{supplier.id}")
            pot_raw = (root.request.form.get("potency_pct") or "").strip()
            try:
                potency_pct = float(pot_raw) if pot_raw else None
            except ValueError:
                root.flash("Lab test potency must be numeric.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            test = root.LabTest(
                supplier_id=supplier.id,
                purchase_id=((root.request.form.get("purchase_id") or "").strip() or None),
                test_date=test_date,
                test_type=((root.request.form.get("test_type") or "coa").strip() or "coa"),
                status_text=((root.request.form.get("status_text") or "").strip() or None),
                potency_pct=potency_pct,
                notes=((root.request.form.get("notes") or "").strip() or None),
                result_paths_json=(root.json.dumps(saved_paths) if saved_paths else None),
                created_by=root.current_user.id,
            )
            root.db.session.add(test)
            for path in saved_paths:
                create_photo_asset(path, source_type="lab_test", category="lab_result", tags=["lab", "test", "supplier"], title=f"Lab test {test_date.isoformat()}", supplier_id=supplier.id, purchase_id=test.purchase_id, uploaded_by=root.current_user.id)
            root.log_audit("create", "lab_test", test.id, details=root.json.dumps({"supplier_id": supplier.id, "files": len(saved_paths)}))
            root.db.session.commit()
            root.flash("Lab test entry added.", "success")
        elif form_type == "supplier_attachment":
            files = root.request.files.getlist("attachment_files")
            title = (root.request.form.get("title") or "").strip() or None
            doc_type = ((root.request.form.get("document_type") or "coa").strip() or "coa")
            saved_paths = save_lab_files(files, prefix=f"supplier-{supplier.id}")
            if not saved_paths:
                root.flash("Select at least one attachment file.", "error")
                return root.redirect(root.url_for("supplier_edit", sid=supplier.id))
            for path in saved_paths:
                root.db.session.add(root.SupplierAttachment(supplier_id=supplier.id, document_type=doc_type, title=title, file_path=path, uploaded_by=root.current_user.id))
                create_photo_asset(path, source_type="supplier_attachment", category="supplier_doc", tags=["supplier", doc_type], title=title or f"Supplier {doc_type}", supplier_id=supplier.id, uploaded_by=root.current_user.id)
            root.log_audit("create", "supplier_attachment", supplier.id, details=root.json.dumps({"count": len(saved_paths), "type": doc_type}))
            root.db.session.commit()
            root.flash("Supplier attachments uploaded.", "success")
        return root.redirect(root.url_for("supplier_edit", sid=supplier.id))

    purchases = root.Purchase.query.filter(root.Purchase.deleted_at.is_(None), root.Purchase.supplier_id == supplier.id).order_by(root.Purchase.purchase_date.desc()).all()
    lab_tests = root.LabTest.query.filter_by(supplier_id=supplier.id).order_by(root.LabTest.test_date.desc()).all()
    for test in lab_tests:
        try:
            paths = root.json.loads(test.result_paths_json or "[]")
            test.file_paths = [path for path in paths if isinstance(path, str) and path.strip()]
        except Exception:
            test.file_paths = []
    attachments = root.SupplierAttachment.query.filter_by(supplier_id=supplier.id).order_by(root.SupplierAttachment.uploaded_at.desc()).all()
    return root.render_template(
        "supplier_form.html",
        supplier=supplier,
        purchases=purchases,
        lab_tests=lab_tests,
        attachments=attachments,
        supplier_incomplete_fields=supplier_incomplete_profile_fields(root, supplier),
        merge_candidates=merge_candidates,
        merge_preview=None,
        merge_target_id="",
        merge_notes="",
    )


def supplier_lab_test_delete_view(root, sid, test_id):
    test = root.db.session.get(root.LabTest, test_id)
    if not test or test.supplier_id != sid:
        root.flash("Lab test record not found.", "error")
        return root.redirect(root.url_for("supplier_edit", sid=sid))
    for path in json_paths(test.result_paths_json):
        root.PhotoAsset.query.filter(root.PhotoAsset.file_path == path, root.PhotoAsset.supplier_id == sid, root.PhotoAsset.source_type == "lab_test").delete(synchronize_session=False)
    root.log_audit("delete", "lab_test", test.id, details=root.json.dumps({"supplier_id": sid}))
    root.db.session.delete(test)
    root.db.session.commit()
    root.flash("Lab test record deleted.", "success")
    return root.redirect(root.url_for("supplier_edit", sid=sid))


def supplier_attachment_delete_view(root, sid, attachment_id):
    attachment = root.db.session.get(root.SupplierAttachment, attachment_id)
    if not attachment or attachment.supplier_id != sid:
        root.flash("Attachment not found.", "error")
        return root.redirect(root.url_for("supplier_edit", sid=sid))
    root.PhotoAsset.query.filter(root.PhotoAsset.file_path == attachment.file_path, root.PhotoAsset.supplier_id == sid, root.PhotoAsset.source_type == "supplier_attachment").delete(synchronize_session=False)
    root.log_audit("delete", "supplier_attachment", attachment.id, details=root.json.dumps({"supplier_id": sid}))
    root.db.session.delete(attachment)
    root.db.session.commit()
    root.flash("Attachment deleted.", "success")
    return root.redirect(root.url_for("supplier_edit", sid=sid))


def photos_library_view(root):
    q = (root.request.args.get("q") or "").strip()
    supplier_id = (root.request.args.get("supplier_id") or "").strip()
    purchase_id = (root.request.args.get("purchase_id") or "").strip()
    category = (root.request.args.get("category") or "").strip()
    query = root.PhotoAsset.query
    if supplier_id:
        query = query.filter(root.PhotoAsset.supplier_id == supplier_id)
    if purchase_id:
        query = query.filter(root.PhotoAsset.purchase_id == purchase_id)
    if category:
        query = query.filter(root.PhotoAsset.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            root.func.lower(root.func.coalesce(root.PhotoAsset.tags, "")).like(like) |
            root.func.lower(root.func.coalesce(root.PhotoAsset.title, "")).like(like) |
            root.func.lower(root.func.coalesce(root.PhotoAsset.file_path, "")).like(like)
        )
    assets = query.order_by(root.PhotoAsset.uploaded_at.desc()).limit(400).all()
    suppliers = root.Supplier.query.order_by(root.Supplier.name.asc()).all()
    purchases = root.Purchase.query.filter(root.Purchase.deleted_at.is_(None)).order_by(root.Purchase.purchase_date.desc()).limit(300).all()
    categories = [row[0] for row in root.db.session.query(root.PhotoAsset.category).distinct().order_by(root.PhotoAsset.category.asc()).all() if row and row[0]]
    return root.render_template("photos.html", assets=assets, suppliers=suppliers, purchases=purchases, q=q, supplier_id=supplier_id, purchase_id=purchase_id, category=category, categories=categories)


def photos_upload_view(root):
    files = root.request.files.getlist("files")
    ret = photos_library_filters_from_hidden_form()
    if not files or not any(getattr(f, "filename", None) for f in files if f):
        root.flash("Choose one or more files to upload.", "error")
        return root.redirect(root.url_for("photos_library", **ret))
    try:
        saved = save_photo_library_files(files, prefix="library")
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("photos_library", **ret))
    category = normalize_photo_category(root.request.form.get("category", ""), fallback="other")
    title = (root.request.form.get("title") or "").strip() or None
    tags = [tag.strip().lower() for tag in (root.request.form.get("tags") or "").strip().split(",") if tag.strip()]
    supplier_id = (root.request.form.get("supplier_id") or "").strip() or None
    if supplier_id and not root.db.session.get(root.Supplier, supplier_id):
        supplier_id = None
    purchase_id = (root.request.form.get("purchase_id") or "").strip() or None
    if purchase_id:
        purchase = root.db.session.get(root.Purchase, purchase_id)
        if not purchase or purchase.deleted_at is not None:
            purchase_id = None
    for path in saved:
        create_photo_asset(path, source_type="manual", category=category, tags=tags, title=title, supplier_id=supplier_id, purchase_id=purchase_id, uploaded_by=root.current_user.id)
    try:
        root.db.session.commit()
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("Photo library upload DB error")
        root.flash("Could not save photo library records.", "error")
        return root.redirect(root.url_for("photos_library"))
    root.flash(f"Uploaded {len(saved)} file(s) to the library.", "success")
    return root.redirect(root.url_for("photos_library", **ret))


def photo_asset_delete_view(root, asset_id):
    asset = root.db.session.get(root.PhotoAsset, asset_id)
    if not asset:
        root.flash("Asset not found.", "error")
        return root.redirect(safe_internal_redirect())
    if asset.source_type not in ("manual", "purchase_upload"):
        root.flash("This file is tied to field intake, suppliers, or lab records and cannot be deleted here.", "error")
        return root.redirect(safe_internal_redirect())
    path = asset.file_path
    root.db.session.delete(asset)
    root.db.session.commit()
    remove_upload_if_unreferenced(root, path)
    root.flash("File removed.", "success")
    return root.redirect(safe_internal_redirect())


def purchase_support_doc_delete_view(root, purchase_id, asset_id):
    purchase = root.db.session.get(root.Purchase, purchase_id)
    if not purchase or purchase.deleted_at is not None:
        root.flash("Purchase not found.", "error")
        return root.redirect(root.url_for("purchases_list"))
    asset = root.db.session.get(root.PhotoAsset, asset_id)
    if not asset or asset.purchase_id != purchase_id or asset.source_type != "purchase_upload":
        root.flash("Supporting document not found.", "error")
        return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))
    path = asset.file_path
    root.db.session.delete(asset)
    root.db.session.commit()
    remove_upload_if_unreferenced(root, path)
    root.flash("Supporting document removed.", "success")
    return root.redirect(root.url_for("purchase_edit", purchase_id=purchase_id))
