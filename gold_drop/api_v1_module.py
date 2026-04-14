from __future__ import annotations

from datetime import datetime

from flask import jsonify, request

from gold_drop.inventory_module import _annotate_inventory_lot
from gold_drop.purchases_module import _annotate_purchase_row
from gold_drop.slack_integration_module import (
    slack_linked_run_ids_index,
    slack_supplier_candidates_for_source,
)
from gold_drop.slack import (
    _derive_slack_production_message,
    _load_slack_run_field_rules,
    _preview_slack_to_run_fields,
    _slack_coverage_label,
    _slack_imports_row_matches_kind_text,
    _slack_message_needs_resolution_ui,
    _slack_ts_to_date_value,
)
from models import Purchase, PurchaseLot, Run, SlackIngestedMessage, db
from services.api_auth import json_api_error, require_api_scope
from services.api_queries import (
    build_inventory_on_hand_query,
    build_lots_query,
    build_purchases_query,
    build_runs_query,
    parse_limit_offset,
)
from services.api_serializers import (
    envelope,
    serialize_inventory_lot,
    serialize_exception_item,
    serialize_lot_summary,
    serialize_purchase_detail,
    serialize_purchase_summary,
    serialize_run_detail,
    serialize_run_summary,
    serialize_slack_import_detail,
    serialize_slack_import_summary,
)
from services.api_site import get_site_identity
from services.lot_allocation import choose_default_lot_allocation, rank_lot_candidates
from services.purchases_journey import build_purchase_journey_payload

API_ROOT = None


def register_routes(app, root):
    global API_ROOT
    API_ROOT = root
    app.add_url_rule("/api/v1/site", endpoint="api_v1_site", view_func=api_v1_site)
    app.add_url_rule("/api/v1/purchases", endpoint="api_v1_purchases", view_func=api_v1_purchases)
    app.add_url_rule("/api/v1/purchases/<purchase_id>", endpoint="api_v1_purchase_detail", view_func=api_v1_purchase_detail)
    app.add_url_rule(
        "/api/v1/purchases/<purchase_id>/journey",
        endpoint="api_v1_purchase_journey",
        view_func=api_v1_purchase_journey,
    )
    app.add_url_rule("/api/v1/lots", endpoint="api_v1_lots", view_func=api_v1_lots)
    app.add_url_rule("/api/v1/lots/<lot_id>", endpoint="api_v1_lot_detail", view_func=api_v1_lot_detail)
    app.add_url_rule("/api/v1/runs", endpoint="api_v1_runs", view_func=api_v1_runs)
    app.add_url_rule("/api/v1/runs/<run_id>", endpoint="api_v1_run_detail", view_func=api_v1_run_detail)
    app.add_url_rule("/api/v1/slack-imports", endpoint="api_v1_slack_imports", view_func=api_v1_slack_imports)
    app.add_url_rule("/api/v1/slack-imports/<msg_id>", endpoint="api_v1_slack_import_detail", view_func=api_v1_slack_import_detail)
    app.add_url_rule("/api/v1/exceptions", endpoint="api_v1_exceptions", view_func=api_v1_exceptions)
    app.add_url_rule("/api/v1/summary/inventory", endpoint="api_v1_inventory_summary", view_func=api_v1_inventory_summary)
    app.add_url_rule("/api/v1/summary/slack-imports", endpoint="api_v1_slack_imports_summary", view_func=api_v1_slack_imports_summary)
    app.add_url_rule("/api/v1/summary/exceptions", endpoint="api_v1_exceptions_summary", view_func=api_v1_exceptions_summary)
    app.add_url_rule(
        "/api/v1/inventory/on-hand",
        endpoint="api_v1_inventory_on_hand",
        view_func=api_v1_inventory_on_hand,
    )


@require_api_scope("read:site")
def api_v1_site():
    return jsonify(envelope(get_site_identity()))


def _parse_optional_date(raw_value: str | None):
    raw = (raw_value or "").strip()
    if not raw:
        return None, None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date(), None
    except ValueError:
        return None, json_api_error(f"Invalid date '{raw}'. Use YYYY-MM-DD.", status_code=400, code="bad_request")


def _require_root():
    if API_ROOT is None:
        raise RuntimeError("API root not registered")
    return API_ROOT


