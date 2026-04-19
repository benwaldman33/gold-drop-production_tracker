from __future__ import annotations

from services.extraction_charge import (
    charge_history_entries,
    charge_state_badge,
    charge_state_label,
    charge_visible_on_board,
    display_charge_datetime_local,
    reactor_count,
    reactor_lifecycle_settings,
    update_charge_state,
)

BOARD_VIEW_OPTIONS = (
    ("all", "All reactors"),
    ("active", "Active only"),
    ("pending", "Pending only"),
    ("running", "Running only"),
    ("completed_today", "Completed today"),
    ("cancelled_today", "Cancelled today"),
)


def register_routes(app, root):
    @root.login_required
    def floor_ops():
        return floor_ops_view(root)

    @root.login_required
    def scan_center():
        return scan_center_view(root)

    @root.editor_required
    def floor_charge_transition(charge_id):
        return floor_charge_transition_view(root, charge_id)

    app.add_url_rule("/floor-ops", endpoint="floor_ops", view_func=floor_ops)
    app.add_url_rule("/scan", endpoint="scan_center", view_func=scan_center)
    app.add_url_rule("/floor-ops/charges/<charge_id>/transition", endpoint="floor_charge_transition", view_func=floor_charge_transition, methods=["POST"])


FLOOR_STATE_LABELS = {
    "inventory": "In inventory",
    "vault": "In vault",
    "reactor_staging": "Reactor staging",
    "quarantine": "Quarantine",
    "custom": "Custom movement",
}


def _reactor_numbers(root, charges):
    configured = max(int(reactor_count(root) or 1), 1)
    observed = {
        int(charge.reactor_number or 0)
        for charge in charges
        if int(charge.reactor_number or 0) > 0
    }
    max_reactor = max([configured, *observed]) if observed else configured
    return range(1, max_reactor + 1)


def _board_view_value(root):
    raw = (root.request.args.get("board_view") or "all").strip().lower()
    allowed = {value for value, _label in BOARD_VIEW_OPTIONS}
    return raw if raw in allowed else "all"


def _card_matches_board_view(card, board_view):
    state_key = (card.get("state_key") or "empty").strip()
    if board_view == "all":
        return True
    if board_view == "active":
        return state_key != "empty"
    if board_view == "pending":
        return state_key in {"pending", "in_reactor", "applied"}
    if board_view == "running":
        return state_key == "running"
    if board_view == "completed_today":
        return state_key == "completed"
    if board_view == "cancelled_today":
        return state_key == "cancelled"
    return True


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


def _build_reactor_charge_view(root):
    charges = (
        root.ExtractionCharge.query.join(root.PurchaseLot)
        .join(root.Purchase)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
        )
        .order_by(root.ExtractionCharge.charged_at.desc(), root.ExtractionCharge.created_at.desc())
        .limit(36)
        .all()
    )

    pending_cards = []
    applied_cards = []
    for reactor_number in _reactor_numbers(root, charges):
        reactor_charges = [charge for charge in charges if int(charge.reactor_number or 0) == reactor_number]
        pending = [charge for charge in reactor_charges if (charge.status or "pending") == "pending"][:4]
        applied = [charge for charge in reactor_charges if (charge.status or "") == "applied"][:3]

        pending_cards.append(
            {
                "reactor_number": reactor_number,
                "count": len(pending),
                "total_lbs": sum(float(charge.charged_weight_lbs or 0) for charge in pending),
                "charges": [
                    {
                        "id": charge.id,
                        "tracking_id": charge.lot.tracking_id if charge.lot else None,
                        "lot_id": charge.purchase_lot_id,
                        "supplier_name": charge.lot.supplier_name if charge.lot else "Unknown",
                        "strain_name": charge.lot.strain_name if charge.lot else "Unknown",
                        "charged_weight_lbs": float(charge.charged_weight_lbs or 0),
                        "charged_at_label": display_charge_datetime_local(charge.charged_at),
                        "source_mode": (charge.source_mode or "").replace("_", " "),
                        "notes": charge.notes,
                    }
                    for charge in pending
                ],
            }
        )

        applied_cards.append(
            {
                "reactor_number": reactor_number,
                "charges": [
                    {
                        "id": charge.id,
                        "tracking_id": charge.lot.tracking_id if charge.lot else None,
                        "supplier_name": charge.lot.supplier_name if charge.lot else "Unknown",
                        "strain_name": charge.lot.strain_name if charge.lot else "Unknown",
                        "charged_weight_lbs": float(charge.charged_weight_lbs or 0),
                        "charged_at_label": display_charge_datetime_local(charge.charged_at),
                        "run_id": charge.run_id,
                    }
                    for charge in applied
                ],
            }
        )

    pending_count = sum(card["count"] for card in pending_cards)
    pending_weight = sum(card["total_lbs"] for card in pending_cards)
    applied_count = sum(len(card["charges"]) for card in applied_cards)
    return {
        "pending_cards": pending_cards,
        "applied_cards": applied_cards,
        "pending_count": pending_count,
        "pending_weight_lbs": pending_weight,
        "applied_count": applied_count,
    }


