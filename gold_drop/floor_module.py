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

    return root.render_template(
        "floor_ops.html",
        recent_scans=recent_scans,
        recent_captures=recent_captures,
        active_scales=active_scales,
        open_lot_count=open_lot_count,
        scans_last_day=scans_last_day,
        captures_last_day=captures_last_day,
    )


def scan_center_view(root):
    return root.render_template("scan_center.html")
