from __future__ import annotations

from datetime import datetime

from flask import jsonify, request
from sqlalchemy import or_

from gold_drop.inventory_module import _annotate_inventory_lot
from gold_drop.purchases_module import _annotate_purchase_row
from gold_drop.suppliers_module import supplier_incomplete_profile_fields
from gold_drop.dashboard_module import DEPARTMENT_PAGES, _department_stat_sections, _weekly_finance_snapshot
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
from models import LotScanEvent, MaterialLot, Purchase, PurchaseLot, RemoteSite, Run, RunInput, ScaleDevice, SlackIngestedMessage, Supplier, WeightCapture, db
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
    serialize_material_reconciliation_issue,
    serialize_material_lot_summary,
    serialize_purchase_detail,
    serialize_purchase_summary,
    serialize_run_detail,
    serialize_run_summary,
    serialize_scan_event,
    serialize_scale_device,
    serialize_slack_import_detail,
    serialize_slack_import_summary,
    serialize_strain_performance_row,
    serialize_supplier_performance_row,
    serialize_search_result,
    serialize_weight_capture,
)
from services.api_site import get_site_identity
from services.lot_allocation import choose_default_lot_allocation, rank_lot_candidates
from services.material_genealogy import (
    build_material_cost_summary_payload,
    build_material_reporting_payload,
    build_material_lot_ancestry_payload,
    build_material_lot_descendants_payload,
    build_material_lot_detail_payload,
    build_material_lot_journey_payload,
    first_open_reconciliation_issues,
)
from services.purchases_journey import build_lot_journey_payload, build_purchase_journey_payload, build_run_journey_payload
from services.site_aggregation import build_aggregation_summary, serialize_remote_site_cache

API_ROOT = None


def register_routes(app, root):
    global API_ROOT
    API_ROOT = root
    app.add_url_rule("/api/v1/site", endpoint="api_v1_site", view_func=api_v1_site)
    app.add_url_rule("/api/v1/capabilities", endpoint="api_v1_capabilities", view_func=api_v1_capabilities)
    app.add_url_rule("/api/v1/sync/manifest", endpoint="api_v1_sync_manifest", view_func=api_v1_sync_manifest)
    app.add_url_rule("/api/v1/aggregation/sites", endpoint="api_v1_aggregation_sites", view_func=api_v1_aggregation_sites)
    app.add_url_rule("/api/v1/aggregation/sites/<site_id>", endpoint="api_v1_aggregation_site_detail", view_func=api_v1_aggregation_site_detail)
    app.add_url_rule("/api/v1/aggregation/summary", endpoint="api_v1_aggregation_summary", view_func=api_v1_aggregation_summary)
    app.add_url_rule("/api/v1/aggregation/suppliers", endpoint="api_v1_aggregation_suppliers", view_func=api_v1_aggregation_suppliers)
    app.add_url_rule("/api/v1/aggregation/strains", endpoint="api_v1_aggregation_strains", view_func=api_v1_aggregation_strains)
    app.add_url_rule("/api/v1/search", endpoint="api_v1_search", view_func=api_v1_search)
    app.add_url_rule("/api/v1/tools/inventory-snapshot", endpoint="api_v1_tool_inventory_snapshot", view_func=api_v1_tool_inventory_snapshot)
    app.add_url_rule("/api/v1/tools/open-lots", endpoint="api_v1_tool_open_lots", view_func=api_v1_tool_open_lots)
    app.add_url_rule("/api/v1/tools/journey-resolve", endpoint="api_v1_tool_journey_resolve", view_func=api_v1_tool_journey_resolve)
    app.add_url_rule("/api/v1/tools/reconciliation-overview", endpoint="api_v1_tool_reconciliation_overview", view_func=api_v1_tool_reconciliation_overview)
    app.add_url_rule("/api/v1/summary/dashboard", endpoint="api_v1_dashboard_summary", view_func=api_v1_dashboard_summary)
    app.add_url_rule("/api/v1/summary/material-costs", endpoint="api_v1_material_costs_summary", view_func=api_v1_material_costs_summary)
    app.add_url_rule("/api/v1/summary/material-genealogy", endpoint="api_v1_material_genealogy_summary", view_func=api_v1_material_genealogy_summary)
    app.add_url_rule("/api/v1/departments", endpoint="api_v1_departments", view_func=api_v1_departments)
    app.add_url_rule("/api/v1/departments/<slug>", endpoint="api_v1_department_detail", view_func=api_v1_department_detail)
    app.add_url_rule("/api/v1/purchases", endpoint="api_v1_purchases", view_func=api_v1_purchases)
    app.add_url_rule("/api/v1/purchases/<purchase_id>", endpoint="api_v1_purchase_detail", view_func=api_v1_purchase_detail)
    app.add_url_rule(
        "/api/v1/purchases/<purchase_id>/journey",
        endpoint="api_v1_purchase_journey",
        view_func=api_v1_purchase_journey,
    )
    app.add_url_rule("/api/v1/lots", endpoint="api_v1_lots", view_func=api_v1_lots)
    app.add_url_rule("/api/v1/lots/<lot_id>", endpoint="api_v1_lot_detail", view_func=api_v1_lot_detail)
    app.add_url_rule("/api/v1/lots/<lot_id>/journey", endpoint="api_v1_lot_journey", view_func=api_v1_lot_journey)
    app.add_url_rule("/api/v1/material-lots/<lot_id>", endpoint="api_v1_material_lot_detail", view_func=api_v1_material_lot_detail)
    app.add_url_rule("/api/v1/material-lots/<lot_id>/journey", endpoint="api_v1_material_lot_journey", view_func=api_v1_material_lot_journey)
    app.add_url_rule("/api/v1/material-lots/<lot_id>/ancestry", endpoint="api_v1_material_lot_ancestry", view_func=api_v1_material_lot_ancestry)
    app.add_url_rule("/api/v1/material-lots/<lot_id>/descendants", endpoint="api_v1_material_lot_descendants", view_func=api_v1_material_lot_descendants)
    app.add_url_rule("/api/v1/runs", endpoint="api_v1_runs", view_func=api_v1_runs)
    app.add_url_rule("/api/v1/runs/<run_id>", endpoint="api_v1_run_detail", view_func=api_v1_run_detail)
    app.add_url_rule("/api/v1/runs/<run_id>/journey", endpoint="api_v1_run_journey", view_func=api_v1_run_journey)
    app.add_url_rule("/api/v1/suppliers", endpoint="api_v1_suppliers", view_func=api_v1_suppliers)
    app.add_url_rule("/api/v1/suppliers/<supplier_id>", endpoint="api_v1_supplier_detail", view_func=api_v1_supplier_detail)
    app.add_url_rule("/api/v1/strains", endpoint="api_v1_strains", view_func=api_v1_strains)
    app.add_url_rule("/api/v1/slack-imports", endpoint="api_v1_slack_imports", view_func=api_v1_slack_imports)
    app.add_url_rule("/api/v1/slack-imports/<msg_id>", endpoint="api_v1_slack_import_detail", view_func=api_v1_slack_import_detail)
    app.add_url_rule("/api/v1/exceptions", endpoint="api_v1_exceptions", view_func=api_v1_exceptions)
    app.add_url_rule("/api/v1/scale-devices", endpoint="api_v1_scale_devices", view_func=api_v1_scale_devices)
    app.add_url_rule("/api/v1/weight-captures", endpoint="api_v1_weight_captures", view_func=api_v1_weight_captures)
    app.add_url_rule("/api/v1/scan-events", endpoint="api_v1_scan_events", view_func=api_v1_scan_events)
    app.add_url_rule("/api/v1/lots/<lot_id>/scans", endpoint="api_v1_lot_scans", view_func=api_v1_lot_scans)
    app.add_url_rule("/api/v1/summary/inventory", endpoint="api_v1_inventory_summary", view_func=api_v1_inventory_summary)
    app.add_url_rule("/api/v1/summary/slack-imports", endpoint="api_v1_slack_imports_summary", view_func=api_v1_slack_imports_summary)
    app.add_url_rule("/api/v1/summary/exceptions", endpoint="api_v1_exceptions_summary", view_func=api_v1_exceptions_summary)
    app.add_url_rule("/api/v1/summary/scanner", endpoint="api_v1_scanner_summary", view_func=api_v1_scanner_summary)
    app.add_url_rule("/api/v1/summary/scales", endpoint="api_v1_scales_summary", view_func=api_v1_scales_summary)
    app.add_url_rule(
        "/api/v1/inventory/on-hand",
        endpoint="api_v1_inventory_on_hand",
        view_func=api_v1_inventory_on_hand,
    )


