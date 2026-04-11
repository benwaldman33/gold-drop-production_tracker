from __future__ import annotations


PURCHASE_IMPORT_ALLOWED_STATUSES = frozenset({
    "declared", "committed", "ordered", "in_transit", "delivered",
    "in_testing", "available", "processing", "complete", "cancelled",
})


def register_routes(app, root):
    @root.purchase_editor_required
    def purchase_import():
        return purchase_import_view(root)

    @root.purchase_editor_required
    def purchase_import_preview():
        return purchase_import_preview_view(root)

    @root.purchase_editor_required
    def purchase_import_commit():
        return purchase_import_commit_view(root)

    @root.purchase_editor_required
    def purchase_import_sample():
        return purchase_import_sample_view(root)

    app.add_url_rule("/purchases/import", endpoint="purchase_import", view_func=purchase_import, methods=["GET", "POST"])
    app.add_url_rule("/purchases/import/preview", endpoint="purchase_import_preview", view_func=purchase_import_preview, methods=["GET"])
    app.add_url_rule("/purchases/import/commit", endpoint="purchase_import_commit", view_func=purchase_import_commit, methods=["POST"])
    app.add_url_rule("/purchases/import/sample.csv", endpoint="purchase_import_sample", view_func=purchase_import_sample)


def purchase_import_staging_path(root, token: str) -> str:
    safe = "".join(c for c in (token or "") if c.isalnum() or c in "-_")
    if len(safe) < 8:
        raise ValueError("Invalid staging token.")
    return root.os.path.join(root.tempfile.gettempdir(), f"gdp_purchimp_{safe}.json")


def purchase_import_load_staging(root, token: str) -> dict | None:
    try:
        path = purchase_import_staging_path(root, token)
    except ValueError:
        return None
    if not root.os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return root.json.load(f)
    except (OSError, root.json.JSONDecodeError):
        return None


def purchase_import_clear_staging(root, token: str) -> None:
    try:
        path = purchase_import_staging_path(root, token)
        if root.os.path.isfile(path):
            root.os.remove(path)
    except (OSError, ValueError):
        pass


def purchase_import_parse_date(root, value: str):
    value = (value or "").strip()
    if not value:
        return None
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return root.datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    parsed = root._parse_date(value)
    if parsed and parsed.year == 1900:
        parsed = parsed.replace(year=root.date.today().year)
    return parsed


def purchase_import_parse_required_positive_float(value: str) -> float | None:
    if not (value or "").strip():
        return None
    text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def purchase_import_parse_optional_float(value: str) -> float | None:
    if not (value or "").strip():
        return None
    text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def purchase_import_normalize_status(raw: str):
    value = (raw or "").strip()
    if not value:
        return "ordered", None
    key = value.lower().replace(" ", "_").replace("-", "_")
    while "__" in key:
        key = key.replace("__", "_")
    aliases = {
        "intransit": "in_transit",
        "in_test": "in_testing",
        "testing": "in_testing",
        "proc": "processing",
        "done": "complete",
        "canceled": "cancelled",
    }
    key = aliases.get(key, key)
    if key in PURCHASE_IMPORT_ALLOWED_STATUSES:
        return key, None
    return None, f"Unknown status {raw!r} (expected e.g. ordered, delivered)."


def purchase_import_normalize_queue_placement(raw: str):
    value = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not value:
        return None, None
    if value in ("aggregate", "indoor", "outdoor"):
        return value, None
    return None, f"Invalid queue placement {raw!r}."


def purchase_import_normalize_clean_dirty(raw: str):
    value = (raw or "").strip().lower()
    if not value:
        return None, None
    if value in ("clean", "dirty"):
        return value, None
    return None, f"Invalid clean/dirty {raw!r}."


def purchase_import_normalize_indoor_outdoor(raw: str):
    if not (raw or "").strip():
        return None, None
    value = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"mixedlight": "mixed_light", "green_house": "greenhouse"}
    value = aliases.get(value, value)
    if value in ("indoor", "outdoor", "mixed_light", "greenhouse"):
        return value, None
    return None, f"Invalid indoor/outdoor {raw!r}."