@require_api_scope("read:purchases")
def api_v1_purchases():
    limit, offset = parse_limit_offset(request)
    start_date, error = _parse_optional_date(request.args.get("start_date"))
    if error:
        return error
    end_date, error = _parse_optional_date(request.args.get("end_date"))
    if error:
        return error
    approved_param = (request.args.get("approved") or "").strip().lower()
    approved = None
    if approved_param in {"1", "true", "yes"}:
        approved = True
    elif approved_param in {"0", "false", "no"}:
        approved = False
    query = build_purchases_query(
        status=(request.args.get("status") or "").strip() or None,
        supplier_id=(request.args.get("supplier_id") or "").strip() or None,
        approved=approved,
        start_date=start_date,
        end_date=end_date,
        include_archived=request.args.get("include_archived") == "1",
    )
    total = query.count()
    purchases = query.offset(offset).limit(limit).all()
    return jsonify(envelope([serialize_purchase_summary(purchase) for purchase in purchases], count=total, limit=limit, offset=offset))


@require_api_scope("read:purchases")
def api_v1_purchase_detail(purchase_id):
    include_archived = request.args.get("include_archived") == "1"
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return json_api_error("Purchase not found", status_code=404, code="not_found")
    if purchase.deleted_at is not None and not include_archived:
        return json_api_error("Purchase not found", status_code=404, code="not_found")
    return jsonify(envelope(serialize_purchase_detail(purchase)))


@require_api_scope("read:journey")
def api_v1_purchase_journey(purchase_id):
    include_archived = request.args.get("include_archived") == "1"
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return json_api_error("Purchase not found", status_code=404, code="not_found")
    if purchase.deleted_at is not None and not include_archived:
        return json_api_error(
            "Purchase is archived. Set include_archived=1 to view its journey.",
            status_code=404,
            code="not_found",
        )
    payload = build_purchase_journey_payload(purchase, include_archived=include_archived)
    return jsonify(envelope(payload))


@require_api_scope("read:lots")
def api_v1_lots():
    limit, offset = parse_limit_offset(request)
    query = build_lots_query(
        purchase_id=(request.args.get("purchase_id") or "").strip() or None,
        supplier_id=(request.args.get("supplier_id") or "").strip() or None,
        strain=(request.args.get("strain") or "").strip() or None,
        tracking_id=(request.args.get("tracking_id") or "").strip() or None,
        open_only=request.args.get("open_only") == "1",
        include_archived=request.args.get("include_archived") == "1",
    )
    total = query.count()
    lots = query.offset(offset).limit(limit).all()
    return jsonify(envelope([serialize_lot_summary(lot) for lot in lots], count=total, limit=limit, offset=offset))


@require_api_scope("read:lots")
def api_v1_lot_detail(lot_id):
    include_archived = request.args.get("include_archived") == "1"
    lot = db.session.get(PurchaseLot, lot_id)
    if not lot:
        return json_api_error("Lot not found", status_code=404, code="not_found")
    if not include_archived:
        if lot.deleted_at is not None or lot.purchase is None or lot.purchase.deleted_at is not None:
            return json_api_error("Lot not found", status_code=404, code="not_found")
    return jsonify(envelope(serialize_lot_summary(lot)))


@require_api_scope("read:runs")
def api_v1_runs():
    limit, offset = parse_limit_offset(request)
    start_date, error = _parse_optional_date(request.args.get("start_date"))
    if error:
        return error
    end_date, error = _parse_optional_date(request.args.get("end_date"))
    if error:
        return error
    reactor_number = None
    if (request.args.get("reactor_number") or "").strip():
        try:
            reactor_number = int(request.args.get("reactor_number"))
        except ValueError:
            return json_api_error("Invalid reactor_number", status_code=400, code="bad_request")
    slack_linked_param = (request.args.get("slack_linked") or "").strip().lower()
    slack_linked = None
    if slack_linked_param in {"1", "true", "yes"}:
        slack_linked = True
    elif slack_linked_param in {"0", "false", "no"}:
        slack_linked = False
    query = build_runs_query(
        start_date=start_date,
        end_date=end_date,
        reactor_number=reactor_number,
        supplier_id=(request.args.get("supplier_id") or "").strip() or None,
        strain=(request.args.get("strain") or "").strip() or None,
        slack_linked=slack_linked,
        include_archived=request.args.get("include_archived") == "1",
    )
    total = query.count()
    runs = query.offset(offset).limit(limit).all()
    return jsonify(envelope([serialize_run_summary(run) for run in runs], count=total, limit=limit, offset=offset))


