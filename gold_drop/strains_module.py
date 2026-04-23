from __future__ import annotations

from strain_import import (
    STRAIN_IMPORT_FIELDS,
    parse_strain_spreadsheet_upload_for_mapping,
    strain_import_field_choices,
    strain_import_rows_from_mapping,
)

def register_routes(app, root):
    @root.login_required
    def strains_list():
        return strains_list_view(root)

    @root.editor_required
    def strain_import():
        return strain_import_view(root)

    @root.editor_required
    def strain_import_preview():
        return strain_import_preview_view(root)

    @root.editor_required
    def strain_import_commit():
        return strain_import_commit_view(root)

    @root.editor_required
    def strain_import_sample():
        return strain_import_sample_view(root)

    app.add_url_rule("/strains", endpoint="strains_list", view_func=strains_list)
    app.add_url_rule("/strains/import", endpoint="strain_import", view_func=strain_import, methods=["GET", "POST"])
    app.add_url_rule("/strains/import/preview", endpoint="strain_import_preview", view_func=strain_import_preview, methods=["GET", "POST"])
    app.add_url_rule("/strains/import/commit", endpoint="strain_import_commit", view_func=strain_import_commit, methods=["POST"])
    app.add_url_rule("/strains/import/sample.csv", endpoint="strain_import_sample", view_func=strain_import_sample)


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


def strain_import_staging_path(root, token: str) -> str:
    safe = "".join(c for c in (token or "") if c.isalnum() or c in "-_")
    if len(safe) < 8:
        raise ValueError("Invalid staging token.")
    return root.os.path.join(root.tempfile.gettempdir(), f"gdp_strainimp_{safe}.json")


def strain_import_load_staging(root, token: str) -> dict | None:
    try:
        path = strain_import_staging_path(root, token)
    except ValueError:
        return None
    if not root.os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return root.json.load(f)
    except (OSError, root.json.JSONDecodeError):
        return None


def strain_import_clear_staging(root, token: str) -> None:
    try:
        path = strain_import_staging_path(root, token)
        if root.os.path.isfile(path):
            root.os.remove(path)
    except (OSError, ValueError):
        pass


def strain_import_validate_row(root, raw: dict):
    errors: list[str] = []
    supplier_name = (raw.get("supplier_name") or "").strip()
    current_strain_name = (raw.get("current_strain_name") or "").strip()
    new_strain_name = (raw.get("new_strain_name") or "").strip()

    if not supplier_name:
        errors.append("Supplier name is required.")
    if not current_strain_name:
        errors.append("Current strain name is required.")
    if not new_strain_name:
        errors.append("New strain name is required.")
    if current_strain_name and new_strain_name and current_strain_name == new_strain_name:
        errors.append("Current strain name and new strain name are the same.")

    supplier = None
    if supplier_name:
        supplier = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == supplier_name.lower()).first()
        if not supplier:
            errors.append(f"Supplier {supplier_name!r} was not found.")

    matched_lots = []
    if supplier and current_strain_name:
        matched_lots = (
            root.PurchaseLot.query.join(root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id)
            .filter(
                root.Purchase.deleted_at.is_(None),
                root.PurchaseLot.deleted_at.is_(None),
                root.Purchase.supplier_id == supplier.id,
                root.func.lower(root.PurchaseLot.strain_name) == current_strain_name.lower(),
            )
            .all()
        )
        if not matched_lots:
            errors.append(f"No purchase lots found for {supplier_name} / {current_strain_name}.")

    if errors:
        return errors, None

    return [], {
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "current_strain_name": current_strain_name,
        "new_strain_name": new_strain_name,
        "notes": (raw.get("notes") or "").strip() or None,
        "matched_lot_ids": [lot.id for lot in matched_lots],
        "matched_lot_count": len(matched_lots),
    }


def strain_import_build_staged_rows(root, staged: dict) -> list[dict]:
    rows = strain_import_rows_from_mapping(
        staged.get("data_rows") or [],
        staged.get("mapping") or {},
        int(staged.get("header_row_index") or 0),
    )
    staged_rows = []
    for raw_row in rows:
        row_copy = dict(raw_row)
        sheet_row = row_copy.pop("_sheet_row", "")
        errs, norm = strain_import_validate_row(root, row_copy)
        staged_rows.append({"sheet_row": sheet_row, "raw": row_copy, "errors": errs, "normalized": norm})
    return staged_rows


