"""Purchases blueprint (incremental extraction from app.py)."""

from __future__ import annotations

import csv
import io
import json

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Purchase, db
from services.purchases_journey import build_purchase_journey_payload

bp = Blueprint("purchases_bp", __name__)
SUPPORTED_JOURNEY_EXPORT_FORMATS = {"json", "csv"}


def _include_archived_requested() -> bool:
    return request.args.get("include_archived") == "1" and bool(current_user.is_super_admin)


def _journey_error_response(message: str, *, api: bool = False):
    if api:
        return jsonify({"error": message}), 404
    flash(message, "error")
    return redirect(url_for("purchases_list"))


def _load_purchase_for_journey_or_error(purchase_id: str, *, api: bool = False):
    purchase = db.session.get(Purchase, purchase_id)
    include_archived = _include_archived_requested()
    if not purchase:
        return None, include_archived, _journey_error_response("Purchase not found.", api=api)
    if purchase.deleted_at is not None and not include_archived:
        msg = (
            "Purchase is archived. Set include_archived=1 as super admin."
            if api
            else "This purchase is archived. Add include_archived=1 (super admin) to view its journey."
        )
        return None, include_archived, _journey_error_response(msg, api=api)
    return purchase, include_archived, None


@bp.route("/purchases/<purchase_id>/journey", endpoint="purchase_journey")
@login_required
def purchase_journey(purchase_id):
    purchase, include_archived, error = _load_purchase_for_journey_or_error(purchase_id)
    if error:
        return error
    journey = build_purchase_journey_payload(purchase, include_archived=include_archived)
    focus_tracking_id = (request.args.get("lot") or "").strip()
    return render_template(
        "purchase_journey.html",
        purchase=purchase,
        journey=journey,
        include_archived=include_archived,
        focus_tracking_id=focus_tracking_id,
    )


@bp.route("/purchases/<purchase_id>/journey/export", endpoint="purchase_journey_export")
@login_required
def purchase_journey_export(purchase_id):
    purchase, include_archived, error = _load_purchase_for_journey_or_error(purchase_id)
    if error:
        return error
    fmt = (request.args.get("format") or "json").strip().lower()
    if fmt not in SUPPORTED_JOURNEY_EXPORT_FORMATS:
        return (
            jsonify(
                {
                    "error": "Unsupported export format",
                    "supported_formats": sorted(SUPPORTED_JOURNEY_EXPORT_FORMATS),
                }
            ),
            400,
        )
    journey = build_purchase_journey_payload(purchase, include_archived=include_archived)

    safe_batch = (purchase.batch_id or purchase.id or "purchase").replace("/", "-")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["purchase_id", "batch_id", "stage_key", "state", "started_at", "completed_at", "metrics_json"])
        for ev in journey.get("events", []):
            w.writerow([
                purchase.id,
                purchase.batch_id or "",
                ev.get("stage_key") or "",
                ev.get("state") or "",
                ev.get("started_at") or "",
                ev.get("completed_at") or "",
                json.dumps(ev.get("metrics") or {}, separators=(",", ":")),
            ])
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_batch}-journey.csv"'},
        )
    return Response(
        json.dumps(journey, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_batch}-journey.json"'},
    )


@bp.route("/api/purchases/<purchase_id>/journey", endpoint="api_purchase_journey")
@login_required
def api_purchase_journey(purchase_id):
    purchase, include_archived, error = _load_purchase_for_journey_or_error(purchase_id, api=True)
    if error:
        return error
    return jsonify(build_purchase_journey_payload(purchase, include_archived=include_archived))