@require_api_scope("read:runs")
def api_v1_run_detail(run_id):
    include_archived = request.args.get("include_archived") == "1"
    run = db.session.get(Run, run_id)
    if not run:
        return json_api_error("Run not found", status_code=404, code="not_found")
    if run.deleted_at is not None and not include_archived:
        return json_api_error("Run not found", status_code=404, code="not_found")
    return jsonify(envelope(serialize_run_detail(run)))


@require_api_scope("read:inventory")
def api_v1_inventory_on_hand():
    limit, offset = parse_limit_offset(request)
    query = build_inventory_on_hand_query(
        supplier_id=(request.args.get("supplier_id") or "").strip() or None,
        strain=(request.args.get("strain") or "").strip() or None,
    )
    total = query.count()
    lots = query.offset(offset).limit(limit).all()
    return jsonify(envelope([serialize_inventory_lot(lot) for lot in lots], count=total, limit=limit, offset=offset))


def _norm_promo(value):
    value = (value or "all").strip().lower()
    return value if value in ("all", "not_linked", "linked") else "all"


def _norm_cov(value):
    value = (value or "all").strip().lower()
    return value if value in ("all", "full", "partial", "none") else "all"


def _build_slack_import_items(root):
    start_date, error = _parse_optional_date(request.args.get("start_date"))
    if error:
        return None, error
    end_date, error = _parse_optional_date(request.args.get("end_date"))
    if error:
        return None, error
    promotion = _norm_promo(request.args.get("promotion"))
    coverage_filter = _norm_cov(request.args.get("coverage"))
    kind_filter = (request.args.get("kind_filter") or "all").strip().lower()
    text_filter = (request.args.get("text_filter") or "").strip()
    text_op = (request.args.get("text_op") or "contains").strip().lower()
    include_hidden = request.args.get("include_hidden") == "1"
    channel_id = (request.args.get("channel_id") or "").strip() or None
    if kind_filter not in {choice[0] for choice in root.SLACK_IMPORT_KIND_FILTER_CHOICES}:
        kind_filter = "all"
    if text_op not in root.SLACK_IMPORT_TEXT_OPS_ALLOWED:
        text_op = "contains"

    link_index = slack_linked_run_ids_index(root)
    rules = _load_slack_run_field_rules()
    pool = SlackIngestedMessage.query.order_by(root.desc(SlackIngestedMessage.message_ts)).limit(2500).all()
    items = []
    bucket_counts = {
        "auto_ready": 0,
        "needs_confirmation": 0,
        "needs_manual_match": 0,
        "blocked": 0,
        "processed": 0,
    }
    for row in pool:
        if not include_hidden and bool(getattr(row, "hidden_from_imports", False)):
            continue
        if channel_id and row.channel_id != channel_id:
            continue
        derived = _derive_slack_production_message(row.raw_text or "")
        root._ensure_slack_message_date_derived(derived, str(row.message_ts or ""))
        eff_kind = derived.get("message_kind") or row.message_kind
        if not _slack_imports_row_matches_kind_text(kind_filter, text_filter, text_op, eff_kind, row.raw_text):
            continue
        ts_date = _slack_ts_to_date_value(row.message_ts)
        if start_date and ts_date is not None and ts_date < start_date:
            continue
        if end_date and ts_date is not None and ts_date > end_date:
            continue
        preview = _preview_slack_to_run_fields(derived, str(row.message_ts or ""), eff_kind, rules)
        coverage = _slack_coverage_label(preview)
        if coverage_filter != "all" and coverage != coverage_filter:
            continue
        linked_run_ids = link_index.get((row.channel_id, row.message_ts), [])
        if promotion == "not_linked" and linked_run_ids:
            continue
        if promotion == "linked" and not linked_run_ids:
            continue

        requested_run_lbs = preview.get("filled", {}).get("bio_in_reactor_lbs")
        try:
            requested_run_lbs = float(requested_run_lbs) if requested_run_lbs not in (None, "") else None
        except (TypeError, ValueError):
            requested_run_lbs = None

        if linked_run_ids:
            triage_bucket = "processed"
        elif (derived.get("message_kind") or row.message_kind or "").strip() == "production_log" and requested_run_lbs:
            source_raw = (derived.get("source") or "").strip()
            supplier_candidates = slack_supplier_candidates_for_source(root, source_raw) if source_raw else []
            supplier_ids = [str(candidate["id"]) for candidate in supplier_candidates[:3]]
            lot_candidates = rank_lot_candidates(
                root,
                supplier_ids=supplier_ids,
                strain_name=(derived.get("strain") or "").strip(),
                requested_weight_lbs=requested_run_lbs,
            ) if supplier_ids else []
            auto_pick = choose_default_lot_allocation(lot_candidates, requested_run_lbs)
            if auto_pick:
                triage_bucket = "auto_ready"
            elif lot_candidates:
                triage_bucket = "needs_confirmation" if len(lot_candidates) == 1 else "needs_manual_match"
            else:
                triage_bucket = "blocked"
        elif _slack_message_needs_resolution_ui(derived):
            triage_bucket = "needs_confirmation"
        elif coverage == "full":
            triage_bucket = "needs_confirmation"
        elif coverage == "partial":
            triage_bucket = "needs_manual_match"
        else:
            triage_bucket = "blocked"

        bucket_counts[triage_bucket] += 1
        items.append(
            serialize_slack_import_summary(
                row,
                derived=derived,
                coverage=coverage,
                linked_run_ids=linked_run_ids,
            )
        )
        items[-1]["triage_bucket"] = triage_bucket
    return (items, bucket_counts), None