@require_api_scope("read:site")
def api_v1_site():
    return jsonify(envelope(get_site_identity()))


@require_api_scope("read:site")
def api_v1_sync_manifest():
    datasets = {
        "purchases": {
            "count": Purchase.query.filter(Purchase.deleted_at.is_(None)).count(),
            "archived_count": Purchase.query.filter(Purchase.deleted_at.isnot(None)).count(),
            "last_created_at": db.session.query(db.func.max(Purchase.created_at)).scalar(),
            "last_updated_at": db.session.query(db.func.max(Purchase.updated_at)).scalar(),
        },
        "lots": {
            "count": PurchaseLot.query.filter(PurchaseLot.deleted_at.is_(None)).count(),
            "archived_count": PurchaseLot.query.filter(PurchaseLot.deleted_at.isnot(None)).count(),
            "last_label_generated_at": db.session.query(db.func.max(PurchaseLot.label_generated_at)).scalar(),
        },
        "runs": {
            "count": Run.query.filter(Run.deleted_at.is_(None)).count(),
            "archived_count": Run.query.filter(Run.deleted_at.isnot(None)).count(),
            "last_created_at": db.session.query(db.func.max(Run.created_at)).scalar(),
            "last_run_date": db.session.query(db.func.max(Run.run_date)).scalar(),
        },
        "slack_imports": {
            "count": SlackIngestedMessage.query.count(),
            "last_ingested_at": db.session.query(db.func.max(SlackIngestedMessage.ingested_at)).scalar(),
        },
        "suppliers": {
            "count": Supplier.query.count(),
            "active_count": Supplier.query.filter(Supplier.is_active.is_(True)).count(),
            "last_created_at": db.session.query(db.func.max(Supplier.created_at)).scalar(),
        },
    }
    payload = {
        "site": get_site_identity(),
        "datasets": {
            name: {
                key: (value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value.isoformat() if hasattr(value, "isoformat") and value is not None else value)
                for key, value in dataset.items()
            }
            for name, dataset in datasets.items()
        },
        "capabilities_endpoint": "/api/v1/capabilities",
    }
    return jsonify(envelope(payload))


