from __future__ import annotations

from inventory_import import (
    INVENTORY_IMPORT_FIELDS,
    inventory_import_field_choices,
    inventory_import_rows_from_mapping,
    parse_inventory_spreadsheet_upload_for_mapping,
)
from services.access_control import has_permission


def register_routes(app, root):
    @root.login_required
    def inventory():
        return inventory_view(root)

    @root.purchase_editor_required
    def inventory_import():
        return inventory_import_view(root)

    @root.purchase_editor_required
    def inventory_import_preview():
        return inventory_import_preview_view(root)

    @root.purchase_editor_required
    def inventory_import_commit():
        return inventory_import_commit_view(root)

    @root.purchase_editor_required
    def inventory_import_sample():
        return inventory_import_sample_view(root)

    app.add_url_rule("/inventory", endpoint="inventory", view_func=inventory)
    app.add_url_rule("/inventory/import", endpoint="inventory_import", view_func=inventory_import, methods=["GET", "POST"])
    app.add_url_rule("/inventory/import/preview", endpoint="inventory_import_preview", view_func=inventory_import_preview, methods=["GET", "POST"])
    app.add_url_rule("/inventory/import/commit", endpoint="inventory_import_commit", view_func=inventory_import_commit, methods=["POST"])
    app.add_url_rule("/inventory/import/sample.csv", endpoint="inventory_import_sample", view_func=inventory_import_sample)


def _lot_allocation_state(lot) -> tuple[str, str]:
    allocated = float(getattr(lot, "allocated_weight_lbs", 0) or 0)
    remaining = float(getattr(lot, "remaining_weight_lbs", 0) or 0)
    if allocated <= 0.01:
        return "on_hand", "On hand"
    if remaining <= 0.01:
        return "fully_allocated", "Fully allocated"
    return "partially_allocated", "Partially allocated"


def _annotate_inventory_lot(root, lot):
    state_key, state_label = _lot_allocation_state(lot)
    exceptions: list[str] = []
    if not getattr(lot, "tracking_id", None):
        exceptions.append("Missing tracking ID")
    if float(getattr(lot, "remaining_pct", 0) or 0) <= 15:
        exceptions.append("Low remaining")
    if not lot.purchase or not lot.purchase.is_approved:
        exceptions.append("Approval required")
    lot._allocation_state_key = state_key
    lot._allocation_state_label = state_label
    lot._floor_state_key = (getattr(lot, "floor_state", None) or "inventory").strip() or "inventory"
    floor_labels = {
        "inventory": "In inventory",
        "vault": "In vault",
        "reactor_staging": "Reactor staging",
        "quarantine": "Quarantine",
        "custom": "Custom movement",
    }
    lot._floor_state_label = floor_labels.get(lot._floor_state_key, lot._floor_state_key.replace("_", " ").title())
    lot._exceptions = exceptions
    lot._material_state = " / ".join(
        [part for part in [getattr(lot.purchase, "clean_or_dirty", None), getattr(lot.purchase, "testing_status", None)] if part]
    ) or "Needs review"
    return lot


def _annotate_in_transit_purchase(purchase):
    if purchase.status == "committed":
        purchase._next_action = "Schedule receipt"
    elif purchase.status == "in_transit":
        purchase._next_action = "Receive and approve"
    else:
        purchase._next_action = "Review / approve"
    purchase._exceptions = []
    if not purchase.is_approved:
        purchase._exceptions.append("Unapproved")
    if not purchase.delivery_date:
        purchase._exceptions.append("Missing delivery date")
    return purchase