@require_api_scope("read:slack_imports")
def api_v1_slack_imports():
    root = _require_root()
    limit, offset = parse_limit_offset(request)
    built, error = _build_slack_import_items(root)
    if error:
        return error
    items, _bucket_counts = built
    total = len(items)
    return jsonify(envelope(items[offset : offset + limit], count=total, limit=limit, offset=offset))


@require_api_scope("read:slack_imports")
def api_v1_slack_import_detail(msg_id):
    root = _require_root()
    row = db.session.get(SlackIngestedMessage, msg_id)
    if not row:
        return json_api_error("Slack import not found", status_code=404, code="not_found")
    derived = _derive_slack_production_message(row.raw_text or "")
    root._ensure_slack_message_date_derived(derived, str(row.message_ts or ""))
    eff_kind = derived.get("message_kind") or row.message_kind
    preview = _preview_slack_to_run_fields(derived, str(row.message_ts or ""), eff_kind, _load_slack_run_field_rules())
    linked_run_ids = root.slack_integration_module.slack_linked_run_ids_index(root).get((row.channel_id, row.message_ts), [])
    return jsonify(
        envelope(
            serialize_slack_import_detail(
                row,
                derived=derived,
                preview=preview,
                coverage=_slack_coverage_label(preview),
                linked_run_ids=linked_run_ids,
                needs_resolution_ui=_slack_message_needs_resolution_ui(derived),
            )
        )
    )


@require_api_scope("read:exceptions")
def api_v1_exceptions():
    root = _require_root()
    limit, offset = parse_limit_offset(request)
    category = (request.args.get("category") or "all").strip().lower()
    allowed = {"all", "purchases", "inventory"}
    if category not in allowed:
        return json_api_error("Invalid category", status_code=400, code="bad_request")

    items = []
    if category in {"all", "purchases"}:
        purchases = Purchase.query.filter(Purchase.deleted_at.is_(None)).order_by(Purchase.purchase_date.desc(), Purchase.id.desc()).limit(500).all()
        for purchase in purchases:
            _annotate_purchase_row(purchase)
            for exc in getattr(purchase, "_exceptions", []):
                items.append(
                    serialize_exception_item(
                        category="purchases",
                        entity_type="purchase",
                        entity_id=purchase.id,
                        label=exc,
                        detail=f"{purchase.batch_id or purchase.id}: {exc}",
                        context={
                            "batch_id": purchase.batch_id,
                            "status": purchase.status,
                            "next_action": getattr(purchase, "_next_action", None),
                        },
                    )
                )
    if category in {"all", "inventory"}:
        lots = build_inventory_on_hand_query().limit(500).all()
        for lot in lots:
            _annotate_inventory_lot(root, lot)
            for exc in getattr(lot, "_exceptions", []):
                items.append(
                    serialize_exception_item(
                        category="inventory",
                        entity_type="purchase_lot",
                        entity_id=lot.id,
                        label=exc,
                        detail=f"{lot.display_label}: {exc}",
                        context={
                            "tracking_id": getattr(lot, "tracking_id", None),
                            "purchase_id": lot.purchase_id,
                            "batch_id": lot.purchase.batch_id if lot.purchase else None,
                            "allocation_state": getattr(lot, "_allocation_state_key", None),
                        },
                    )
                )
    total = len(items)
    return jsonify(envelope(items[offset : offset + limit], count=total, limit=limit, offset=offset))


