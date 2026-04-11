from __future__ import annotations


def register_routes(app, root):
    @root.login_required
    def inventory():
        return inventory_view(root)

    app.add_url_rule("/inventory", endpoint="inventory", view_func=inventory)


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
    on_hand = on_hand_q.all()

    in_transit_q = root.Purchase.query.filter(
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(["committed", "ordered", "in_transit"]),
    )
    if supplier_filter:
        in_transit_q = in_transit_q.filter(root.Purchase.supplier_id == supplier_filter)
    in_transit = in_transit_q.all()

    total_on_hand = sum(l.remaining_weight_lbs for l in on_hand)
    total_in_transit = sum(p.stated_weight_lbs for p in in_transit)
    daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0

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
        list_filters_active=inv_active,
        clear_filters_url=root.url_for("inventory", clear_filters=1),
    )