def inventory_view(root):
    redir = root._list_filters_clear_redirect("inventory")
    if redir:
        return redir
    m = root._list_filters_merge("inventory", ("supplier_id", "strain"))
    supplier_filter = (m.get("supplier_id") or "").strip()
    strain_raw = (m.get("strain") or "").strip()
    strain_filter = strain_raw.lower()
    on_hand_q = root.PurchaseLot.query.join(root.Purchase).filter(
        root.PurchaseLot.remaining_weight_lbs > 0,
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        root.Purchase.purchase_approved_at.isnot(None),
    )
    if supplier_filter:
        on_hand_q = on_hand_q.filter(root.Purchase.supplier_id == supplier_filter)
    if strain_filter:
        on_hand_q = on_hand_q.filter(root.func.lower(root.PurchaseLot.strain_name).like(f"%{strain_filter}%"))
    on_hand = [_annotate_inventory_lot(root, lot) for lot in on_hand_q.all()]

    in_transit_q = root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(["committed", "ordered", "in_transit"]),
    )
    if supplier_filter:
        in_transit_q = in_transit_q.filter(root.Purchase.supplier_id == supplier_filter)
    in_transit = [_annotate_in_transit_purchase(purchase) for purchase in in_transit_q.all()]

    total_on_hand = sum(l.remaining_weight_lbs for l in on_hand)
    total_in_transit = sum(p.stated_weight_lbs for p in in_transit)
    daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0
    partially_allocated_count = sum(1 for lot in on_hand if getattr(lot, "_allocation_state_key", "") == "partially_allocated")
    low_remaining_count = sum(1 for lot in on_hand if "Low remaining" in getattr(lot, "_exceptions", []))
    missing_tracking_count = sum(1 for lot in on_hand if not getattr(lot, "tracking_id", None))

    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    inv_active = bool(supplier_filter or strain_raw)
    return root.render_template(
        "inventory.html",
        on_hand=on_hand,
        in_transit=in_transit,
        total_on_hand=total_on_hand,
        total_in_transit=total_in_transit,
        days_supply=days_supply,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        strain_filter=strain_raw,
        partially_allocated_count=partially_allocated_count,
        low_remaining_count=low_remaining_count,
        missing_tracking_count=missing_tracking_count,
        list_filters_active=inv_active,
        clear_filters_url=root.url_for("inventory", clear_filters=1),
    )


INVENTORY_IMPORT_ALLOWED_FLOOR_STATES = {
    "inventory": "In inventory",
    "vault": "In vault",
    "reactor_staging": "Reactor staging",
    "quarantine": "Quarantine",
    "custom": "Custom movement",
}


def inventory_import_staging_path(root, token: str) -> str:
    safe = "".join(c for c in (token or "") if c.isalnum() or c in "-_")
    if len(safe) < 8:
        raise ValueError("Invalid staging token.")
    return root.os.path.join(root.tempfile.gettempdir(), f"gdp_invimp_{safe}.json")


def inventory_import_load_staging(root, token: str) -> dict | None:
    try:
        path = inventory_import_staging_path(root, token)
    except ValueError:
        return None
    if not root.os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return root.json.load(f)
    except (OSError, root.json.JSONDecodeError):
        return None


def inventory_import_clear_staging(root, token: str) -> None:
    try:
        path = inventory_import_staging_path(root, token)
        if root.os.path.isfile(path):
            root.os.remove(path)
    except (OSError, ValueError):
        pass


def inventory_import_parse_optional_float(value: str) -> float | None:
    if not (value or "").strip():
        return None
    text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def inventory_import_parse_optional_bool(value: str) -> bool | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "milled"}:
        return True
    if text in {"0", "false", "no", "n", "not_milled", "unmilled"}:
        return False
    return None


