from __future__ import annotations

from flask import request

from gold_drop.purchases import INVENTORY_ON_HAND_PURCHASE_STATUSES
from models import Purchase, PurchaseLot, Run, RunInput


def parse_limit_offset(req=request, *, default_limit: int = 50, max_limit: int = 200):
    try:
        limit = int((req.args.get("limit") or default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int((req.args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def build_lots_query(
    *,
    purchase_id: str | None = None,
    supplier_id: str | None = None,
    strain: str | None = None,
    tracking_id: str | None = None,
    open_only: bool = False,
    include_archived: bool = False,
):
    query = PurchaseLot.query.join(Purchase)
    if not include_archived:
        query = query.filter(PurchaseLot.deleted_at.is_(None), Purchase.deleted_at.is_(None))
    if purchase_id:
        query = query.filter(PurchaseLot.purchase_id == purchase_id)
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    if strain:
        query = query.filter(PurchaseLot.strain_name.ilike(f"%{strain.strip()}%"))
    if tracking_id:
        query = query.filter(PurchaseLot.tracking_id == tracking_id.strip())
    if open_only:
        query = query.filter(
            PurchaseLot.remaining_weight_lbs > 0,
            Purchase.status.in_(INVENTORY_ON_HAND_PURCHASE_STATUSES),
            Purchase.purchase_approved_at.isnot(None),
        )
    return query.order_by(Purchase.purchase_date.desc(), PurchaseLot.id.desc())


def build_inventory_on_hand_query(*, supplier_id: str | None = None, strain: str | None = None):
    query = (
        PurchaseLot.query.join(Purchase)
        .filter(
            PurchaseLot.remaining_weight_lbs > 0,
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            Purchase.status.in_(INVENTORY_ON_HAND_PURCHASE_STATUSES),
            Purchase.purchase_approved_at.isnot(None),
        )
    )
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    if strain:
        query = query.filter(PurchaseLot.strain_name.ilike(f"%{strain.strip()}%"))
    return query.order_by(Purchase.purchase_date.desc(), PurchaseLot.id.desc())


def build_purchases_query(
    *,
    status: str | None = None,
    supplier_id: str | None = None,
    approved: bool | None = None,
    start_date=None,
    end_date=None,
    include_archived: bool = False,
):
    query = Purchase.query
    if not include_archived:
        query = query.filter(Purchase.deleted_at.is_(None))
    if status:
        query = query.filter(Purchase.status == status)
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    if approved is True:
        query = query.filter(Purchase.purchase_approved_at.isnot(None))
    elif approved is False:
        query = query.filter(Purchase.purchase_approved_at.is_(None))
    if start_date:
        query = query.filter(Purchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(Purchase.purchase_date <= end_date)
    return query.order_by(Purchase.purchase_date.desc(), Purchase.id.desc())


def build_runs_query(
    *,
    start_date=None,
    end_date=None,
    reactor_number: int | None = None,
    supplier_id: str | None = None,
    strain: str | None = None,
    slack_linked: bool | None = None,
    include_archived: bool = False,
):
    query = Run.query
    if not include_archived:
        query = query.filter(Run.deleted_at.is_(None))
    if start_date:
        query = query.filter(Run.run_date >= start_date)
    if end_date:
        query = query.filter(Run.run_date <= end_date)
    if reactor_number is not None:
        query = query.filter(Run.reactor_number == reactor_number)
    if slack_linked is True:
        query = query.filter(Run.slack_message_ts.isnot(None))
    elif slack_linked is False:
        query = query.filter(Run.slack_message_ts.is_(None))
    if supplier_id or strain:
        query = query.join(RunInput, RunInput.run_id == Run.id).join(PurchaseLot, PurchaseLot.id == RunInput.lot_id).join(Purchase, Purchase.id == PurchaseLot.purchase_id)
        if not include_archived:
            query = query.filter(Purchase.deleted_at.is_(None), PurchaseLot.deleted_at.is_(None))
        if supplier_id:
            query = query.filter(Purchase.supplier_id == supplier_id)
        if strain:
            query = query.filter(PurchaseLot.strain_name.ilike(f"%{strain.strip()}%"))
        query = query.distinct()
    return query.order_by(Run.run_date.desc(), Run.id.desc())
