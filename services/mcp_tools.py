from __future__ import annotations

from collections.abc import Callable

import app as app_module
from sqlalchemy import or_

from gold_drop.suppliers_module import supplier_incomplete_profile_fields
from models import LotScanEvent, Purchase, PurchaseLot, RemoteSite, Run, Supplier
from services.api_queries import build_inventory_on_hand_query, build_lots_query
from services.api_site import get_site_identity
from services.api_serializers import (
    serialize_inventory_lot,
    serialize_lot_summary,
    serialize_scan_event,
    serialize_search_result,
    serialize_strain_performance_row,
    serialize_supplier_performance_row,
)
from services.purchases_journey import build_lot_journey_payload, build_purchase_journey_payload, build_run_journey_payload
from services.site_aggregation import build_aggregation_summary, serialize_remote_site_cache


class McpToolError(ValueError):
    pass


def _root():
    return app_module


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


def _inventory_snapshot(arguments: dict) -> dict:
    supplier_id = (arguments.get("supplier_id") or "").strip() or None
    strain = (arguments.get("strain") or "").strip() or None
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
    lots = build_inventory_on_hand_query(supplier_id=supplier_id, strain=strain).limit(limit).all()
    total_on_hand = float(sum(float(lot.remaining_weight_lbs or 0) for lot in lots))
    return {
        "filters": {"supplier_id": supplier_id, "strain": strain, "limit": limit},
        "summary": {
            "open_lot_count": len(lots),
            "total_on_hand_lbs": total_on_hand,
        },
        "lots": [serialize_inventory_lot(lot) for lot in lots],
    }


def _open_lots(arguments: dict) -> dict:
    supplier_id = (arguments.get("supplier_id") or "").strip() or None
    strain = (arguments.get("strain") or "").strip() or None
    min_remaining_lbs = arguments.get("min_remaining_lbs")
    if min_remaining_lbs not in (None, ""):
        try:
            min_remaining_lbs = float(min_remaining_lbs)
        except (TypeError, ValueError) as exc:
            raise McpToolError("min_remaining_lbs must be numeric") from exc
    else:
        min_remaining_lbs = None
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
    query = build_lots_query(
        supplier_id=supplier_id,
        strain=strain,
        open_only=True,
        include_archived=False,
    )
    if min_remaining_lbs is not None:
        query = query.filter(PurchaseLot.remaining_weight_lbs >= min_remaining_lbs)
    lots = query.limit(limit).all()
    return {
        "filters": {
            "supplier_id": supplier_id,
            "strain": strain,
            "min_remaining_lbs": min_remaining_lbs,
            "limit": limit,
        },
        "results": [serialize_lot_summary(lot) for lot in lots],
    }


def _journey_resolve(arguments: dict) -> dict:
    entity_type = (arguments.get("entity_type") or "").strip().lower()
    entity_id = (arguments.get("entity_id") or "").strip()
    if entity_type not in {"purchase", "lot", "run"} or not entity_id:
        raise McpToolError("entity_type must be purchase, lot, or run and entity_id is required")
    if entity_type == "purchase":
        purchase = app_module.db.session.get(Purchase, entity_id)
        if not purchase:
            raise McpToolError("Purchase not found")
        return {
            "entity_type": "purchase",
            "entity_id": entity_id,
            "journey": build_purchase_journey_payload(purchase),
        }
    if entity_type == "lot":
        lot = app_module.db.session.get(PurchaseLot, entity_id)
        if not lot:
            raise McpToolError("Lot not found")
        return {
            "entity_type": "lot",
            "entity_id": entity_id,
            "journey": build_lot_journey_payload(lot),
        }
    run = app_module.db.session.get(Run, entity_id)
    if not run:
        raise McpToolError("Run not found")
    return {
        "entity_type": "run",
        "entity_id": entity_id,
        "journey": build_run_journey_payload(run),
    }


