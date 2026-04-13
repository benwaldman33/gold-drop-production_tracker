from __future__ import annotations


def register_routes(app, root):
    @root.login_required
    def inventory():
        return inventory_view(root)

    app.add_url_rule("/inventory", endpoint="inventory", view_func=inventory)


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