def _build_active_reactor_board(root):
    settings = reactor_lifecycle_settings(root)
    charges = (
        root.ExtractionCharge.query.join(root.PurchaseLot)
        .join(root.Purchase)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
        )
        .order_by(root.ExtractionCharge.charged_at.desc(), root.ExtractionCharge.created_at.desc())
        .limit(60)
        .all()
    )

    cards = []
    for reactor_number in _reactor_numbers(root, charges):
        reactor_charges = [charge for charge in charges if int(charge.reactor_number or 0) == reactor_number]
        pending = [charge for charge in reactor_charges if (charge.status or "pending") == "pending"]
        current = next((charge for charge in reactor_charges if charge_visible_on_board(root, charge)), None)

        if current:
            state_key = (current.status or "pending").strip() or "pending"
            state_label = charge_state_label(state_key)
            state_badge = charge_state_badge(state_key)
            if state_key == "pending":
                next_step = "Open the saved charge and move it into reactor, start the run, or save the linked run."
            elif state_key == "applied":
                next_step = "Mark the charge running, complete it, or open the linked run."
            elif state_key == "in_reactor":
                next_step = "Mark the charge running when the reactor actually starts."
            elif state_key == "running":
                next_step = "Mark the charge complete when the reactor cycle finishes."
            elif state_key == "completed":
                next_step = "Completed charges stay visible until the day rolls over."
            else:
                next_step = "Cancelled charges stay visible until the day rolls over."
            history = charge_history_entries(root, current.id, limit=6) if settings["show_history"] else []
        else:
            state_key = "empty"
            state_label = "Empty"
            state_badge = "badge-gray"
            next_step = "Ready for the next lot charge."
            history = []

        cards.append(
            {
                "reactor_number": reactor_number,
                "state_key": state_key,
                "state_label": state_label,
                "state_badge": state_badge,
                "next_step": next_step,
                "pending_count": len(pending),
                "pending_weight_lbs": sum(float(charge.charged_weight_lbs or 0) for charge in pending),
                "show_history": settings["show_history"],
                "current": (
                    {
                        "charge_id": current.id,
                        "tracking_id": current.lot.tracking_id if current and current.lot else None,
                        "lot_id": current.purchase_lot_id if current else None,
                        "supplier_name": current.lot.supplier_name if current and current.lot else "Unknown",
                        "strain_name": current.lot.strain_name if current and current.lot else "Unknown",
                        "charged_weight_lbs": float(current.charged_weight_lbs or 0) if current else 0.0,
                        "charged_at_label": display_charge_datetime_local(current.charged_at) if current else None,
                        "operator_name": (
                            current.creator.display_name
                            if current and current.creator and current.creator.display_name
                            else None
                        ),
                        "state_key": state_key,
                        "state_label": state_label,
                        "source_mode": (current.source_mode or "").replace("_", " ") if current else None,
                        "run_id": current.run_id if current else None,
                        "available_actions": _reactor_card_actions(settings, current),
                        "history": history,
                    }
                    if current
                    else None
                ),
            }
        )

    active_count = sum(1 for card in cards if card["state_key"] != "empty")
    return {
        "cards": cards,
        "active_count": active_count,
        "reactor_count": len(cards),
    }