def _purchase_journey(arguments: dict) -> dict:
    purchase_id = (arguments.get("purchase_id") or "").strip()
    if not purchase_id:
        raise McpToolError("purchase_id is required")
    purchase = app_module.db.session.get(Purchase, purchase_id)
    if not purchase:
        raise McpToolError("Purchase not found")
    return build_purchase_journey_payload(purchase)


def _lot_journey(arguments: dict) -> dict:
    lot_id = (arguments.get("lot_id") or "").strip()
    if not lot_id:
        raise McpToolError("lot_id is required")
    lot = app_module.db.session.get(PurchaseLot, lot_id)
    if not lot:
        raise McpToolError("Lot not found")
    return build_lot_journey_payload(lot)


def _run_journey(arguments: dict) -> dict:
    run_id = (arguments.get("run_id") or "").strip()
    if not run_id:
        raise McpToolError("run_id is required")
    run = app_module.db.session.get(Run, run_id)
    if not run:
        raise McpToolError("Run not found")
    return build_run_journey_payload(run)


def _reconciliation_overview(arguments: dict) -> dict:
    root = _root()
    from gold_drop import api_v1_module

    built, error = api_v1_module._build_slack_import_items(root)
    if error:
        raise McpToolError("Unable to build reconciliation overview")
    items, bucket_counts = built
    exception_payload = api_v1_module._exceptions_summary_payload(root)
    return {
        "slack_imports": {
            "total_messages": len(items),
            "bucket_counts": bucket_counts,
            "blocked_items": [item for item in items if item.get("triage_bucket") == "blocked"][:10],
            "needs_manual_match_items": [item for item in items if item.get("triage_bucket") == "needs_manual_match"][:10],
        },
        "exceptions": exception_payload,
    }


def _scanner_summary(arguments: dict) -> dict:
    events = LotScanEvent.query.order_by(LotScanEvent.created_at.desc()).all()
    action_counts: dict[str, int] = {}
    for event in events:
        action_counts[event.action] = action_counts.get(event.action, 0) + 1
    return {
        "total_events": len(events),
        "distinct_tracked_lots": len({event.tracking_id_snapshot for event in events if event.tracking_id_snapshot}),
        "action_counts": action_counts,
        "latest_event_at": events[0].created_at.isoformat().replace("+00:00", "Z") if events and events[0].created_at else None,
    }


def _lot_scan_history(arguments: dict) -> dict:
    lot_id = (arguments.get("lot_id") or "").strip()
    tracking_id = (arguments.get("tracking_id") or "").strip()
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
    if not lot_id and not tracking_id:
        raise McpToolError("lot_id or tracking_id is required")
    query = LotScanEvent.query.order_by(LotScanEvent.created_at.desc())
    if lot_id:
        query = query.filter(LotScanEvent.lot_id == lot_id)
    if tracking_id:
        query = query.filter(LotScanEvent.tracking_id_snapshot == tracking_id)
    events = query.limit(limit).all()
    return {
        "filters": {"lot_id": lot_id or None, "tracking_id": tracking_id or None, "limit": limit},
        "results": [serialize_scan_event(event) for event in events],
    }


def _site_identity(arguments: dict) -> dict:
    return get_site_identity()


def _dashboard_summary(arguments: dict) -> dict:
    from gold_drop import api_v1_module

    period = str(arguments.get("period") or "30").strip()
    if period not in {"7", "30", "90"}:
        raise McpToolError("period must be one of 7, 30, or 90")
    with app_module.app.test_request_context("/mcp/dashboard", query_string={"period": period}):
        response = api_v1_module.api_v1_dashboard_summary.__wrapped__()
        return response.get_json()["data"]