@require_api_scope("read:site")
def api_v1_capabilities():
    payload = {
        "authentication": {
            "scheme": "bearer",
            "scope_model": "read_only_v1",
        },
        "scopes": [
            "read:site",
            "read:purchases",
            "read:journey",
            "read:lots",
            "read:runs",
            "read:inventory",
            "read:dashboard",
            "read:aggregation",
            "read:search",
            "read:tools",
            "read:slack_imports",
            "read:exceptions",
            "read:scanner",
            "read:scales",
            "read:suppliers",
            "read:strains",
        ],
        "endpoints": [
            {"path": "/api/v1/site", "scope": "read:site", "kind": "identity"},
            {"path": "/api/v1/capabilities", "scope": "read:site", "kind": "discovery"},
            {"path": "/api/v1/sync/manifest", "scope": "read:site", "kind": "manifest"},
            {"path": "/api/v1/aggregation/sites", "scope": "read:aggregation", "kind": "list"},
            {"path": "/api/v1/aggregation/sites/<site_id>", "scope": "read:aggregation", "kind": "detail"},
            {"path": "/api/v1/aggregation/summary", "scope": "read:aggregation", "kind": "summary"},
            {"path": "/api/v1/aggregation/suppliers", "scope": "read:aggregation", "kind": "list"},
            {"path": "/api/v1/aggregation/strains", "scope": "read:aggregation", "kind": "list"},
            {"path": "/api/v1/search", "scope": "read:search", "kind": "search"},
            {"path": "/api/v1/tools/inventory-snapshot", "scope": "read:tools", "kind": "tool"},
            {"path": "/api/v1/tools/open-lots", "scope": "read:tools", "kind": "tool"},
            {"path": "/api/v1/tools/journey-resolve", "scope": "read:tools", "kind": "tool"},
            {"path": "/api/v1/tools/reconciliation-overview", "scope": "read:tools", "kind": "tool"},
            {"path": "/api/v1/summary/dashboard", "scope": "read:dashboard", "kind": "summary"},
            {"path": "/api/v1/summary/material-costs", "scope": "read:inventory", "kind": "summary"},
            {"path": "/api/v1/summary/material-genealogy", "scope": "read:inventory", "kind": "summary"},
            {"path": "/api/v1/departments", "scope": "read:dashboard", "kind": "list"},
            {"path": "/api/v1/departments/<slug>", "scope": "read:dashboard", "kind": "detail"},
            {"path": "/api/v1/purchases", "scope": "read:purchases", "kind": "list"},
            {"path": "/api/v1/purchases/<purchase_id>", "scope": "read:purchases", "kind": "detail"},
            {"path": "/api/v1/purchases/<purchase_id>/journey", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/lots", "scope": "read:lots", "kind": "list"},
            {"path": "/api/v1/lots/<lot_id>", "scope": "read:lots", "kind": "detail"},
            {"path": "/api/v1/lots/<lot_id>/journey", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/material-lots/<lot_id>", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/material-lots/<lot_id>/journey", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/material-lots/<lot_id>/ancestry", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/material-lots/<lot_id>/descendants", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/inventory/on-hand", "scope": "read:inventory", "kind": "list"},
            {"path": "/api/v1/summary/inventory", "scope": "read:inventory", "kind": "summary"},
            {"path": "/api/v1/runs", "scope": "read:runs", "kind": "list"},
            {"path": "/api/v1/runs/<run_id>", "scope": "read:runs", "kind": "detail"},
            {"path": "/api/v1/runs/<run_id>/journey", "scope": "read:journey", "kind": "detail"},
            {"path": "/api/v1/suppliers", "scope": "read:suppliers", "kind": "list"},
            {"path": "/api/v1/suppliers/<supplier_id>", "scope": "read:suppliers", "kind": "detail"},
            {"path": "/api/v1/strains", "scope": "read:strains", "kind": "list"},
            {"path": "/api/v1/slack-imports", "scope": "read:slack_imports", "kind": "list"},
            {"path": "/api/v1/slack-imports/<msg_id>", "scope": "read:slack_imports", "kind": "detail"},
            {"path": "/api/v1/summary/slack-imports", "scope": "read:slack_imports", "kind": "summary"},
            {"path": "/api/v1/exceptions", "scope": "read:exceptions", "kind": "list"},
            {"path": "/api/v1/summary/exceptions", "scope": "read:exceptions", "kind": "summary"},
            {"path": "/api/v1/scale-devices", "scope": "read:scales", "kind": "list"},
            {"path": "/api/v1/weight-captures", "scope": "read:scales", "kind": "list"},
            {"path": "/api/v1/summary/scales", "scope": "read:scales", "kind": "summary"},
            {"path": "/api/v1/scan-events", "scope": "read:scanner", "kind": "list"},
            {"path": "/api/v1/lots/<lot_id>/scans", "scope": "read:scanner", "kind": "list"},
            {"path": "/api/v1/summary/scanner", "scope": "read:scanner", "kind": "summary"},
        ],
    }
    return jsonify(envelope(payload))


@require_api_scope("read:aggregation")
def api_v1_aggregation_sites():
    limit, offset = parse_limit_offset(request, default_limit=50, max_limit=200)
    sites = RemoteSite.query.order_by(RemoteSite.name.asc()).all()
    payload = [serialize_remote_site_cache(site) for site in sites]
    total = len(payload)
    return jsonify(
        envelope(
            payload[offset : offset + limit],
            count=total,
            limit=limit,
            offset=offset,
            sort="name_ascending",
        )
    )


@require_api_scope("read:aggregation")
def api_v1_aggregation_site_detail(site_id):
    site = db.session.get(RemoteSite, site_id)
    if site is None:
        return json_api_error("Remote site not found", status_code=404, code="not_found")
    return jsonify(envelope(serialize_remote_site_cache(site)))


@require_api_scope("read:search")
def api_v1_search():
    query_text = (request.args.get("q") or "").strip()
    if not query_text:
        return json_api_error("Missing q", status_code=400, code="bad_request")
    limit, offset = parse_limit_offset(request, default_limit=25, max_limit=100)
    requested_types = {
        value.strip().lower()
        for value in (request.args.get("types") or "").split(",")
        if value.strip()
    }
    allowed_types = {"suppliers", "purchases", "lots", "runs"}
    if requested_types and not requested_types.issubset(allowed_types):
        return json_api_error("Invalid types filter", status_code=400, code="bad_request")
    if not requested_types:
        requested_types = allowed_types

    results = []

    if "suppliers" in requested_types:
        suppliers = Supplier.query.filter(Supplier.name.ilike(f"%{query_text}%")).order_by(Supplier.name.asc()).limit(limit).all()
        for supplier in suppliers:
            results.append(
                serialize_search_result(
                    entity_type="supplier",
                    entity_id=supplier.id,
                    label=supplier.name,
                    subtitle=supplier.location or supplier.contact_name,
                    match_fields=["name"],
                    context={"is_active": bool(supplier.is_active)},
                )
            )

    if "purchases" in requested_types:
        purchases = Purchase.query.filter(
            Purchase.deleted_at.is_(None),
            or_(
                Purchase.batch_id.ilike(f"%{query_text}%"),
                Purchase.notes.ilike(f"%{query_text}%"),
            ),
        ).order_by(Purchase.purchase_date.desc(), Purchase.id.desc()).limit(limit).all()
        for purchase in purchases:
            results.append(
                serialize_search_result(
                    entity_type="purchase",
                    entity_id=purchase.id,
                    label=purchase.batch_id or purchase.id,
                    subtitle=purchase.supplier.name if purchase.supplier else None,
                    match_fields=[
                        field for field, value in (
                            ("batch_id", purchase.batch_id),
                            ("notes", purchase.notes),
                        ) if value and query_text.lower() in value.lower()
                    ],
                    context={
                        "status": purchase.status,
                        "purchase_date": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
                    },
                )
            )

    if "lots" in requested_types:
        lots = PurchaseLot.query.join(Purchase).filter(
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
            or_(
                PurchaseLot.tracking_id == query_text,
                PurchaseLot.strain_name.ilike(f"%{query_text}%"),
                Purchase.batch_id.ilike(f"%{query_text}%"),
            ),
        ).order_by(Purchase.purchase_date.desc(), PurchaseLot.id.desc()).limit(limit).all()
        for lot in lots:
            match_fields = []
            if (lot.tracking_id or "") == query_text:
                match_fields.append("tracking_id")
            if query_text.lower() in (lot.strain_name or "").lower():
                match_fields.append("strain_name")
            if lot.purchase and query_text.lower() in (lot.purchase.batch_id or "").lower():
                match_fields.append("batch_id")
            results.append(
                serialize_search_result(
                    entity_type="lot",
                    entity_id=lot.id,
                    label=lot.display_label,
                    subtitle=lot.purchase.batch_id if lot.purchase else None,
                    match_fields=match_fields,
                    context={
                        "tracking_id": lot.tracking_id,
                        "remaining_weight_lbs": float(lot.remaining_weight_lbs or 0),
                    },
                )
            )

    if "runs" in requested_types:
        runs_query = Run.query.filter(Run.deleted_at.is_(None))
        if query_text.isdigit():
            runs_query = runs_query.filter(Run.reactor_number == int(query_text))
        else:
            runs_query = runs_query.filter(Run.notes.ilike(f"%{query_text}%"))
        runs = runs_query.order_by(Run.run_date.desc(), Run.id.desc()).limit(limit).all()
        for run in runs:
            match_fields = ["reactor_number"] if query_text.isdigit() else ["notes"]
            results.append(
                serialize_search_result(
                    entity_type="run",
                    entity_id=run.id,
                    label=f"Run {run.id[:8]}",
                    subtitle=f"Reactor {run.reactor_number} on {run.run_date.isoformat() if run.run_date else 'unknown date'}",
                    match_fields=match_fields,
                    context={
                        "reactor_number": run.reactor_number,
                        "run_date": run.run_date.isoformat() if run.run_date else None,
                        "bio_in_reactor_lbs": float(run.bio_in_reactor_lbs or 0) if run.bio_in_reactor_lbs is not None else None,
                    },
                )
            )

    total = len(results)
    results = results[offset : offset + limit]
    return jsonify(
        envelope(
            {"query": query_text, "results": results, "count": total},
            count=total,
            limit=limit,
            offset=offset,
            sort="relevance",
            filters={"q": query_text, "types": sorted(requested_types)},
        )
    )


@require_api_scope("read:tools")
def api_v1_tool_inventory_snapshot():
    supplier_id = (request.args.get("supplier_id") or "").strip() or None
    strain = (request.args.get("strain") or "").strip() or None
    lots = build_inventory_on_hand_query(supplier_id=supplier_id, strain=strain).limit(25).all()
    total_on_hand = float(sum(float(lot.remaining_weight_lbs or 0) for lot in lots))
    supplier_names = sorted({lot.purchase.supplier.name for lot in lots if lot.purchase and lot.purchase.supplier})
    strain_names = sorted({lot.strain_name for lot in lots if lot.strain_name})
    payload = {
        "filters": {
            "supplier_id": supplier_id,
            "strain": strain,
        },
        "summary": {
            "open_lot_count": len(lots),
            "total_on_hand_lbs": total_on_hand,
            "supplier_count": len(supplier_names),
            "strain_count": len(strain_names),
        },
        "lots": [serialize_inventory_lot(lot) for lot in lots],
    }
    return jsonify(envelope(payload))


@require_api_scope("read:tools")
def api_v1_tool_open_lots():
    supplier_id = (request.args.get("supplier_id") or "").strip() or None
    strain = (request.args.get("strain") or "").strip() or None
    min_remaining_lbs = None
    if (request.args.get("min_remaining_lbs") or "").strip():
        try:
            min_remaining_lbs = float(request.args.get("min_remaining_lbs"))
        except ValueError:
            return json_api_error("Invalid min_remaining_lbs", status_code=400, code="bad_request")
    limit, offset = parse_limit_offset(request, default_limit=25, max_limit=100)
    query = build_lots_query(
        purchase_id=None,
        supplier_id=supplier_id,
        strain=strain,
        tracking_id=None,
        open_only=True,
        include_archived=False,
    )
    if min_remaining_lbs is not None:
        query = query.filter(PurchaseLot.remaining_weight_lbs >= min_remaining_lbs)
    total = query.count()
    lots = query.offset(offset).limit(limit).all()
    payload = {
        "filters": {
            "supplier_id": supplier_id,
            "strain": strain,
            "min_remaining_lbs": min_remaining_lbs,
        },
        "results": [serialize_lot_summary(lot) for lot in lots],
    }
    return jsonify(envelope(payload, count=total, limit=limit, offset=offset))


@require_api_scope("read:tools")
def api_v1_tool_journey_resolve():
    entity_type = (request.args.get("entity_type") or "").strip().lower()
    entity_id = (request.args.get("entity_id") or "").strip()
    if entity_type not in {"purchase", "lot", "run", "material_lot"} or not entity_id:
        return json_api_error("entity_type must be purchase, lot, run, or material_lot and entity_id is required", status_code=400, code="bad_request")

    if entity_type == "purchase":
        purchase = db.session.get(Purchase, entity_id)
        if not purchase:
            return json_api_error("Purchase not found", status_code=404, code="not_found")
        payload = {
            "entity_type": "purchase",
            "entity_id": entity_id,
            "journey_endpoint": f"/api/v1/purchases/{entity_id}/journey",
            "journey": build_purchase_journey_payload(purchase),
        }
        return jsonify(envelope(payload))
    if entity_type == "lot":
        lot = db.session.get(PurchaseLot, entity_id)
        if not lot:
            return json_api_error("Lot not found", status_code=404, code="not_found")
        payload = {
            "entity_type": "lot",
            "entity_id": entity_id,
            "journey_endpoint": f"/api/v1/lots/{entity_id}/journey",
            "journey": build_lot_journey_payload(lot),
        }
        return jsonify(envelope(payload))

    if entity_type == "material_lot":
        material_lot = db.session.get(MaterialLot, entity_id)
        if not material_lot:
            return json_api_error("Material lot not found", status_code=404, code="not_found")
        payload = {
            "entity_type": "material_lot",
            "entity_id": entity_id,
            "journey_endpoint": f"/api/v1/material-lots/{entity_id}/journey",
            "journey": build_material_lot_journey_payload(_require_root(), material_lot),
        }
        return jsonify(envelope(payload))

    run = db.session.get(Run, entity_id)
    if not run:
        return json_api_error("Run not found", status_code=404, code="not_found")
    payload = {
        "entity_type": "run",
        "entity_id": entity_id,
        "journey_endpoint": f"/api/v1/runs/{entity_id}/journey",
        "journey": build_run_journey_payload(run),
    }
    return jsonify(envelope(payload))


@require_api_scope("read:tools")
def api_v1_tool_reconciliation_overview():
    root = _require_root()
    built, error = _build_slack_import_items(root)
    if error:
        return error
    items, bucket_counts = built
    exception_payload = _exceptions_summary_payload(root)
    blocked_items = [item for item in items if item.get("triage_bucket") == "blocked"][:10]
    manual_items = [item for item in items if item.get("triage_bucket") == "needs_manual_match"][:10]
    payload = {
        "slack_imports": {
            "total_messages": len(items),
            "bucket_counts": bucket_counts,
            "blocked_items": blocked_items,
            "needs_manual_match_items": manual_items,
        },
        "exceptions": exception_payload,
        "material_genealogy": {
            "open_issue_count": root.MaterialReconciliationIssue.query.filter_by(status="open").count(),
            "open_issues": [
                serialize_material_reconciliation_issue(issue)
                for issue in first_open_reconciliation_issues(root, limit=10)
            ],
        },
    }
    return jsonify(envelope(payload))


def _exceptions_summary_payload(root):
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
    return {
        "total_exceptions": purchase_count + inventory_count,
        "category_counts": {
            "purchases": purchase_count,
            "inventory": inventory_count,
        },
        "label_counts": dict(sorted(by_label.items(), key=lambda item: (-item[1], item[0]))),
    }


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


def _dashboard_period_start(root, period: str):
    if period == "today":
        return root.date.today()
    if period == "7":
        return root.date.today() - root.timedelta(days=7)
    if period == "90":
        return root.date.today() - root.timedelta(days=90)
    if period == "all":
        return root.date(2020, 1, 1)
    return root.date.today() - root.timedelta(days=30)


def _dashboard_summary_payload(root, period: str):
    start_date = _dashboard_period_start(root, period)
    exclude_unpriced = root._exclude_unpriced_batches_enabled()
    runs_q = root.Run.query.filter(root.Run.deleted_at.is_(None), root.Run.run_date >= start_date)
    if exclude_unpriced:
        runs_q = runs_q.filter(root._priced_run_filter())
    runs = runs_q.all()

    kpi_actuals = {}
    if runs:
        yields = [r.overall_yield_pct for r in runs if r.overall_yield_pct]
        thca_yields = [r.thca_yield_pct for r in runs if r.thca_yield_pct]
        hte_yields = [r.hte_yield_pct for r in runs if r.hte_yield_pct]
        costs = [r.cost_per_gram_combined for r in runs if r.cost_per_gram_combined]
        costs_thca = [r.cost_per_gram_thca for r in runs if r.cost_per_gram_thca is not None]
        costs_hte = [r.cost_per_gram_hte for r in runs if r.cost_per_gram_hte is not None]
        total_lbs = sum(r.bio_in_reactor_lbs or 0 for r in runs)
        kpi_actuals["thca_yield_pct"] = sum(thca_yields) / len(thca_yields) if thca_yields else None
        kpi_actuals["hte_yield_pct"] = sum(hte_yields) / len(hte_yields) if hte_yields else None
        kpi_actuals["overall_yield_pct"] = sum(yields) / len(yields) if yields else None
        kpi_actuals["cost_per_gram_combined"] = sum(costs) / len(costs) if costs else None
        kpi_actuals["cost_per_gram_thca"] = sum(costs_thca) / len(costs_thca) if costs_thca else None
        kpi_actuals["cost_per_gram_hte"] = sum(costs_hte) / len(costs_hte) if costs_hte else None
        days_in_period = max((root.date.today() - start_date).days, 1)
        weeks = max(days_in_period / 7, 1)
        kpi_actuals["weekly_throughput"] = total_lbs / weeks
        daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
        on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
            root.Purchase.purchase_approved_at.isnot(None),
        ).scalar() or 0
        kpi_actuals["days_of_supply"] = on_hand / daily_target if daily_target > 0 else 0
        purchase_ids = root.db.session.query(root.Purchase.id).join(
            root.PurchaseLot, root.PurchaseLot.purchase_id == root.Purchase.id
        ).join(
            RunInput, RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Run, root.Run.id == RunInput.run_id
        ).filter(
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
            root.Run.run_date >= start_date,
        ).distinct().all()
        purchase_ids = [pid for (pid,) in purchase_ids]
        purchases_in_period = root.Purchase.query.filter(root.Purchase.id.in_(purchase_ids)).all() if purchase_ids else []
        potency_costs = []
        for purchase in purchases_in_period:
            potency = purchase.tested_potency_pct or purchase.stated_potency_pct
            if purchase.price_per_lb and potency and potency > 0:
                potency_costs.append(purchase.price_per_lb / potency)
        kpi_actuals["cost_per_potency_point"] = sum(potency_costs) / len(potency_costs) if potency_costs else None

    kpis = root.KpiTarget.query.all()
    kpi_cards = []
    for kpi in kpis:
        actual = kpi_actuals.get(kpi.kpi_name)
        kpi_cards.append({
            "name": kpi.display_name,
            "kpi_name": kpi.kpi_name,
            "target": float(kpi.target_value or 0),
            "actual": float(actual or 0) if actual is not None else None,
            "color": kpi.evaluate(actual),
            "unit": kpi.unit or "",
            "direction": kpi.direction,
        })

    total_runs = len(runs)
    total_lbs = float(sum(r.bio_in_reactor_lbs or 0 for r in runs))
    total_dry_output = float(sum((r.dry_hte_g or 0) + (r.dry_thca_g or 0) for r in runs))
    on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
        root.PurchaseLot.remaining_weight_lbs > 0,
        root.PurchaseLot.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        root.Purchase.purchase_approved_at.isnot(None),
    ).scalar() or 0

    week_start = root.date.today() - root.timedelta(days=root.date.today().weekday())
    wtd_runs_q = root.Run.query.filter(
        root.Run.deleted_at.is_(None),
        root.Run.run_date >= week_start,
        root.Run.run_date <= root.date.today(),
    )
    if exclude_unpriced:
        wtd_runs_q = wtd_runs_q.filter(root._priced_run_filter())
    wtd_runs = wtd_runs_q.all()
    wtd_lbs = float(sum(r.bio_in_reactor_lbs or 0 for r in wtd_runs))
    wtd_dry_thca = float(sum(r.dry_thca_g or 0 for r in wtd_runs))
    wtd_dry_hte = float(sum(r.dry_hte_g or 0 for r in wtd_runs))

    current_month_start = root.date.today().replace(day=1)
    prev_month_end = current_month_start - root.timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    mom_query = root.db.session.query(
        root.Supplier.id.label("supplier_id"),
        root.Supplier.name.label("supplier_name"),
        root.func.avg(root.Run.overall_yield_pct).label("avg_yield"),
    ).join(
        root.Purchase, root.Purchase.supplier_id == root.Supplier.id
    ).join(
        root.PurchaseLot, root.PurchaseLot.purchase_id == root.Purchase.id
    ).join(
        root.RunInput, root.RunInput.lot_id == root.PurchaseLot.id
    ).join(
        root.Run, root.Run.id == root.RunInput.run_id
    ).filter(
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
        root.Run.is_rollover == False,
        root.Run.run_date >= current_month_start,
        root.Run.overall_yield_pct.isnot(None),
    )
    if exclude_unpriced:
        mom_query = mom_query.filter(root._priced_run_filter())
    mom_rows = mom_query.group_by(root.Supplier.id, root.Supplier.name).all()
    best_supplier_mom = None
    if mom_rows:
        best = max(mom_rows, key=lambda row: float(row.avg_yield or 0))
        prev = root.db.session.query(root.func.avg(root.Run.overall_yield_pct)).join(
            root.RunInput, root.Run.id == root.RunInput.run_id
        ).join(
            root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
        ).join(
            root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
        ).filter(
            root.Run.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.deleted_at.is_(None),
            root.Run.is_rollover == False,
            root.Purchase.supplier_id == best.supplier_id,
            root.Run.run_date >= prev_month_start,
            root.Run.run_date <= prev_month_end,
        )
        if exclude_unpriced:
            prev = prev.filter(root._priced_run_filter())
        prev_avg = prev.scalar()
        best_supplier_mom = {
            "name": best.supplier_name,
            "current": float(best.avg_yield or 0),
            "previous": float(prev_avg or 0) if prev_avg is not None else None,
            "pct_change": (((float(best.avg_yield or 0) - float(prev_avg or 0)) / float(prev_avg or 0)) * 100.0)
            if prev_avg not in (None, 0)
            else None,
        }

    fin = _weekly_finance_snapshot(root)
    return {
        "period": period,
        "exclude_unpriced": bool(exclude_unpriced),
        "totals": {
            "total_runs": total_runs,
            "total_lbs": total_lbs,
            "total_dry_output_g": total_dry_output,
            "on_hand_lbs": float(on_hand or 0),
        },
        "week_to_date": {
            "week_start": week_start.isoformat(),
            "week_end": root.date.today().isoformat(),
            "lbs_processed": wtd_lbs,
            "dry_thca_g": wtd_dry_thca,
            "dry_hte_g": wtd_dry_hte,
        },
        "weekly_finance": {
            "week_start": fin["week_start"].isoformat(),
            "week_end": fin["week_end"].isoformat(),
            "weekly_dollar_budget": fin["weekly_dollar_budget"],
            "week_commitment_dollars": fin["week_commitment_dollars"],
            "week_purchase_dollars": fin["week_purchase_dollars"],
        },
        "best_supplier_mom": best_supplier_mom,
        "kpis": kpi_cards,
    }


