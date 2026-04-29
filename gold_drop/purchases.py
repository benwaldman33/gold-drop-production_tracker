from __future__ import annotations

from datetime import date, timedelta

from models import Purchase, SystemSetting

BIOMASS_BUDGET_COUNT_STATUSES = frozenset({
    "committed", "ordered", "in_transit", "in_testing", "available",
    "delivered", "processing", "complete",
})
INVENTORY_ON_HAND_PURCHASE_STATUSES = ("delivered", "in_testing", "available", "processing")
NON_OPERATIONAL_PURCHASE_STATUSES = frozenset({"complete", "cancelled"})
OPERATIONAL_PURCHASE_STATUSES = frozenset({
    "declared",
    "ordered",
    "committed",
    "in_transit",
    "in_testing",
    "available",
    "delivered",
    "processing",
})


def purchase_is_operational(p: Purchase | None) -> bool:
    if not p or p.deleted_at is not None:
        return False
    return (p.status or "").strip().lower() not in NON_OPERATIONAL_PURCHASE_STATUSES


def filter_operational_purchases(query):
    return query.filter(Purchase.status.notin_(NON_OPERATIONAL_PURCHASE_STATUSES))


def purchase_counts_toward_biomass_budget(p: Purchase | None) -> bool:
    if not p or p.deleted_at is not None:
        return False
    return (p.status or "").strip() in BIOMASS_BUDGET_COUNT_STATUSES


def purchase_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def purchase_biomass_budget_lbs(p: Purchase | None) -> float:
    if not p:
        return 0.0
    if p.actual_weight_lbs is not None:
        return float(p.actual_weight_lbs)
    return float(p.stated_weight_lbs or 0) or 0.0


def purchase_biomass_budget_potency(p: Purchase | None) -> float | None:
    if not p:
        return None
    if p.tested_potency_pct is not None:
        return float(p.tested_potency_pct)
    if p.stated_potency_pct is not None:
        return float(p.stated_potency_pct)
    return None


def purchase_budget_spend(p: Purchase | None) -> float:
    if not p:
        return 0.0
    if p.total_cost is not None and float(p.total_cost) > 0:
        return float(p.total_cost)
    w = purchase_biomass_budget_lbs(p)
    if p.price_per_lb is not None and w > 0:
        return float(w) * float(p.price_per_lb)
    return 0.0


def budget_week_purchase_metrics(week_start: date, week_end: date, exclude_purchase_id: str | None = None) -> dict:
    q = Purchase.query.filter(
        Purchase.deleted_at.is_(None),
        Purchase.purchase_date >= week_start,
        Purchase.purchase_date <= week_end,
        Purchase.status.in_(BIOMASS_BUDGET_COUNT_STATUSES),
    )
    if exclude_purchase_id:
        q = q.filter(Purchase.id != exclude_purchase_id)
    spend = 0.0
    lbs = 0.0
    weighted_pot_sum = 0.0
    clean_lbs = 0.0
    dirty_lbs = 0.0
    unknown_lbs = 0.0
    n = 0
    for p in q.all():
        n += 1
        lb = purchase_biomass_budget_lbs(p)
        lbs += lb
        spend += purchase_budget_spend(p)
        pot = purchase_biomass_budget_potency(p)
        if pot is not None:
            weighted_pot_sum += lb * pot
        cod = (p.clean_or_dirty or "").strip().lower()
        if cod == "clean":
            clean_lbs += lb
        elif cod == "dirty":
            dirty_lbs += lb
        else:
            unknown_lbs += lb
    return {
        "spend": spend,
        "lbs": lbs,
        "weighted_pot_sum": weighted_pot_sum,
        "clean_lbs": clean_lbs,
        "dirty_lbs": dirty_lbs,
        "unknown_lbs": unknown_lbs,
        "purchase_count": n,
    }


def biomass_budget_snapshot_for_purchase(p: Purchase | None) -> tuple[bool, float, float | None, float]:
    if not p:
        return False, 0.0, None, 0.0
    counted = purchase_counts_toward_biomass_budget(p)
    lbs = purchase_biomass_budget_lbs(p)
    pot = purchase_biomass_budget_potency(p) if counted else None
    spend = purchase_budget_spend(p) if counted else 0.0
    return counted, lbs, pot, spend


def enforce_weekly_biomass_purchase_limits(purchase: Purchase, new_snap: tuple, *, enforce_cap: bool = True) -> None:
    if not enforce_cap:
        return
    counted, lbs, _pot, spend = new_snap
    if not purchase.purchase_date:
        return
    ws = purchase_week_start(purchase.purchase_date)
    we = ws + timedelta(days=6)
    base = budget_week_purchase_metrics(ws, we, exclude_purchase_id=purchase.id)
    tot_spend = base["spend"] + (spend if counted else 0.0)
    tot_lbs = base["lbs"] + (lbs if counted else 0.0)
    cap_usd = SystemSetting.get_float("biomass_purchase_weekly_budget_usd", 0)
    cap_lbs = SystemSetting.get_float("biomass_purchase_weekly_target_lbs", 0)
    if cap_usd > 0 and tot_spend > cap_usd + 0.01:
        remaining = max(0.0, cap_usd - base["spend"])
        raise ValueError(
            f"This would exceed the weekly biomass purchase budget (${cap_usd:,.0f}). "
            f"Already ~${base['spend']:,.0f} this week; ~${remaining:,.0f} remaining before this purchase."
        )
    if cap_lbs > 0 and tot_lbs > cap_lbs + 1e-6:
        remaining = max(0.0, cap_lbs - base["lbs"])
        raise ValueError(
            f"This would exceed the weekly biomass volume target ({cap_lbs:,.0f} lbs). "
            f"Already ~{base['lbs']:,.0f} lbs this week; ~{remaining:,.0f} lbs room before this purchase."
        )