def strain_import_commit_norm(root, norm: dict) -> None:
    lot_ids = norm.get("matched_lot_ids") or []
    if not lot_ids:
        raise ValueError("No matching lots found to rename.")
    lots = root.PurchaseLot.query.filter(root.PurchaseLot.id.in_(lot_ids)).all()
    if not lots:
        raise ValueError("Matching lots are no longer available.")
    for lot in lots:
        lot.strain_name = norm["new_strain_name"]
    details = {
        "supplier_id": norm["supplier_id"],
        "supplier_name": norm["supplier_name"],
        "from": norm["current_strain_name"],
        "to": norm["new_strain_name"],
        "lot_count": len(lots),
        "notes": norm.get("notes"),
    }
    root.log_audit("update", "strain_import", root.gen_uuid(), details=root.json.dumps(details))
    root.db.session.commit()


def strain_import_view(root):
    if root.request.method == "GET":
        return root.render_template("strain_import.html")
    f = root.request.files.get("spreadsheet")
    if not f or not getattr(f, "filename", None):
        root.flash("Choose a .csv, .xlsx, or .xlsm file to upload.", "error")
        return root.redirect(root.url_for("strain_import"))
    raw = f.read()
    if not raw:
        root.flash("The file is empty.", "error")
        return root.redirect(root.url_for("strain_import"))
    try:
        staged = parse_strain_spreadsheet_upload_for_mapping(f.filename, raw)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("strain_import"))

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
        with open(strain_import_staging_path(root, token), "w", encoding="utf-8") as out:
            root.json.dump(payload, out)
    except OSError:
        root.flash("Could not stage import file; try again.", "error")
        return root.redirect(root.url_for("strain_import"))

    root.session["strain_import_token"] = token
    for warning in staged["warnings"]:
        root.flash(warning, "warning")
    return root.redirect(root.url_for("strain_import_preview"))


def strain_import_preview_view(root):
    token = (root.session.get("strain_import_token") or "").strip()
    data = strain_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("strain_import"))
    if root.request.method == "POST":
        new_mapping: dict[str, str] = {}
        for header in data.get("headers") or []:
            idx = str(header.get("index"))
            field_name = (root.request.form.get(f"map_{idx}") or "").strip()
            if field_name:
                new_mapping[idx] = field_name
        data["mapping"] = new_mapping
        try:
            with open(strain_import_staging_path(root, token), "w", encoding="utf-8") as out:
                root.json.dump(data, out)
        except OSError:
            root.flash("Could not update import mapping; try again.", "error")
            return root.redirect(root.url_for("strain_import_preview"))

    staged_rows = strain_import_build_staged_rows(root, data)
    ok_count = sum(1 for row in staged_rows if not row.get("errors"))
    mapped_headers = [
        {
            "index": header.get("index"),
            "header": header.get("header"),
            "normalized": header.get("normalized"),
            "field": (data.get("mapping") or {}).get(str(header.get("index")), ""),
            "field_label": STRAIN_IMPORT_FIELDS.get((data.get("mapping") or {}).get(str(header.get("index")), ""), {}).get("label", ""),
        }
        for header in data.get("headers") or []
    ]
    mapped_preview_columns = [h for h in mapped_headers if h.get("field")]
    return root.render_template(
        "strain_import_preview.html",
        staged=data,
        staged_rows=staged_rows,
        ok_count=ok_count,
        field_choices=strain_import_field_choices(),
        mapped_headers=mapped_headers,
        mapped_preview_columns=mapped_preview_columns,
    )


def strain_import_commit_view(root):
    token = (root.session.get("strain_import_token") or "").strip()
    data = strain_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("strain_import"))
    staged_rows = strain_import_build_staged_rows(root, data)
    selected = {int(x) for x in root.request.form.getlist("row_idx") if str(x).isdigit()}
    if not selected:
        root.flash("No rows selected to import.", "warning")
        return root.redirect(root.url_for("strain_import_preview"))

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
            strain_import_commit_norm(root, norm)
            imported += 1
        except ValueError as exc:
            root.db.session.rollback()
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: {exc}")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("strain import row failed")
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: unexpected error.")

    strain_import_clear_staging(root, token)
    root.session.pop("strain_import_token", None)
    if imported:
        root.flash(f"Imported {imported} strain rename row(s).", "success")
    if failed:
        root.flash(f"{failed} row(s) not imported.", "warning")
    for msg in fail_msgs[:15]:
        root.flash(msg, "error")
    if len(fail_msgs) > 15:
        root.flash(f"...and {len(fail_msgs) - 15} more errors (see logs).", "error")
    return root.redirect(root.url_for("strains_list"))


def strain_import_sample_view(root):
    lines = [
        "Supplier,Current Strain,New Strain,Notes",
        "Example Farm,Blue Dream,Blue Dream BX1,Standardize naming from vendor feed",
    ]
    body = "\n".join(lines) + "\n"
    return root.Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=strain_import_sample.csv"},
    )