@require_api_scope("read:inventory")
def api_v1_inventory_summary():
    root = _require_root()
    supplier_id = (request.args.get("supplier_id") or "").strip() or None
    strain = (request.args.get("strain") or "").strip() or None
    lots = build_inventory_on_hand_query(supplier_id=supplier_id, strain=strain).all()
    annotated = [_annotate_inventory_lot(root, lot) for lot in lots]
    total_on_hand = float(sum(float(lot.remaining_weight_lbs or 0) for lot in annotated))
    daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0.0
    payload = {
        "supplier_id": supplier_id,
        "strain": strain,
        "open_lot_count": len(annotated),
        "total_on_hand_lbs": total_on_hand,
        "days_of_supply": float(days_supply),
        "partially_allocated_count": sum(1 for lot in annotated if getattr(lot, "_allocation_state_key", "") == "partially_allocated"),
        "fully_allocated_count": sum(1 for lot in annotated if getattr(lot, "_allocation_state_key", "") == "fully_allocated"),
        "low_remaining_count": sum(1 for lot in annotated if "Low remaining" in getattr(lot, "_exceptions", [])),
        "missing_tracking_count": sum(1 for lot in annotated if "Missing tracking ID" in getattr(lot, "_exceptions", [])),
        "approval_required_count": sum(1 for lot in annotated if "Approval required" in getattr(lot, "_exceptions", [])),
    }
    return jsonify(envelope(payload))


@require_api_scope("read:slack_imports")
def api_v1_slack_imports_summary():
    root = _require_root()
    built, error = _build_slack_import_items(root)
    if error:
        return error
    items, bucket_counts = built
    payload = {
        "total_messages": len(items),
        "bucket_counts": bucket_counts,
        "linked_count": sum(1 for item in items if item.get("promotion_status") == "linked"),
        "unlinked_count": sum(1 for item in items if item.get("promotion_status") == "not_linked"),
        "coverage_counts": {
            "full": sum(1 for item in items if item.get("coverage") == "full"),
            "partial": sum(1 for item in items if item.get("coverage") == "partial"),
            "none": sum(1 for item in items if item.get("coverage") == "none"),
        },
    }
    return jsonify(envelope(payload))


@require_api_scope("read:exceptions")
def api_v1_exceptions_summary():
    root = _require_root()
    purchases = Purchase.query.filter(Purchase.deleted_at.is_(None)).order_by(Purchase.purchase_date.desc(), Purchase.id.desc()).limit(500).all()
    purchase_count = 0
    inventory_count = 0
    by_label: dict[str, int] = {}
    for purchase in purchases:
        _annotate_purchase_row(purchase)
        for exc in getattr(purchase, "_exceptions", []):
            purchase_count += 1
            by_label[exc] = by_label.get(exc, 0) + 1
    lots = build_inventory_on_hand_query().limit(500).all()
    for lot in lots:
        _annotate_inventory_lot(root, lot)
        for exc in getattr(lot, "_exceptions", []):
            inventory_count += 1
            by_label[exc] = by_label.get(exc, 0) + 1
    payload = {
        "total_exceptions": purchase_count + inventory_count,
        "category_counts": {
            "purchases": purchase_count,
            "inventory": inventory_count,
        },
        "label_counts": dict(sorted(by_label.items(), key=lambda item: (-item[1], item[0]))),
    }
    return jsonify(envelope(payload))