def purchase_import_validate_row(root, raw: dict):
    errors: list[str] = []
    supplier_name = (raw.get("supplier") or "").strip()
    if not supplier_name:
        errors.append("Supplier is required.")

    purchase_date = None
    purchase_date_raw = (raw.get("purchase_date") or "").strip()
    if purchase_date_raw:
        purchase_date = purchase_import_parse_date(root, purchase_date_raw)
    if not purchase_date:
        paid_raw = (raw.get("paid_date") or "").strip()
        if paid_raw:
            purchase_date = purchase_import_parse_date(root, paid_raw)
    if not purchase_date:
        errors.append("Purchase date is missing or could not be parsed (Paid date is used as fallback when purchase date is blank).")

    actual_weight_lbs = None
    actual_weight_raw = (raw.get("actual_weight_lbs") or "").strip()
    if actual_weight_raw:
        actual_weight_lbs = purchase_import_parse_optional_float(actual_weight_raw)
        if actual_weight_lbs is None:
            errors.append("Actual weight (lbs) is not a valid number.")
        elif actual_weight_lbs < 0:
            errors.append("Actual weight (lbs) cannot be negative.")

    stated_weight_raw = (raw.get("stated_weight_lbs") or "").strip()
    stated_weight = purchase_import_parse_required_positive_float(stated_weight_raw) if stated_weight_raw else None
    if (stated_weight is None or stated_weight <= 0) and actual_weight_lbs is not None and actual_weight_lbs > 0:
        stated_weight = float(actual_weight_lbs)
    if stated_weight is None or stated_weight <= 0:
        errors.append("Invoice/stated weight must be greater than zero, or provide actual weight when invoice weight is blank.")

    status, status_err = purchase_import_normalize_status((raw.get("status") or "").strip())
    if status_err:
        errors.append(status_err)

    batch_in = (raw.get("batch_id") or "").strip().upper()
    if batch_in:
        conflict = root.Purchase.query.filter(root.Purchase.batch_id == batch_in, root.Purchase.deleted_at.is_(None)).first()
        if conflict:
            errors.append(f"Batch ID {batch_in} already exists in Purchases.")

    delivery_date = None
    delivery_raw = (raw.get("delivery_date") or "").strip()
    if delivery_raw:
        delivery_date = purchase_import_parse_date(root, delivery_raw)
        if not delivery_date:
            errors.append("Delivery date could not be parsed.")

    paid_dt = None
    paid_date_raw = (raw.get("paid_date") or "").strip()
    if paid_date_raw:
        paid_dt = purchase_import_parse_date(root, paid_date_raw)
        if not paid_dt:
            errors.append("Paid date could not be parsed.")

    total_cost_val = None
    total_cost_raw = (raw.get("total_cost") or "").strip()
    if total_cost_raw:
        total_cost_val = purchase_import_parse_optional_float(total_cost_raw)
        if total_cost_val is None:
            errors.append("Amount / total cost is not a valid number.")
        elif total_cost_val < 0:
            errors.append("Amount / total cost cannot be negative.")

    stated_potency_pct = None
    stated_potency_raw = (raw.get("stated_potency_pct") or "").strip()
    if stated_potency_raw:
        stated_potency_pct = purchase_import_parse_optional_float(stated_potency_raw)
        if stated_potency_pct is None:
            errors.append("Stated potency is not a valid number.")

    tested_potency_pct = None
    tested_potency_raw = (raw.get("tested_potency_pct") or "").strip()
    if tested_potency_raw:
        tested_potency_pct = purchase_import_parse_optional_float(tested_potency_raw)
        if tested_potency_pct is None:
            errors.append("Tested potency is not a valid number.")

    price_per_lb = None
    price_per_lb_raw = (raw.get("price_per_lb") or "").strip()
    if price_per_lb_raw:
        price_per_lb = purchase_import_parse_optional_float(price_per_lb_raw)
        if price_per_lb is None:
            errors.append("Price per lb is not a valid number.")

    harvest_date = None
    harvest_raw = (raw.get("harvest_date") or "").strip()
    if harvest_raw:
        harvest_date = purchase_import_parse_date(root, harvest_raw)
        if not harvest_date:
            errors.append("Harvest date could not be parsed.")

    qp, qp_err = purchase_import_normalize_queue_placement(raw.get("queue_placement") or "")
    if qp_err:
        errors.append(qp_err)
    cd, cd_err = purchase_import_normalize_clean_dirty(raw.get("clean_or_dirty") or "")
    if cd_err:
        errors.append(cd_err)
    io_val, io_err = purchase_import_normalize_indoor_outdoor(raw.get("indoor_outdoor") or "")
    if io_err:
        errors.append(io_err)

    if errors:
        return errors, None

    note_lines = []
    base_notes = (raw.get("notes") or "").strip()
    if base_notes:
        note_lines.append(base_notes)
    week_s = (raw.get("purchase_week") or "").strip()
    if week_s:
        note_lines.append(f"Import - Purchasing week: {week_s}")
    if paid_dt:
        note_lines.append(f"Paid date: {paid_dt.isoformat()}")
    pay_m = (raw.get("payment_method") or "").strip()
    if pay_m:
        note_lines.append(f"Payment: {pay_m}")
    composed_notes = "\n".join(note_lines) if note_lines else None

    norm = {
        "supplier_name": supplier_name,
        "purchase_date": purchase_date.isoformat(),
        "stated_weight_lbs": float(stated_weight),
        "status": status or "ordered",
        "batch_id": batch_in or None,
        "delivery_date": delivery_date.isoformat() if delivery_date else None,
        "actual_weight_lbs": float(actual_weight_lbs) if actual_weight_lbs is not None else None,
        "stated_potency_pct": float(stated_potency_pct) if stated_potency_pct is not None else None,
        "tested_potency_pct": float(tested_potency_pct) if tested_potency_pct is not None else None,
        "price_per_lb": float(price_per_lb) if price_per_lb is not None else None,
        "total_cost": float(total_cost_val) if total_cost_val is not None else None,
        "harvest_date": harvest_date.isoformat() if harvest_date else None,
        "storage_note": (raw.get("storage_note") or "").strip() or None,
        "license_info": (raw.get("license_info") or "").strip() or None,
        "coa_status_text": (raw.get("coa_status_text") or "").strip() or None,
        "notes": composed_notes,
        "queue_placement": qp,
        "clean_or_dirty": cd,
        "indoor_outdoor": io_val,
        "strain": (raw.get("strain") or "").strip() or None,
    }
    return [], norm