def _cross_site_summary(arguments: dict) -> dict:
    from gold_drop import api_v1_module

    root = _root()
    local_site = get_site_identity()
    local_dashboard = _dashboard_summary({"period": str(arguments.get("period") or "30")})
    local_inventory = api_v1_module._inventory_summary_payload(root, supplier_id=None, strain=None)
    local_exceptions = api_v1_module._exceptions_summary_payload(root)
    local_slack, error = api_v1_module._slack_imports_summary_payload(root)
    if error:
        raise McpToolError("Unable to build local Slack summary")
    return build_aggregation_summary(
        local_site,
        local_dashboard=local_dashboard,
        local_inventory=local_inventory,
        local_exceptions=local_exceptions,
        local_slack=local_slack,
    )


def _remote_sites(arguments: dict) -> dict:
    limit = max(1, min(int(arguments.get("limit") or 50), 200))
    sites = RemoteSite.query.order_by(RemoteSite.name.asc()).limit(limit).all()
    return {
        "count": len(sites),
        "sites": [serialize_remote_site_cache(site) for site in sites],
    }


def _cross_site_supplier_compare(arguments: dict) -> dict:
    query_text = (arguments.get("q") or "").strip().lower()
    limit = max(1, min(int(arguments.get("limit") or 100), 200))
    rows = []
    local_site = get_site_identity()
    root = _root()
    for supplier in Supplier.query.order_by(Supplier.name.asc(), Supplier.id.asc()).all():
        payload = _supplier_performance_payload(root, supplier)
        if query_text and query_text not in ((payload.get("supplier") or {}).get("name") or "").lower():
            continue
        payload["site"] = {
            "source": "local",
            "site_code": local_site.get("site_code"),
            "site_name": local_site.get("site_name"),
            "site_region": local_site.get("site_region"),
            "site_environment": local_site.get("site_environment"),
        }
        rows.append(payload)
    for remote_site in RemoteSite.query.filter(RemoteSite.is_active.is_(True)).order_by(RemoteSite.name.asc()).all():
        for payload in remote_site.payload("last_suppliers_payload_json") or []:
            supplier_name = ((payload.get("supplier") or {}).get("name") or "").lower()
            if query_text and query_text not in supplier_name:
                continue
            item = dict(payload)
            item["site"] = {
                "source": "remote_cache",
                "site_code": remote_site.site_code,
                "site_name": remote_site.site_name or remote_site.name,
                "site_region": remote_site.site_region,
                "site_environment": remote_site.site_environment,
            }
            rows.append(item)
    return {"count": len(rows[:limit]), "results": rows[:limit], "query": query_text or None}


def _cross_site_strain_compare(arguments: dict) -> dict:
    from gold_drop import api_v1_module

    root = _root()
    query_text = (arguments.get("q") or "").strip().lower()
    supplier_filter = (arguments.get("supplier_name") or "").strip().lower()
    limit = max(1, min(int(arguments.get("limit") or 100), 200))
    local_site = get_site_identity()
    rows = []
    with app_module.app.test_request_context(
        "/mcp/aggregation/strains",
        query_string={"view": "all", "supplier_id": "", "strain": query_text},
    ):
        local_payload = api_v1_module.api_v1_strains.__wrapped__().get_json()["data"]
    for payload in local_payload:
        supplier_name = (payload.get("supplier_name") or "").lower()
        if supplier_filter and supplier_filter not in supplier_name:
            continue
        item = dict(payload)
        item["site"] = {
            "source": "local",
            "site_code": local_site.get("site_code"),
            "site_name": local_site.get("site_name"),
            "site_region": local_site.get("site_region"),
            "site_environment": local_site.get("site_environment"),
        }
        rows.append(item)
    for remote_site in RemoteSite.query.filter(RemoteSite.is_active.is_(True)).order_by(RemoteSite.name.asc()).all():
        for payload in remote_site.payload("last_strains_payload_json") or []:
            strain_name = (payload.get("strain_name") or "").lower()
            supplier_name = (payload.get("supplier_name") or "").lower()
            if query_text and query_text not in strain_name:
                continue
            if supplier_filter and supplier_filter not in supplier_name:
                continue
            item = dict(payload)
            item["site"] = {
                "source": "remote_cache",
                "site_code": remote_site.site_code,
                "site_name": remote_site.site_name or remote_site.name,
                "site_region": remote_site.site_region,
                "site_environment": remote_site.site_environment,
            }
            rows.append(item)
    return {
        "count": len(rows[:limit]),
        "results": rows[:limit],
        "query": query_text or None,
        "supplier_name": supplier_filter or None,
    }