def inventory_import_validate_row(root, raw: dict):
    errors: list[str] = []
    tracking_id = (raw.get("tracking_id") or "").strip().upper()
    if not tracking_id:
        errors.append("Tracking ID is required.")

    lot = None
    if tracking_id:
        lot = (
            root.PurchaseLot.query.join(root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id)
            .filter(
                root.PurchaseLot.deleted_at.is_(None),
                root.Purchase.deleted_at.is_(None),
                root.PurchaseLot.tracking_id == tracking_id,
            )
            .first()
        )
        if not lot:
            errors.append(f"Tracking ID {tracking_id!r} was not found.")

    potency_pct = None
    potency_raw = (raw.get("potency_pct") or "").strip()
    if potency_raw:
        potency_pct = inventory_import_parse_optional_float(potency_raw)
        if potency_pct is None:
            errors.append("Potency % is not a valid number.")

    floor_state = None
    floor_state_raw = (raw.get("floor_state") or "").strip()
    if floor_state_raw:
        floor_state = floor_state_raw.lower().replace(" ", "_").replace("-", "_")
        while "__" in floor_state:
            floor_state = floor_state.replace("__", "_")
        if floor_state not in INVENTORY_IMPORT_ALLOWED_FLOOR_STATES:
            errors.append(
                "Floor state must be one of: inventory, vault, reactor_staging, quarantine, or custom."
            )

    milled = None
    milled_raw = (raw.get("milled") or "").strip()
    if milled_raw:
        milled = inventory_import_parse_optional_bool(milled_raw)
        if milled is None:
            errors.append("Milled must be yes/no, true/false, milled, or unmilled.")

    updates: dict[str, object] = {}
    if (raw.get("strain_name") or "").strip():
        updates["strain_name"] = (raw.get("strain_name") or "").strip()
    if potency_raw:
        updates["potency_pct"] = potency_pct
    if (raw.get("location") or "").strip():
        updates["location"] = (raw.get("location") or "").strip()
    if floor_state_raw:
        updates["floor_state"] = floor_state
    if milled_raw:
        updates["milled"] = milled
    if (raw.get("notes") or "").strip():
        updates["notes"] = (raw.get("notes") or "").strip()

    if not errors and not updates:
        errors.append("Map at least one populated update field besides Tracking ID.")

    if errors:
        return errors, None

    assert lot is not None
    change_summary: list[dict[str, str]] = []
    for field, new_value in updates.items():
        old_value = getattr(lot, field, None)
        old_display = "" if old_value is None else str(old_value)
        new_display = "" if new_value is None else str(new_value)
        if old_display != new_display:
            change_summary.append({"field": field, "from": old_display, "to": new_display})

    if not change_summary:
        return ["This row does not change any current lot values."], None

    return [], {
        "lot_id": lot.id,
        "tracking_id": lot.tracking_id,
        "supplier_name": getattr(lot, "supplier_name", None),
        "current_strain_name": lot.strain_name,
        "updates": updates,
        "change_summary": change_summary,
    }


def inventory_import_build_staged_rows(root, staged: dict) -> list[dict]:
    rows = inventory_import_rows_from_mapping(
        staged.get("data_rows") or [],
        staged.get("mapping") or {},
        int(staged.get("header_row_index") or 0),
    )
    staged_rows = []
    for raw_row in rows:
        row_copy = dict(raw_row)
        sheet_row = row_copy.pop("_sheet_row", "")
        errs, norm = inventory_import_validate_row(root, row_copy)
        staged_rows.append(
            {
                "sheet_row": sheet_row,
                "raw": row_copy,
                "errors": errs,
                "normalized": norm,
                "action": "update",
            }
        )
    return staged_rows


def inventory_import_commit_norm(root, norm: dict) -> None:
    lot = root.db.session.get(root.PurchaseLot, norm["lot_id"])
    if not lot or lot.deleted_at is not None or not lot.purchase or lot.purchase.deleted_at is not None:
        raise ValueError(f"Lot {norm.get('tracking_id') or norm.get('lot_id')} is no longer available.")

    for field, value in (norm.get("updates") or {}).items():
        setattr(lot, field, value)
    root.log_audit(
        "update",
        "lot",
        lot.id,
        details=root.json.dumps(
            {
                "source": "inventory_import",
                "tracking_id": lot.tracking_id,
                "purchase_id": lot.purchase_id,
                "changes": norm.get("change_summary") or [],
            }
        ),
    )
    root.db.session.commit()


def inventory_import_view(root):
    denied = _require_inventory_import_access(root)
    if denied is not None:
        return denied
    if root.request.method == "GET":
        return root.render_template("inventory_import.html")
    f = root.request.files.get("spreadsheet")
    if not f or not getattr(f, "filename", None):
        root.flash("Choose a .csv, .xlsx, or .xlsm file to upload.", "error")
        return root.redirect(root.url_for("inventory_import"))
    raw = f.read()
    if not raw:
        root.flash("The file is empty.", "error")
        return root.redirect(root.url_for("inventory_import"))
    try:
        staged = parse_inventory_spreadsheet_upload_for_mapping(f.filename, raw)
    except ValueError as exc:
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("inventory_import"))

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
        with open(inventory_import_staging_path(root, token), "w", encoding="utf-8") as out:
            root.json.dump(payload, out)
    except OSError:
        root.flash("Could not stage import file; try again.", "error")
        return root.redirect(root.url_for("inventory_import"))

    root.session["inventory_import_token"] = token
    for warning in staged["warnings"]:
        root.flash(warning, "warning")
    return root.redirect(root.url_for("inventory_import_preview"))