def purchase_import_commit_norm(root, norm: dict, *, create_suppliers: bool) -> None:
    name = norm["supplier_name"]
    supplier = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == name.lower()).first()
    if not supplier:
        if not create_suppliers:
            raise ValueError(f"Unknown supplier: {name}")
        supplier = root.Supplier(name=name, is_active=True)
        root.db.session.add(supplier)
        root.db.session.flush()

    import_status = norm.get("status") or "ordered"
    if import_status in root.INVENTORY_ON_HAND_PURCHASE_STATUSES:
        import_status = "ordered"
    purchase = root.Purchase(
        supplier_id=supplier.id,
        purchase_date=root.datetime.strptime(norm["purchase_date"], "%Y-%m-%d").date(),
        status=import_status,
        stated_weight_lbs=float(norm["stated_weight_lbs"]),
    )
    if norm.get("delivery_date"):
        purchase.delivery_date = root.datetime.strptime(norm["delivery_date"], "%Y-%m-%d").date()
    purchase.actual_weight_lbs = norm.get("actual_weight_lbs")
    purchase.stated_potency_pct = norm.get("stated_potency_pct")
    purchase.tested_potency_pct = norm.get("tested_potency_pct")
    purchase.price_per_lb = norm.get("price_per_lb")
    tc_import = norm.get("total_cost")
    purchase.total_cost = float(tc_import) if tc_import is not None else None
    purchase.storage_note = norm.get("storage_note")
    purchase.license_info = norm.get("license_info")
    purchase.queue_placement = norm.get("queue_placement")
    purchase.coa_status_text = norm.get("coa_status_text")
    purchase.clean_or_dirty = norm.get("clean_or_dirty")
    purchase.indoor_outdoor = norm.get("indoor_outdoor")
    purchase.notes = norm.get("notes")
    if norm.get("harvest_date"):
        purchase.harvest_date = root.datetime.strptime(norm["harvest_date"], "%Y-%m-%d").date()

    weight_cost = purchase.actual_weight_lbs if purchase.actual_weight_lbs is not None else purchase.stated_weight_lbs
    if purchase.price_per_lb is None and tc_import is not None and weight_cost and float(weight_cost) > 0:
        purchase.price_per_lb = float(tc_import) / float(weight_cost)
    if purchase.stated_potency_pct and purchase.price_per_lb is None and tc_import is None:
        purchase.price_per_lb = root.SystemSetting.get_float("potency_rate", 1.50) * purchase.stated_potency_pct
    if purchase.total_cost is None:
        weight = purchase.actual_weight_lbs if purchase.actual_weight_lbs is not None else purchase.stated_weight_lbs
        if weight and purchase.price_per_lb:
            purchase.total_cost = float(weight) * float(purchase.price_per_lb)
    if purchase.tested_potency_pct and purchase.stated_potency_pct and purchase.actual_weight_lbs:
        rate = root.SystemSetting.get_float("potency_rate", 1.50)
        purchase.true_up_amount = (purchase.tested_potency_pct - purchase.stated_potency_pct) * rate * purchase.actual_weight_lbs
        if not purchase.true_up_status:
            purchase.true_up_status = "pending"

    root.db.session.add(purchase)
    root.db.session.flush()

    batch_in = norm.get("batch_id") or ""
    if batch_in:
        candidate = batch_in.strip().upper()
        conflict = root.Purchase.query.filter(root.Purchase.batch_id == candidate, root.Purchase.id != purchase.id).first()
        if conflict:
            raise ValueError(f"Batch ID '{candidate}' already exists.")
        purchase.batch_id = candidate
    else:
        d = purchase.delivery_date or purchase.purchase_date
        w = purchase.actual_weight_lbs or purchase.stated_weight_lbs
        purchase.batch_id = root._ensure_unique_batch_id(root._generate_batch_id(supplier.name, d, w), exclude_purchase_id=purchase.id)

    strain = norm.get("strain")
    if strain:
        wlot = float(purchase.stated_weight_lbs)
        root.db.session.add(root.PurchaseLot(purchase_id=purchase.id, strain_name=strain, weight_lbs=wlot, remaining_weight_lbs=wlot))

    root._maintain_purchase_inventory_lots(purchase)
    root._enforce_weekly_biomass_purchase_limits(purchase, root._biomass_budget_snapshot_for_purchase(purchase), enforce_cap=True)
    root.log_audit("create", "purchase", purchase.id)
    root.db.session.commit()