def _search_entities(arguments: dict) -> dict:
    query_text = (arguments.get("q") or "").strip()
    if not query_text:
        raise McpToolError("q is required")
    allowed_types = {"suppliers", "purchases", "lots", "runs"}
    requested_types = arguments.get("types") or list(allowed_types)
    if isinstance(requested_types, str):
        requested_types = [value.strip().lower() for value in requested_types.split(",") if value.strip()]
    requested_types = set(requested_types)
    if requested_types and not requested_types.issubset(allowed_types):
        raise McpToolError("Invalid types filter")
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
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
                        field
                        for field, value in (("batch_id", purchase.batch_id), ("notes", purchase.notes))
                        if value and query_text.lower() in value.lower()
                    ],
                    context={"status": purchase.status},
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
                    context={"tracking_id": lot.tracking_id},
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
            results.append(
                serialize_search_result(
                    entity_type="run",
                    entity_id=run.id,
                    label=f"Run {run.id[:8]}",
                    subtitle=f"Reactor {run.reactor_number}",
                    match_fields=["reactor_number"] if query_text.isdigit() else ["notes"],
                    context={"reactor_number": run.reactor_number},
                )
            )
    return {"query": query_text, "types": sorted(requested_types), "results": results[:limit]}


def _supplier_performance(arguments: dict) -> dict:
    supplier_id = (arguments.get("supplier_id") or "").strip()
    if not supplier_id:
        raise McpToolError("supplier_id is required")
    supplier = app_module.db.session.get(Supplier, supplier_id)
    if not supplier:
        raise McpToolError("Supplier not found")
    return _supplier_performance_payload(_root(), supplier)


def _strain_performance(arguments: dict) -> dict:
    root = _root()
    view = (arguments.get("view") or "all").strip().lower()
    if view not in {"all", "90"}:
        raise McpToolError("view must be all or 90")
    supplier_id = (arguments.get("supplier_id") or "").strip() or None
    strain = (arguments.get("strain") or "").strip() or None
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
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
    if supplier_id:
        query = query.filter(root.Supplier.id == supplier_id)
    if strain:
        query = query.filter(root.PurchaseLot.strain_name.ilike(f"%{strain}%"))
    if view == "90":
        query = query.filter(root.Run.run_date >= root.date.today() - root.timedelta(days=90))
    query = query.group_by(root.PurchaseLot.strain_name, root.Supplier.name).order_by(root.desc("avg_yield"))
    rows = query.limit(limit).all()
    return {
        "view": view,
        "filters": {"supplier_id": supplier_id, "strain": strain, "limit": limit},
        "results": [
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
            for row in rows
        ],
    }