@require_api_scope("read:dashboard")
def api_v1_dashboard_summary():
    root = _require_root()
    period = (request.args.get("period") or "30").strip()
    if period not in {"today", "7", "30", "90", "all"}:
        return json_api_error("Invalid period", status_code=400, code="bad_request")
    return jsonify(envelope(_dashboard_summary_payload(root, period)))


@require_api_scope("read:inventory")
def api_v1_material_costs_summary():
    root = _require_root()
    return jsonify(envelope(build_material_cost_summary_payload(root)))


@require_api_scope("read:inventory")
def api_v1_material_genealogy_summary():
    root = _require_root()
    return jsonify(envelope(build_material_reporting_payload(root)))


@require_api_scope("read:aggregation")
def api_v1_aggregation_summary():
    root = _require_root()
    period = (request.args.get("period") or "30").strip()
    if period not in {"today", "7", "30", "90", "all"}:
        return json_api_error("Invalid period", status_code=400, code="bad_request")
    slack_payload, error = _slack_imports_summary_payload(root)
    if error:
        return error
    payload = build_aggregation_summary(
        get_site_identity(),
        local_dashboard=_dashboard_summary_payload(root, period),
        local_inventory=_inventory_summary_payload(root, supplier_id=None, strain=None),
        local_exceptions=_exceptions_summary_payload(root),
        local_slack=slack_payload,
    )
    payload["period"] = period
    return jsonify(envelope(payload))


