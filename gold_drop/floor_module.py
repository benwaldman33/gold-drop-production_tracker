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
from services.extraction_run import (
    HTE_POTENCY_DISPOSITION_LABELS,
    HTE_QUEUE_DESTINATION_LABELS,
    POST_EXTRACTION_PATHWAY_LABELS,
    THCA_DESTINATION_LABELS,
    display_local_timestamp,
)

BOARD_VIEW_OPTIONS = (
    ("all", "All reactors"),
    ("active", "Active only"),
    ("pending", "Pending only"),
    ("running", "Running only"),
    ("completed_today", "Completed today"),
    ("cancelled_today", "Cancelled today"),
)

DOWNSTREAM_QUEUE_SECTIONS = (
    (
        "needs_routing",
        "Needs Queue Decision",
        "Minor-run outputs that have started post-extraction but still need a downstream destination or hold.",
    ),
    (
        "golddrop_queue",
        "GoldDrop Production Queue",
        "Runs ready to move into GoldDrop production planning.",
    ),
    (
        "liquid_loud_hold",
        "Liquid Loud Hold",
        "Material being held back for Liquid Loud processing.",
    ),
    (
        "terp_strip_cage",
        "Terp Strip / CDT Cage",
        "Dirty or hard-to-filter HTE queued for upstairs terp stripping / CDT handling.",
    ),
    (
        "hold_hp_base_oil",
        "HP Base Oil Hold",
        "Low-potency output held for HP base oil decisions.",
    ),
    (
        "hold_distillate",
        "Distillate Hold",
        "High-potency output held to be made into distillate.",
    ),
)


def register_routes(app, root):
    @root.login_required
    def floor_ops():
        return floor_ops_view(root)

    @root.login_required
    def scan_center():
        return scan_center_view(root)

    @root.login_required
    def downstream_queues():
        return downstream_queues_view(root)

    @root.editor_required
    def floor_charge_transition(charge_id):
        return floor_charge_transition_view(root, charge_id)

    @root.editor_required
    def downstream_queue_move(run_id):
        return downstream_queue_move_view(root, run_id)

    app.add_url_rule("/floor-ops", endpoint="floor_ops", view_func=floor_ops)
    app.add_url_rule("/scan", endpoint="scan_center", view_func=scan_center)
    app.add_url_rule("/downstream-queues", endpoint="downstream_queues", view_func=downstream_queues)
    app.add_url_rule("/floor-ops/charges/<charge_id>/transition", endpoint="floor_charge_transition", view_func=floor_charge_transition, methods=["POST"])
    app.add_url_rule("/downstream-queues/runs/<run_id>/move", endpoint="downstream_queue_move", view_func=downstream_queue_move, methods=["POST"])


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


def _downstream_active_queue(run):
    potency_hold = (getattr(run, "hte_potency_disposition", None) or "").strip()
    if potency_hold in {"hold_hp_base_oil", "hold_distillate"}:
        return potency_hold
    queue_destination = (getattr(run, "hte_queue_destination", None) or "").strip()
    if queue_destination in {"golddrop_queue", "liquid_loud_hold", "terp_strip_cage"}:
        return queue_destination
    pathway = (getattr(run, "post_extraction_pathway", None) or "").strip()
    if pathway == "minor_run_200" and getattr(run, "post_extraction_initial_outputs_recorded_at", None):
        return "needs_routing"
    return None


def _downstream_move_options():
    return [
        {"value": "golddrop_queue", "label": "Move to GoldDrop production queue"},
        {"value": "liquid_loud_hold", "label": "Move to Liquid Loud hold"},
        {"value": "terp_strip_cage", "label": "Send to Terp strip / CDT cage"},
        {"value": "hold_hp_base_oil", "label": "Hold for HP base oil"},
        {"value": "hold_distillate", "label": "Hold for distillate"},
    ]


def _downstream_next_step(item):
    queue_key = item["queue_key"]
    if queue_key == "needs_routing":
        return "Choose the next downstream destination or hold for this HTE output."
    if queue_key == "golddrop_queue":
        return "Ready for GoldDrop production planning and handoff."
    if queue_key == "liquid_loud_hold":
        return "Hold until Liquid Loud allocation and release are decided."
    if queue_key == "terp_strip_cage":
        return "Await upstairs terp strip / CDT work or Prescott handling."
    if queue_key == "hold_hp_base_oil":
        return "Held until HP base oil disposition is scheduled."
    if queue_key == "hold_distillate":
        return "Held until distillate production scheduling is confirmed."
    return "Open the run for supervisor review."