def inventory_import_preview_view(root):
    denied = _require_inventory_import_access(root)
    if denied is not None:
        return denied
    token = (root.session.get("inventory_import_token") or "").strip()
    data = inventory_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("inventory_import"))
    if root.request.method == "POST":
        new_mapping: dict[str, str] = {}
        for header in data.get("headers") or []:
            idx = str(header.get("index"))
            field_name = (root.request.form.get(f"map_{idx}") or "").strip()
            if field_name:
                new_mapping[idx] = field_name
        data["mapping"] = new_mapping
        try:
            with open(inventory_import_staging_path(root, token), "w", encoding="utf-8") as out:
                root.json.dump(data, out)
        except OSError:
            root.flash("Could not update import mapping; try again.", "error")
            return root.redirect(root.url_for("inventory_import_preview"))

    staged_rows = inventory_import_build_staged_rows(root, data)
    ok_count = sum(1 for row in staged_rows if not row.get("errors"))
    mapped_headers = [
        {
            "index": header.get("index"),
            "header": header.get("header"),
            "normalized": header.get("normalized"),
            "field": (data.get("mapping") or {}).get(str(header.get("index")), ""),
            "field_label": INVENTORY_IMPORT_FIELDS.get((data.get("mapping") or {}).get(str(header.get("index")), ""), {}).get("label", ""),
        }
        for header in data.get("headers") or []
    ]
    mapped_preview_columns = [h for h in mapped_headers if h.get("field")]
    return root.render_template(
        "inventory_import_preview.html",
        staged=data,
        staged_rows=staged_rows,
        ok_count=ok_count,
        field_choices=inventory_import_field_choices(),
        mapped_headers=mapped_headers,
        mapped_preview_columns=mapped_preview_columns,
    )


def inventory_import_commit_view(root):
    denied = _require_inventory_import_access(root)
    if denied is not None:
        return denied
    token = (root.session.get("inventory_import_token") or "").strip()
    data = inventory_import_load_staging(root, token) if token else None
    if not data:
        root.flash("No staged import found. Upload a file again.", "error")
        return root.redirect(root.url_for("inventory_import"))
    staged_rows = inventory_import_build_staged_rows(root, data)
    selected = {int(x) for x in root.request.form.getlist("row_idx") if str(x).isdigit()}
    if not selected:
        root.flash("No rows selected to import.", "warning")
        return root.redirect(root.url_for("inventory_import_preview"))

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
            inventory_import_commit_norm(root, norm)
            imported += 1
        except ValueError as exc:
            root.db.session.rollback()
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: {exc}")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("inventory import row failed")
            failed += 1
            fail_msgs.append(f"Row {row.get('sheet_row', i)}: unexpected error.")

    inventory_import_clear_staging(root, token)
    root.session.pop("inventory_import_token", None)
    if imported:
        root.flash(f"Imported {imported} inventory update row(s).", "success")
    if failed:
        root.flash(f"{failed} row(s) not imported.", "warning")
    for msg in fail_msgs[:15]:
        root.flash(msg, "error")
    if len(fail_msgs) > 15:
        root.flash(f"...and {len(fail_msgs) - 15} more errors (see logs).", "error")
    return root.redirect(root.url_for("inventory"))


def inventory_import_sample_view(root):
    denied = _require_inventory_import_access(root)
    if denied is not None:
        return denied
    lines = [
        "Tracking ID,Strain,Potency %,Location,Floor State,Milled,Notes",
        "LOT-ABC12345,Blue Dream BX1,31.2,Dock B,reactor_staging,yes,Ready for charge",
    ]
    body = "\n".join(lines) + "\n"
    return root.Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=inventory_import_sample.csv"},
    )


def _require_inventory_import_access(root):
    if has_permission(root, root.current_user, "inventory.import"):
        return None
    root.flash("Inventory import access required.", "error")
    return root.redirect(root.url_for("inventory"))