def _aggregation_site_stub(*, source: str, site_code: str | None, site_name: str | None, site_region: str | None, site_environment: str | None, **_ignored):
    return {
        "source": source,
        "site_code": site_code,
        "site_name": site_name,
        "site_region": site_region,
        "site_environment": site_environment,
    }


@require_api_scope("read:aggregation")
def api_v1_aggregation_suppliers():
    root = _require_root()
    limit, offset = parse_limit_offset(request, default_limit=100, max_limit=500)
    query_text = (request.args.get("q") or "").strip().lower()
    local_site = get_site_identity()
    rows = []
    for supplier in Supplier.query.order_by(Supplier.name.asc(), Supplier.id.asc()).all():
        payload = _supplier_performance_payload(root, supplier)
        if query_text and query_text not in ((payload.get("supplier") or {}).get("name") or "").lower():
            continue
        payload["site"] = _aggregation_site_stub(source="local", **local_site)
        rows.append(payload)

    for remote_site in RemoteSite.query.filter(RemoteSite.is_active.is_(True)).order_by(RemoteSite.name.asc()).all():
        cached_rows = remote_site.payload("last_suppliers_payload_json") or []
        for payload in cached_rows:
            supplier_name = ((payload.get("supplier") or {}).get("name") or "").lower()
            if query_text and query_text not in supplier_name:
                continue
            item = dict(payload)
            item["site"] = _aggregation_site_stub(
                source="remote_cache",
                site_code=remote_site.site_code,
                site_name=remote_site.site_name or remote_site.name,
                site_region=remote_site.site_region,
                site_environment=remote_site.site_environment,
            )
            rows.append(item)

    total = len(rows)
    return jsonify(
        envelope(
            rows[offset : offset + limit],
            count=total,
            limit=limit,
            offset=offset,
            sort="supplier_name_ascending",
            filters={"q": query_text or None},
        )
    )


