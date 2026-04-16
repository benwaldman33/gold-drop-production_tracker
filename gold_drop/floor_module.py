from __future__ import annotations


def register_routes(app, root):
    @root.login_required
    def floor_ops():
        return floor_ops_view(root)

    @root.login_required
    def scan_center():
        return scan_center_view(root)

    app.add_url_rule("/floor-ops", endpoint="floor_ops", view_func=floor_ops)
    app.add_url_rule("/scan", endpoint="scan_center", view_func=scan_center)


FLOOR_STATE_LABELS = {
    "inventory": "In inventory",
    "vault": "In vault",
    "reactor_staging": "Reactor staging",
    "quarantine": "Quarantine",
    "custom": "Custom movement",
}


def _build_floor_rollups(root):
    open_lots = (
        root.PurchaseLot.query.join(root.Purchase)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.PurchaseLot.remaining_weight_lbs > 0,
        )
        .all()
    )
    state_counts = {key: 0 for key in FLOOR_STATE_LABELS}
    ready_count = 0
    ready_weight = 0.0
    pending_prep_count = 0
    pending_testing_count = 0

    for lot in open_lots:
        state_key = (lot.floor_state or "inventory").strip() or "inventory"
        state_counts[state_key] = state_counts.get(state_key, 0) + 1
        testing_status = (lot.purchase.testing_status or "pending") if lot.purchase else "pending"
        if not lot.milled:
            pending_prep_count += 1
        if testing_status not in {"completed", "not_needed"}:
            pending_testing_count += 1
        if lot.milled and testing_status in {"completed", "not_needed"} and state_key == "reactor_staging":
            ready_count += 1
            ready_weight += float(lot.remaining_weight_lbs or 0)

    return {
        "state_cards": [
            {"key": key, "label": label, "count": state_counts.get(key, 0)}
            for key, label in FLOOR_STATE_LABELS.items()
        ],
        "ready_count": ready_count,
        "ready_weight_lbs": ready_weight,
        "pending_prep_count": pending_prep_count,
        "pending_testing_count": pending_testing_count,
    }


def floor_ops_view(root):
    recent_scans = root.LotScanEvent.query.order_by(root.LotScanEvent.created_at.desc()).limit(12).all()
    recent_captures = root.WeightCapture.query.order_by(root.WeightCapture.created_at.desc()).limit(12).all()
    active_scales = root.ScaleDevice.query.filter_by(is_active=True).count()
    open_lot_count = root.PurchaseLot.query.filter(
        root.PurchaseLot.deleted_at.is_(None),
        root.PurchaseLot.remaining_weight_lbs > 0,
    ).count()

    scans_last_day = root.LotScanEvent.query.filter(
        root.LotScanEvent.created_at >= root.datetime.now(root.timezone.utc) - root.timedelta(days=1)
    ).count()
    captures_last_day = root.WeightCapture.query.filter(
        root.WeightCapture.created_at >= root.datetime.now(root.timezone.utc) - root.timedelta(days=1)
    ).count()
    floor_rollups = _build_floor_rollups(root)

    return root.render_template(
        "floor_ops.html",
        recent_scans=recent_scans,
        recent_captures=recent_captures,
        active_scales=active_scales,
        open_lot_count=open_lot_count,
        scans_last_day=scans_last_day,
        captures_last_day=captures_last_day,
        floor_rollups=floor_rollups,
    )


def scan_center_view(root):
    recent_scans = root.LotScanEvent.query.order_by(root.LotScanEvent.created_at.desc()).limit(6).all()
    return root.render_template("scan_center.html", recent_scans=recent_scans)