def purchase_import_view(root):
    if root.request.method == "GET":
        return root.render_template("purchase_import.html")
    f = root.request.files.get("spreadsheet")
    if not f or not getattr(f, "filename", None):
        root.flash("Choose a .csv, .xlsx, or .xlsm file to upload.", "error")
        return root.redirect(root.url_for("purchase_import"))
    raw = f.read()
    if not raw:
        root.flash("The file is empty.", "error")
        return root.redirect(root.url_for("purchase_import"))
    try:
        rows, parse_warnings = root.parse_purchase_spreadsheet_upload(f.filename, raw)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("purchase_import"))
    staged_rows = []
    for raw_row in rows:
        row_copy = dict(raw_row)
        sheet_row = row_copy.pop("_sheet_row", "")
        errs, norm = purchase_import_validate_row(root, row_copy)
        staged_rows.append({"sheet_row": sheet_row, "raw": row_copy, "errors": errs, "normalized": norm})

    token = root.secrets.token_urlsafe(32)
    payload = {"filename": root.secure_filename(f.filename) or "upload", "parse_warnings": parse_warnings, "rows": staged_rows}
    try:
        with open(purchase_import_staging_path(root, token), "w", encoding="utf-8") as out:
            root.json.dump(payload, out)
    except OSError:
        root.flash("Could not stage import file; try again.", "error")
        return root.redirect(root.url_for("purchase_import"))

    root.session["purchase_import_token"] = token
    for warning in parse_warnings:
        root.flash(warning, "warning")
    return root.redirect(root.url_for("purchase_import_preview"))


def purchase_import_preview_view(root):
    token = (root.session.get("purchase_import_token") or "").strip()
    data = purchase_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("purchase_import"))
    ok_count = sum(1 for row in data["rows"] if not row.get("errors"))
    return root.render_template("purchase_import_preview.html", staged=data, ok_count=ok_count)


def purchase_import_commit_view(root):
    token = (root.session.get("purchase_import_token") or "").strip()
    data = purchase_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("purchase_import"))
    create_suppliers = root.request.form.get("create_suppliers") == "1"
    selected = {int(x) for x in root.request.form.getlist("row_idx") if str(x).isdigit()}
    if not selected:
        root.flash("No rows selected to import.", "warning")
        return root.redirect(root.url_for("purchase_import_preview"))
    imported = 0
    failed = 0
    fail_msgs = []
    for i, row in enumerate(data["rows"]):
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
            purchase_import_commit_norm(root, norm, create_suppliers=create_suppliers)
            imported += 1
        except ValueError as exc:
            root.db.session.rollback()
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: {exc}")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("purchase import row failed")
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: unexpected error.")

    purchase_import_clear_staging(root, token)
    root.session.pop("purchase_import_token", None)
    if imported:
        root.flash(f"Imported {imported} purchase(s).", "success")
    if failed:
        root.flash(f"{failed} row(s) not imported.", "warning")
    for msg in fail_msgs[:15]:
        root.flash(msg, "error")
    if len(fail_msgs) > 15:
        root.flash(f"...and {len(fail_msgs) - 15} more errors (see logs).", "error")
    return root.redirect(root.url_for("purchases_list"))


def purchase_import_sample_view(root):
    lines = [
        "Week,Purchase Date,Paid Date,Vendor,Amount,Payment Method,Invoice Weight,Actual Weight,Manifest",
        "2/9-2/15,1/21/2026,2/10/2026,Example Farm,$4911.30,ACH,297.90,297.70,10187853",
    ]
    body = "\n".join(lines) + "\n"
    return root.Response(body, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=purchase_import_sample.csv"})