@require_api_scope("read:aggregation")
def api_v1_aggregation_strains():
    root = _require_root()
    limit, offset = parse_limit_offset(request, default_limit=100, max_limit=500)
    query_text = (request.args.get("q") or "").strip().lower()
    supplier_filter = (request.args.get("supplier_name") or "").strip().lower()
    local_site = get_site_identity()

    local_view = root.app.test_request_context(
        "/internal/aggregation/strains",
        query_string={"view": "all", "supplier_id": "", "strain": query_text},
    )
    rows = []
    with local_view:
        local_response = api_v1_strains.__wrapped__()
        local_payload = local_response.get_json()["data"]
    for payload in local_payload:
        supplier_name = (payload.get("supplier_name") or "").lower()
        if supplier_filter and supplier_filter not in supplier_name:
            continue
        item = dict(payload)
        item["site"] = _aggregation_site_stub(source="local", **local_site)
        rows.append(item)

    for remote_site in RemoteSite.query.filter(RemoteSite.is_active.is_(True)).order_by(RemoteSite.name.asc()).all():
        cached_rows = remote_site.payload("last_strains_payload_json") or []
        for payload in cached_rows:
            strain_name = (payload.get("strain_name") or "").lower()
            supplier_name = (payload.get("supplier_name") or "").lower()
            if query_text and query_text not in strain_name:
                continue
            if supplier_filter and supplier_filter not in supplier_name:
                continue
            item = dict(payload)
            item["site"] = _aggregation_site_stub(
                source="remote_cache",
                site_code=remote_site.site_code,
                site_name=remote_site.site_name or remote_site.name,
                site_region=remote_site.site_region,
                site_environment=remote_site.site_environment,
            )
            rows.append(item)

    total = len(rows)
    return jsonify(
        envelope(
            rows[offset : offset + limit],
            count=total,
            limit=limit,
            offset=offset,
            sort="avg_yield_desc",
            filters={"q": query_text or None, "supplier_name": supplier_filter or None},
        )
    )


@require_api_scope("read:dashboard")
def api_v1_departments():
    data = []
    for slug, cfg in DEPARTMENT_PAGES.items():
        data.append(
            {
                "slug": slug,
                "title": cfg.get("title"),
                "intro": cfg.get("intro"),
                "link_count": len(cfg.get("links", [])),
            }
        )
    return jsonify(envelope(data))


@require_api_scope("read:dashboard")
def api_v1_department_detail(slug):
    root = _require_root()
    cfg = DEPARTMENT_PAGES.get(slug)
    if not cfg:
        return json_api_error("Department not found", status_code=404, code="not_found")
    sections = []
    for section in _department_stat_sections(root, slug):
        rows = [{"label": label, "value": value} for label, value in section.get("rows", [])]
        sections.append({"title": section.get("title"), "rows": rows})
    payload = {
        "slug": slug,
        "title": cfg.get("title"),
        "intro": cfg.get("intro"),
        "links": cfg.get("links", []),
        "sections": sections,
    }
    return jsonify(envelope(payload))


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
    return jsonify(
        envelope(
            [serialize_purchase_summary(purchase) for purchase in purchases],
            count=total,
            limit=limit,
            offset=offset,
            sort="purchase_date_desc",
            filters={
                "status": (request.args.get("status") or "").strip() or None,
                "supplier_id": (request.args.get("supplier_id") or "").strip() or None,
                "approved": approved,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "include_archived": request.args.get("include_archived") == "1",
            },
        )
    )


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
    return jsonify(
        envelope(
            [serialize_lot_summary(lot) for lot in lots],
            count=total,
            limit=limit,
            offset=offset,
            sort="purchase_date_desc",
            filters={
                "purchase_id": (request.args.get("purchase_id") or "").strip() or None,
                "supplier_id": (request.args.get("supplier_id") or "").strip() or None,
                "strain": (request.args.get("strain") or "").strip() or None,
                "tracking_id": (request.args.get("tracking_id") or "").strip() or None,
                "open_only": request.args.get("open_only") == "1",
                "include_archived": request.args.get("include_archived") == "1",
            },
        )
    )


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


@require_api_scope("read:journey")
def api_v1_lot_journey(lot_id):
    include_archived = request.args.get("include_archived") == "1"
    lot = db.session.get(PurchaseLot, lot_id)
    if not lot:
        return json_api_error("Lot not found", status_code=404, code="not_found")
    if not include_archived:
        if lot.deleted_at is not None or lot.purchase is None or lot.purchase.deleted_at is not None:
            return json_api_error(
                "Lot is archived. Set include_archived=1 to view its journey.",
                status_code=404,
                code="not_found",
            )
    payload = build_lot_journey_payload(lot, include_archived=include_archived)
    return jsonify(envelope(payload))


@require_api_scope("read:journey")
def api_v1_material_lot_detail(lot_id):
    material_lot = db.session.get(MaterialLot, lot_id)
    if not material_lot:
        return json_api_error("Material lot not found", status_code=404, code="not_found")
    return jsonify(envelope(build_material_lot_detail_payload(_require_root(), material_lot)))


@require_api_scope("read:journey")
def api_v1_material_lot_journey(lot_id):
    material_lot = db.session.get(MaterialLot, lot_id)
    if not material_lot:
        return json_api_error("Material lot not found", status_code=404, code="not_found")
    return jsonify(envelope(build_material_lot_journey_payload(_require_root(), material_lot)))


@require_api_scope("read:journey")
def api_v1_material_lot_ancestry(lot_id):
    material_lot = db.session.get(MaterialLot, lot_id)
    if not material_lot:
        return json_api_error("Material lot not found", status_code=404, code="not_found")
    return jsonify(envelope(build_material_lot_ancestry_payload(_require_root(), material_lot)))


@require_api_scope("read:journey")
def api_v1_material_lot_descendants(lot_id):
    material_lot = db.session.get(MaterialLot, lot_id)
    if not material_lot:
        return json_api_error("Material lot not found", status_code=404, code="not_found")
    return jsonify(envelope(build_material_lot_descendants_payload(_require_root(), material_lot)))


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
    return jsonify(
        envelope(
            [serialize_run_summary(run) for run in runs],
            count=total,
            limit=limit,
            offset=offset,
            sort="run_date_desc",
            filters={
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "reactor_number": reactor_number,
                "supplier_id": (request.args.get("supplier_id") or "").strip() or None,
                "strain": (request.args.get("strain") or "").strip() or None,
                "slack_linked": slack_linked,
                "include_archived": request.args.get("include_archived") == "1",
            },
        )
    )


@require_api_scope("read:runs")
def api_v1_run_detail(run_id):
    include_archived = request.args.get("include_archived") == "1"
    run = db.session.get(Run, run_id)
    if not run:
        return json_api_error("Run not found", status_code=404, code="not_found")
    if run.deleted_at is not None and not include_archived:
        return json_api_error("Run not found", status_code=404, code="not_found")
    return jsonify(envelope(serialize_run_detail(run)))


@require_api_scope("read:journey")
def api_v1_run_journey(run_id):
    include_archived = request.args.get("include_archived") == "1"
    run = db.session.get(Run, run_id)
    if not run:
        return json_api_error("Run not found", status_code=404, code="not_found")
    if run.deleted_at is not None and not include_archived:
        return json_api_error(
            "Run is archived. Set include_archived=1 to view its journey.",
            status_code=404,
            code="not_found",
        )
    payload = build_run_journey_payload(run, include_archived=include_archived)
    return jsonify(envelope(payload))