MCP_TOOLS: list[dict[str, object]] = [
    {
        "name": "site_identity",
        "description": "Return the configured local site identity for this deployment.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _site_identity,
    },
    {
        "name": "inventory_snapshot",
        "description": "Summarize on-hand inventory and return matching lots.",
        "inputSchema": {"type": "object", "properties": {"supplier_id": {"type": "string"}, "strain": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _inventory_snapshot,
    },
    {
        "name": "open_lots",
        "description": "Find open lots with optional supplier, strain, and minimum remaining-weight filters.",
        "inputSchema": {"type": "object", "properties": {"supplier_id": {"type": "string"}, "strain": {"type": "string"}, "min_remaining_lbs": {"type": "number"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _open_lots,
    },
    {
        "name": "journey_resolve",
        "description": "Resolve and return the canonical journey for a purchase, lot, or run.",
        "inputSchema": {"type": "object", "properties": {"entity_type": {"type": "string", "enum": ["purchase", "lot", "run"]}, "entity_id": {"type": "string"}}, "required": ["entity_type", "entity_id"], "additionalProperties": False},
        "handler": _journey_resolve,
    },
    {
        "name": "purchase_journey",
        "description": "Return the detailed journey for a single purchase.",
        "inputSchema": {"type": "object", "properties": {"purchase_id": {"type": "string"}}, "required": ["purchase_id"], "additionalProperties": False},
        "handler": _purchase_journey,
    },
    {
        "name": "lot_journey",
        "description": "Return the detailed journey for a single inventory lot.",
        "inputSchema": {"type": "object", "properties": {"lot_id": {"type": "string"}}, "required": ["lot_id"], "additionalProperties": False},
        "handler": _lot_journey,
    },
    {
        "name": "run_journey",
        "description": "Return the detailed upstream journey for a single extraction run.",
        "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"], "additionalProperties": False},
        "handler": _run_journey,
    },
    {
        "name": "reconciliation_overview",
        "description": "Return Slack-import triage posture plus current exception summaries.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _reconciliation_overview,
    },
    {
        "name": "scanner_summary",
        "description": "Return scanner activity totals and action counts for the local site.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _scanner_summary,
    },
    {
        "name": "lot_scan_history",
        "description": "Return recent scan events for one lot or tracking ID.",
        "inputSchema": {"type": "object", "properties": {"lot_id": {"type": "string"}, "tracking_id": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _lot_scan_history,
    },
    {
        "name": "dashboard_summary",
        "description": "Return the site dashboard summary for a 7, 30, or 90 day period.",
        "inputSchema": {"type": "object", "properties": {"period": {"type": "string", "enum": ["7", "30", "90"]}}, "additionalProperties": False},
        "handler": _dashboard_summary,
    },
    {
        "name": "cross_site_summary",
        "description": "Return the cached cross-site rollup summary using the local site and registered remote-site caches.",
        "inputSchema": {"type": "object", "properties": {"period": {"type": "string", "enum": ["7", "30", "90"]}}, "additionalProperties": False},
        "handler": _cross_site_summary,
    },
    {
        "name": "remote_sites",
        "description": "List registered remote sites and their cached payload status.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _remote_sites,
    },
    {
        "name": "search_entities",
        "description": "Search suppliers, purchases, lots, and runs by text.",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "types": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "limit": {"type": "integer"}}, "required": ["q"], "additionalProperties": False},
        "handler": _search_entities,
    },
    {
        "name": "supplier_performance",
        "description": "Return performance analytics for one supplier.",
        "inputSchema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}, "required": ["supplier_id"], "additionalProperties": False},
        "handler": _supplier_performance,
    },
    {
        "name": "strain_performance",
        "description": "Return strain-performance rows with optional supplier/strain filters.",
        "inputSchema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["all", "90"]}, "supplier_id": {"type": "string"}, "strain": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _strain_performance,
    },
    {
        "name": "cross_site_supplier_compare",
        "description": "Compare supplier performance across the local site and cached remote-site supplier payloads.",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _cross_site_supplier_compare,
    },
    {
        "name": "cross_site_strain_compare",
        "description": "Compare strain performance across the local site and cached remote-site strain payloads.",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}, "supplier_name": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _cross_site_strain_compare,
    },
]


def list_mcp_tools() -> list[dict[str, object]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        }
        for tool in MCP_TOOLS
    ]


def execute_mcp_tool(name: str, arguments: dict | None = None) -> dict:
    arguments = arguments or {}
    tool_map: dict[str, Callable[[dict], dict]] = {
        tool["name"]: tool["handler"] for tool in MCP_TOOLS
    }
    handler = tool_map.get(name)
    if handler is None:
        raise McpToolError(f"Unknown tool {name}")
    with app_module.app.app_context():
        with app_module.app.test_request_context("/mcp"):
            return handler(arguments)
