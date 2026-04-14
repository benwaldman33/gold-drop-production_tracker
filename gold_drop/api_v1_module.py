from __future__ import annotations

from datetime import datetime

from flask import jsonify, request

from models import Purchase, PurchaseLot, Run, db
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
    serialize_lot_summary,
    serialize_purchase_detail,
    serialize_purchase_summary,
    serialize_run_detail,
    serialize_run_summary,
)
from services.api_site import get_site_identity
from services.purchases_journey import build_purchase_journey_payload


def register_routes(app, root):
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