def _supplier_performance_payload(root, supplier):
    exclude_unpriced = root._exclude_unpriced_batches_enabled()
    runs_q = root.db.session.query(
        root.func.avg(root.Run.overall_yield_pct),
        root.func.avg(root.Run.thca_yield_pct),
        root.func.avg(root.Run.hte_yield_pct),
        root.func.avg(root.Run.cost_per_gram_combined),
        root.func.count(root.Run.id),
        root.func.sum(root.Run.bio_in_reactor_lbs),
        root.func.sum(root.Run.dry_thca_g),
        root.func.sum(root.Run.dry_hte_g),
    ).join(
        root.RunInput, root.Run.id == root.RunInput.run_id
    ).join(
        root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
    ).join(
        root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
    ).filter(
        root.Purchase.supplier_id == supplier.id,
        root.Run.is_rollover == False,
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
    )
    if exclude_unpriced:
        runs_q = runs_q.filter(root._priced_run_filter())
    all_time = runs_q.first()
    ninety = runs_q.filter(root.Run.run_date >= root.date.today() - root.timedelta(days=90)).first()
    last_run_q = root.db.session.query(root.Run).join(
        root.RunInput, root.Run.id == root.RunInput.run_id
    ).join(
        root.PurchaseLot, root.RunInput.lot_id == root.PurchaseLot.id
    ).join(
        root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
    ).filter(
        root.Purchase.supplier_id == supplier.id,
        root.Run.is_rollover == False,
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
    )
    if exclude_unpriced:
        last_run_q = last_run_q.filter(root._priced_run_filter())
    last_run = last_run_q.order_by(root.Run.run_date.desc()).first()
    return serialize_supplier_performance_row(
        supplier=supplier,
        profile_incomplete=bool(supplier_incomplete_profile_fields(root, supplier)),
        all_time={
            "yield": float(all_time[0] or 0) if all_time[0] is not None else None,
            "thca": float(all_time[1] or 0) if all_time[1] is not None else None,
            "hte": float(all_time[2] or 0) if all_time[2] is not None else None,
            "cpg": float(all_time[3] or 0) if all_time[3] is not None else None,
            "runs": int(all_time[4] or 0),
            "lbs": float(all_time[5] or 0),
            "total_thca": float(all_time[6] or 0),
            "total_hte": float(all_time[7] or 0),
        },
        ninety_day={
            "yield": float(ninety[0] or 0) if ninety[0] is not None else None,
            "thca": float(ninety[1] or 0) if ninety[1] is not None else None,
            "hte": float(ninety[2] or 0) if ninety[2] is not None else None,
            "cpg": float(ninety[3] or 0) if ninety[3] is not None else None,
            "runs": int(ninety[4] or 0),
        },
        last_batch={
            "yield": float(last_run.overall_yield_pct or 0) if last_run and last_run.overall_yield_pct is not None else None,
            "thca": float(last_run.thca_yield_pct or 0) if last_run and last_run.thca_yield_pct is not None else None,
            "hte": float(last_run.hte_yield_pct or 0) if last_run and last_run.hte_yield_pct is not None else None,
            "cpg": float(last_run.cost_per_gram_combined or 0) if last_run and last_run.cost_per_gram_combined is not None else None,
            "date": last_run.run_date.isoformat() if last_run and last_run.run_date else None,
        },
    )


@require_api_scope("read:suppliers")
def api_v1_suppliers():
    root = _require_root()
    limit, offset = parse_limit_offset(request)
    q = Supplier.query
    active_param = (request.args.get("active") or "").strip().lower()
    if active_param in {"1", "true", "yes"}:
        q = q.filter(Supplier.is_active.is_(True))
    elif active_param in {"0", "false", "no"}:
        q = q.filter(Supplier.is_active.is_(False))
    if (request.args.get("q") or "").strip():
        term = request.args.get("q").strip()
        q = q.filter(Supplier.name.ilike(f"%{term}%"))
    q = q.order_by(Supplier.name.asc(), Supplier.id.asc())
    total = q.count()
    suppliers = q.offset(offset).limit(limit).all()
    return jsonify(
        envelope(
            [_supplier_performance_payload(root, supplier) for supplier in suppliers],
            count=total,
            limit=limit,
            offset=offset,
            sort="name_ascending",
            filters={
                "active": active_param or None,
                "q": (request.args.get("q") or "").strip() or None,
            },
        )
    )


@require_api_scope("read:suppliers")
def api_v1_supplier_detail(supplier_id):
    root = _require_root()
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        return json_api_error("Supplier not found", status_code=404, code="not_found")
    payload = _supplier_performance_payload(root, supplier)
    payload["contact_name"] = supplier.contact_name
    payload["contact_phone"] = supplier.contact_phone
    payload["contact_email"] = supplier.contact_email
    payload["location"] = supplier.location
    payload["notes"] = supplier.notes
    payload["is_active"] = bool(supplier.is_active)
    return jsonify(envelope(payload))


@require_api_scope("read:strains")
def api_v1_strains():
    root = _require_root()
    limit, offset = parse_limit_offset(request)
    view = (request.args.get("view") or "all").strip().lower()
    if view not in {"all", "90"}:
        return json_api_error("Invalid view", status_code=400, code="bad_request")
    query = root.db.session.query(
        root.PurchaseLot.strain_name,
        root.Supplier.name.label("supplier_name"),
        root.func.avg(root.Run.overall_yield_pct).label("avg_yield"),
        root.func.avg(root.Run.thca_yield_pct).label("avg_thca"),
        root.func.avg(root.Run.hte_yield_pct).label("avg_hte"),
        root.func.avg(root.Run.cost_per_gram_combined).label("avg_cpg"),
        root.func.count(root.Run.id).label("run_count"),
        root.func.sum(root.Run.bio_in_reactor_lbs).label("total_lbs"),
        root.func.sum(root.Run.dry_thca_g).label("total_thca_g"),
        root.func.sum(root.Run.dry_hte_g).label("total_hte_g"),
    ).join(
        root.RunInput, root.PurchaseLot.id == root.RunInput.lot_id
    ).join(
        root.Run, root.RunInput.run_id == root.Run.id
    ).join(
        root.Purchase, root.PurchaseLot.purchase_id == root.Purchase.id
    ).join(
        root.Supplier, root.Purchase.supplier_id == root.Supplier.id
    ).filter(
        root.Run.is_rollover == False,
        root.Run.deleted_at.is_(None),
        root.Purchase.deleted_at.is_(None),
        root.PurchaseLot.deleted_at.is_(None),
    )
    if root._exclude_unpriced_batches_enabled():
        query = query.filter(root._priced_run_filter())
    if (request.args.get("supplier_id") or "").strip():
        query = query.filter(root.Supplier.id == request.args.get("supplier_id").strip())
    if (request.args.get("strain") or "").strip():
        query = query.filter(root.PurchaseLot.strain_name.ilike(f"%{request.args.get('strain').strip()}%"))
    if view == "90":
        query = query.filter(root.Run.run_date >= root.date.today() - root.timedelta(days=90))
    query = query.group_by(
        root.PurchaseLot.strain_name, root.Supplier.name
    ).order_by(root.desc("avg_yield"))
    total = query.count()
    results = query.offset(offset).limit(limit).all()
    data = [
        serialize_strain_performance_row(
            strain_name=row.strain_name,
            supplier_name=row.supplier_name,
            avg_yield=row.avg_yield,
            avg_thca=row.avg_thca,
            avg_hte=row.avg_hte,
            avg_cpg=row.avg_cpg,
            run_count=row.run_count,
            total_lbs=row.total_lbs,
            total_thca_g=row.total_thca_g,
            total_hte_g=row.total_hte_g,
            view=view,
        )
        for row in results
    ]
    return jsonify(
        envelope(
            data,
            count=total,
            limit=limit,
            offset=offset,
            sort="avg_yield_desc",
            filters={
                "view": view,
                "supplier_id": (request.args.get("supplier_id") or "").strip() or None,
                "strain": (request.args.get("strain") or "").strip() or None,
            },
        )
    )