def _build_reactor_history(root, cards):
    history_cards = []
    for card in cards:
        current = card.get("current") or {}
        entries = list(current.get("history") or [])
        if current:
            if current.get("run_id"):
                entries.insert(
                    0,
                    {
                        "label": "Run linked",
                        "timestamp_label": current.get("charged_at_label") or "",
                        "run_id": current.get("run_id"),
                    },
                )
            entries.insert(
                0,
                {
                    "label": f"Charge recorded ({current.get('state_label')})",
                    "timestamp_label": current.get("charged_at_label") or "",
                    "run_id": current.get("run_id"),
                },
            )
        history_cards.append(
            {
                "reactor_number": card["reactor_number"],
                "state_label": card["state_label"],
                "entries": entries[:8],
            }
        )
    return history_cards


def _reactor_card_actions(settings, charge):
    status = (charge.status or "pending").strip() or "pending"
    actions = []
    if status in {"pending", "applied"} and settings["states"]["in_reactor"]["enabled"]:
        actions.append({"target_state": "in_reactor", "label": "Mark In Reactor"})
    if status in {"pending", "in_reactor", "applied"} and settings["states"]["running"]["enabled"]:
        actions.append({"target_state": "running", "label": "Mark Running"})
    if status in {"pending", "in_reactor", "applied", "running"} and settings["states"]["completed"]["enabled"]:
        actions.append({"target_state": "completed", "label": "Mark Complete"})
    if status in {"pending", "in_reactor", "applied", "running"} and settings["states"]["cancelled"]["enabled"]:
        actions.append({"target_state": "cancelled", "label": "Cancel Charge"})
    return actions


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
    reactor_charge_view = _build_reactor_charge_view(root)
    active_reactor_board = _build_active_reactor_board(root)
    board_view = _board_view_value(root)
    filtered_cards = [card for card in active_reactor_board["cards"] if _card_matches_board_view(card, board_view)]
    reactor_history = _build_reactor_history(root, active_reactor_board["cards"])
    reactor_lifecycle = reactor_lifecycle_settings(root)

    return root.render_template(
        "floor_ops.html",
        recent_scans=recent_scans,
        recent_captures=recent_captures,
        active_scales=active_scales,
        open_lot_count=open_lot_count,
        scans_last_day=scans_last_day,
        captures_last_day=captures_last_day,
        floor_rollups=floor_rollups,
        reactor_charge_view=reactor_charge_view,
        active_reactor_board=active_reactor_board,
        filtered_reactor_cards=filtered_cards,
        reactor_history=reactor_history,
        board_view=board_view,
        board_view_options=BOARD_VIEW_OPTIONS,
        reactor_lifecycle=reactor_lifecycle,
    )


def scan_center_view(root):
    recent_scans = root.LotScanEvent.query.order_by(root.LotScanEvent.created_at.desc()).limit(6).all()
    return root.render_template("scan_center.html", recent_scans=recent_scans)


def floor_charge_transition_view(root, charge_id):
    charge = root.db.session.get(root.ExtractionCharge, charge_id)
    if charge is None:
        root.flash("Extraction charge not found.", "error")
        return root.redirect(root.url_for("floor_ops"))

    target_state = (root.request.form.get("target_state") or "").strip()
    cancel_resolution = (root.request.form.get("cancel_resolution") or "").strip().lower() or None
    if target_state == "cancelled" and cancel_resolution not in {"modify", "abandon", None}:
        root.flash("Choose whether the cancelled charge should send you to modify the linked run or simply abandon it.", "error")
        return root.redirect(root.url_for("floor_ops"))

    try:
        history = charge_history_entries(root, charge.id, limit=20)
        update_charge_state(
            root,
            charge,
            target_state,
            history_entries=history,
            cancel_resolution=cancel_resolution,
            context={"source": "floor_ops"},
        )
        root.db.session.commit()
        root.flash(f"Reactor state updated to {charge_state_label(target_state)}.", "success")
        if target_state == "cancelled" and cancel_resolution == "modify" and charge.run_id:
            return root.redirect(root.url_for("run_edit", run_id=charge.run_id))
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("Error updating reactor charge state")
        root.flash("Error updating reactor charge state.", "error")
    return root.redirect(root.url_for("floor_ops"))