def _build_downstream_queue_item(root, run):
    allocations = list(run.inputs.all())
    lots = [allocation.lot for allocation in allocations if allocation.lot]
    strain_names = sorted({(lot.strain_name or "").strip() for lot in lots if (lot.strain_name or "").strip()})
    supplier_names = sorted({(lot.supplier_name or "").strip() for lot in lots if (lot.supplier_name or "").strip()})
    tracking_ids = [lot.tracking_id for lot in lots if lot.tracking_id]
    queue_key = _downstream_active_queue(run)
    return {
        "run_id": run.id,
        "run_date_label": run.run_date.strftime("%Y-%m-%d") if run.run_date else "Unknown date",
        "reactor_number": run.reactor_number,
        "queue_key": queue_key,
        "pathway_label": POST_EXTRACTION_PATHWAY_LABELS.get((run.post_extraction_pathway or "").strip(), "Not set"),
        "strain_summary": ", ".join(strain_names) if strain_names else "Unknown strain",
        "supplier_summary": ", ".join(supplier_names) if supplier_names else "Unknown supplier",
        "tracking_ids": tracking_ids,
        "wet_hte_g": float(run.wet_hte_g or 0),
        "wet_thca_g": float(run.wet_thca_g or 0),
        "dry_hte_g": float(run.dry_hte_g or 0),
        "dry_thca_g": float(run.dry_thca_g or 0),
        "post_extraction_started_at_label": display_local_timestamp(getattr(run, "post_extraction_started_at", None)),
        "outputs_confirmed_at_label": display_local_timestamp(getattr(run, "post_extraction_initial_outputs_recorded_at", None)),
        "thca_destination_label": THCA_DESTINATION_LABELS.get((run.thca_destination or "").strip(), ""),
        "hte_clean_decision_label": {"clean": "Clean", "dirty": "Dirty"}.get((run.hte_clean_decision or "").strip(), ""),
        "hte_filter_outcome_label": {"standard": "Standard refinement path", "needs_prescott": "Needs Prescott"}.get((run.hte_filter_outcome or "").strip(), ""),
        "hte_queue_destination_label": HTE_QUEUE_DESTINATION_LABELS.get((run.hte_queue_destination or "").strip(), ""),
        "hte_potency_disposition_label": HTE_POTENCY_DISPOSITION_LABELS.get((run.hte_potency_disposition or "").strip(), ""),
    }


def _build_downstream_queues(root):
    runs = (
        root.Run.query.filter(
            root.Run.deleted_at.is_(None),
            root.Run.run_completed_at.isnot(None),
            root.Run.post_extraction_started_at.isnot(None),
            root.Run.post_extraction_initial_outputs_recorded_at.isnot(None),
        )
        .order_by(root.Run.run_date.desc(), root.Run.created_at.desc())
        .limit(120)
        .all()
    )
    section_map = {
        key: {
            "key": key,
            "label": label,
            "description": description,
            "items": [],
        }
        for key, label, description in DOWNSTREAM_QUEUE_SECTIONS
    }
    for run in runs:
        item = _build_downstream_queue_item(root, run)
        queue_key = item["queue_key"]
        if not queue_key:
            continue
        item["next_step"] = _downstream_next_step(item)
        section_map[queue_key]["items"].append(item)
    sections = [section_map[key] for key, _label, _description in DOWNSTREAM_QUEUE_SECTIONS]
    summary_cards = [
        {
            "key": section["key"],
            "label": section["label"],
            "count": len(section["items"]),
        }
        for section in sections
    ]
    return {
        "sections": sections,
        "summary_cards": summary_cards,
        "move_options": _downstream_move_options(),
        "active_count": sum(card["count"] for card in summary_cards),
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


def downstream_queues_view(root):
    queues = _build_downstream_queues(root)
    return root.render_template(
        "downstream_queues.html",
        downstream_queues=queues,
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


def downstream_queue_move_view(root, run_id):
    run = root.db.session.get(root.Run, run_id)
    if run is None or run.deleted_at is not None:
        root.flash("Run not found.", "error")
        return root.redirect(root.url_for("downstream_queues"))
    if run.run_completed_at is None or run.post_extraction_initial_outputs_recorded_at is None:
        root.flash("This run is not ready for downstream queue management yet.", "error")
        return root.redirect(root.url_for("downstream_queues"))

    previous_queue = _downstream_active_queue(run)
    target = (root.request.form.get("target_destination") or "").strip()
    if target not in {"golddrop_queue", "liquid_loud_hold", "terp_strip_cage", "hold_hp_base_oil", "hold_distillate", "complete"}:
        root.flash("Choose a valid downstream destination.", "error")
        return root.redirect(root.url_for("downstream_queues"))

    if target == "complete":
        run.hte_queue_destination = None
        run.hte_potency_disposition = None
        message = "Downstream queue item marked complete."
    elif target in {"hold_hp_base_oil", "hold_distillate"}:
        run.hte_potency_disposition = target
        run.hte_queue_destination = None
        message = f"Run moved to {HTE_POTENCY_DISPOSITION_LABELS[target]}."
    else:
        run.hte_queue_destination = target
        run.hte_potency_disposition = None
        message = f"Run moved to {HTE_QUEUE_DESTINATION_LABELS[target]}."

    root.log_audit(
        "update",
        "run",
        run.id,
        details=root.json.dumps(
            {
                "source": "downstream_queues",
                "previous_queue": previous_queue,
                "target_destination": target,
            }
        ),
    )
    root.db.session.commit()
    root.flash(message, "success")
    return root.redirect(root.url_for("downstream_queues"))