@require_api_scope("read:inventory")
def api_v1_inventory_on_hand():
    limit, offset = parse_limit_offset(request)
    query = build_inventory_on_hand_query(
        supplier_id=(request.args.get("supplier_id") or "").strip() or None,
        strain=(request.args.get("strain") or "").strip() or None,
    )
    total = query.count()
    lots = query.offset(offset).limit(limit).all()
    return jsonify(
        envelope(
            [serialize_inventory_lot(lot) for lot in lots],
            count=total,
            limit=limit,
            offset=offset,
            sort="purchase_date_desc",
            filters={
                "supplier_id": (request.args.get("supplier_id") or "").strip() or None,
                "strain": (request.args.get("strain") or "").strip() or None,
            },
        )
    )


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
    return jsonify(
        envelope(
            items[offset : offset + limit],
            count=total,
            limit=limit,
            offset=offset,
            sort="message_ts_desc",
            filters={
                "start_date": request.args.get("start_date") or None,
                "end_date": request.args.get("end_date") or None,
                "promotion": _norm_promo(request.args.get("promotion")),
                "coverage": _norm_cov(request.args.get("coverage")),
                "kind_filter": (request.args.get("kind_filter") or "all").strip().lower(),
                "text_filter": (request.args.get("text_filter") or "").strip() or None,
                "text_op": (request.args.get("text_op") or "contains").strip().lower(),
                "include_hidden": request.args.get("include_hidden") == "1",
                "channel_id": (request.args.get("channel_id") or "").strip() or None,
            },
        )
    )


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
    return jsonify(
        envelope(
            items[offset : offset + limit],
            count=total,
            limit=limit,
            offset=offset,
            sort="category_then_label",
            filters={"category": category},
        )
    )


@require_api_scope("read:scales")
def api_v1_scale_devices():
    limit, offset = parse_limit_offset(request)
    devices = ScaleDevice.query.order_by(ScaleDevice.created_at.desc()).all()
    total = len(devices)
    return jsonify(
        envelope(
            [serialize_scale_device(device) for device in devices[offset : offset + limit]],
            count=total,
            limit=limit,
            offset=offset,
            sort="created_at_desc",
        )
    )


@require_api_scope("read:scales")
def api_v1_weight_captures():
    limit, offset = parse_limit_offset(request)
    capture_type = (request.args.get("capture_type") or "").strip().lower()
    source_mode = (request.args.get("source_mode") or "").strip().lower()
    device_id = (request.args.get("device_id") or "").strip()
    query = WeightCapture.query
    if capture_type:
        query = query.filter(WeightCapture.capture_type == capture_type)
    if source_mode:
        query = query.filter(WeightCapture.source_mode == source_mode)
    if device_id:
        query = query.filter(WeightCapture.device_id == device_id)
    captures = query.order_by(WeightCapture.created_at.desc()).all()
    total = len(captures)
    return jsonify(
        envelope(
            [serialize_weight_capture(capture) for capture in captures[offset : offset + limit]],
            count=total,
            limit=limit,
            offset=offset,
            sort="created_at_desc",
            filters={"capture_type": capture_type or None, "source_mode": source_mode or None, "device_id": device_id or None},
        )
    )


@require_api_scope("read:scanner")
def api_v1_scan_events():
    limit, offset = parse_limit_offset(request)
    action = (request.args.get("action") or "").strip().lower()
    tracking_id = (request.args.get("tracking_id") or "").strip()
    query = LotScanEvent.query
    if action:
        query = query.filter(LotScanEvent.action == action)
    if tracking_id:
        query = query.filter(LotScanEvent.tracking_id_snapshot == tracking_id)
    events = query.order_by(LotScanEvent.created_at.desc()).all()
    total = len(events)
    return jsonify(
        envelope(
            [serialize_scan_event(event) for event in events[offset : offset + limit]],
            count=total,
            limit=limit,
            offset=offset,
            sort="created_at_desc",
            filters={"action": action or None, "tracking_id": tracking_id or None},
        )
    )


@require_api_scope("read:scanner")
def api_v1_lot_scans(lot_id):
    lot = db.session.get(PurchaseLot, lot_id)
    if lot is None:
        return json_api_error("Lot not found", status_code=404, code="not_found")
    limit, offset = parse_limit_offset(request)
    events = lot.scan_events.order_by(LotScanEvent.created_at.desc()).all()
    total = len(events)
    return jsonify(
        envelope(
            [serialize_scan_event(event) for event in events[offset : offset + limit]],
            count=total,
            limit=limit,
            offset=offset,
            sort="created_at_desc",
            filters={"lot_id": lot_id},
        )
    )


def _inventory_summary_payload(root, *, supplier_id: str | None, strain: str | None):
    lots = build_inventory_on_hand_query(supplier_id=supplier_id, strain=strain).all()
    annotated = [_annotate_inventory_lot(root, lot) for lot in lots]
    total_on_hand = float(sum(float(lot.remaining_weight_lbs or 0) for lot in annotated))
    daily_target = root.SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0.0
    return {
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


@require_api_scope("read:inventory")
def api_v1_inventory_summary():
    root = _require_root()
    supplier_id = (request.args.get("supplier_id") or "").strip() or None
    strain = (request.args.get("strain") or "").strip() or None
    return jsonify(envelope(_inventory_summary_payload(root, supplier_id=supplier_id, strain=strain)))


def _slack_imports_summary_payload(root):
    built, error = _build_slack_import_items(root)
    if error:
        return None, error
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
    return payload, None


@require_api_scope("read:slack_imports")
def api_v1_slack_imports_summary():
    root = _require_root()
    payload, error = _slack_imports_summary_payload(root)
    if error:
        return error
    return jsonify(envelope(payload))


@require_api_scope("read:exceptions")
def api_v1_exceptions_summary():
    root = _require_root()
    return jsonify(envelope(_exceptions_summary_payload(root)))


@require_api_scope("read:scanner")
def api_v1_scanner_summary():
    events = LotScanEvent.query.order_by(LotScanEvent.created_at.desc()).all()
    action_counts: dict[str, int] = {}
    tracking_ids = set()
    for event in events:
        action_counts[event.action] = action_counts.get(event.action, 0) + 1
        if event.tracking_id_snapshot:
            tracking_ids.add(event.tracking_id_snapshot)
    payload = {
        "total_events": len(events),
        "distinct_tracked_lots": len(tracking_ids),
        "action_counts": action_counts,
        "latest_event_at": (
            events[0].created_at.isoformat().replace("+00:00", "Z")
            if events and events[0].created_at
            else None
        ),
    }
    return jsonify(envelope(payload))


@require_api_scope("read:scales")
def api_v1_scales_summary():
    devices = ScaleDevice.query.all()
    captures = WeightCapture.query.order_by(WeightCapture.created_at.desc()).all()
    payload = {
        "device_count": len(devices),
        "active_device_count": sum(1 for device in devices if device.is_active),
        "capture_count": len(captures),
        "device_capture_count": sum(1 for capture in captures if capture.source_mode == "device"),
        "latest_capture_at": (
            captures[0].created_at.isoformat().replace("+00:00", "Z")
            if captures and captures[0].created_at
            else None
        ),
        "capture_type_counts": {},
    }
    for capture in captures:
        payload["capture_type_counts"][capture.capture_type] = payload["capture_type_counts"].get(capture.capture_type, 0) + 1
    return jsonify(envelope(payload))
