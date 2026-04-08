"""Batch update helpers (used from app.py request handlers)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func

from models import (
    db,
    Run,
    Purchase,
    PurchaseLot,
    BiomassAvailability,
    Supplier,
    CostEntry,
)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

MAX_BATCH_IDS = 200
STRAIN_PAIR_SEP = "\x1f"

RUN_TYPES = frozenset({"standard", "kief", "ld"})
HTE_STAGES = frozenset({"", "awaiting_lab", "lab_clean", "lab_dirty_queued_strip", "terp_stripped"})
PURCHASE_STATUSES = frozenset({
    "declared", "committed", "ordered", "in_transit", "delivered",
    "in_testing", "available", "processing", "complete", "cancelled",
})
BIOMASS_STAGES = frozenset({"declared", "testing", "committed", "delivered", "cancelled"})
BIOMASS_TESTING_STATUS = frozenset({"pending", "completed", "not_needed"})
BIOMASS_TESTING_TIMING = frozenset({"before_delivery", "after_delivery"})
COST_TYPES = frozenset({"solvent", "personnel", "overhead"})


def parse_uuid_ids(raw: str) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        s = part.strip()
        if UUID_RE.match(s) and s not in out:
            out.append(s)
        if len(out) >= MAX_BATCH_IDS:
            break
    return out


def _tri_bool(raw: str) -> Any:
    """'' -> None (no change), '1' True, '0' False."""
    v = (raw or "").strip()
    if v == "":
        return None
    if v == "1":
        return True
    if v == "0":
        return False
    return None


def apply_batch_runs(ids: list[str], form: Any) -> tuple[int, list[str]]:
    """form: werkzeug MultiDict."""
    updated = 0
    errors: list[str] = []
    rt = (form.get("run_type") or "").strip()
    hte_raw = (form.get("hte_pipeline_stage") or "").strip()
    hte = "" if hte_raw == "__nochange__" else hte_raw
    load_src = (form.get("load_source_reactors") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()
    rollover = _tri_bool(form.get("set_is_rollover") or "")
    decarb = _tri_bool(form.get("set_decarb_sample_done") or "")

    for rid in ids:
        run = db.session.get(Run, rid)
        if not run or run.deleted_at is not None:
            errors.append(f"Run {rid[:8]}… not found.")
            continue
        changed = False
        if rt and rt in RUN_TYPES:
            run.run_type = rt
            changed = True
        if hte_raw != "__nochange__" and hte in HTE_STAGES:
            run.hte_pipeline_stage = hte or None
            changed = True
        if form.get("apply_load_source") == "1":
            run.load_source_reactors = load_src or None
            changed = True
        if rollover is not None:
            run.is_rollover = rollover
            changed = True
        if decarb is not None:
            run.decarb_sample_done = decarb
            changed = True
        if notes_add:
            prev = (run.notes or "").strip()
            run.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            run.calculate_yields()
            try:
                run.calculate_cost()
            except Exception:
                pass
            updated += 1
    return updated, errors


def apply_batch_purchases(ids: list[str], form: Any) -> tuple[int, list[str], list]:
    """Returns (count, errors, touched_purchase_objects) for downstream hooks."""
    updated = 0
    errors: list[str] = []
    touched: list = []
    st = (form.get("status") or "").strip()
    dd_raw = (form.get("delivery_date") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()
    delivery_date = None
    if dd_raw:
        try:
            delivery_date = datetime.strptime(dd_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Invalid delivery date.")
            return 0, errors, []

    for pid in ids:
        p = db.session.get(Purchase, pid)
        if not p or p.deleted_at is not None:
            errors.append(f"Purchase {pid[:8]}… not found.")
            continue
        changed = False
        if st and st in PURCHASE_STATUSES:
            p.status = st
            changed = True
        if form.get("apply_delivery_date") == "1":
            p.delivery_date = delivery_date  # None if field left blank → clear
            changed = True
        qp_raw = (form.get("queue_placement") or "").strip()
        if qp_raw == "__clear__":
            p.queue_placement = None
            changed = True
        elif qp_raw in ("aggregate", "indoor", "outdoor"):
            p.queue_placement = qp_raw
            changed = True
        if notes_add:
            prev = (p.notes or "").strip()
            p.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            touched.append(p)
            updated += 1
    return updated, errors, touched


def apply_batch_biomass(ids: list[str], form: Any) -> tuple[int, list[str]]:
    updated = 0
    errors: list[str] = []
    stage = (form.get("stage") or "").strip()
    ts = (form.get("testing_status") or "").strip()
    tt = (form.get("testing_timing") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()

    for bid in ids:
        b = db.session.get(BiomassAvailability, bid)
        if not b:
            errors.append(f"Biomass row {bid[:8]}… not found.")
            continue
        changed = False
        if stage and stage in BIOMASS_STAGES:
            b.stage = stage
            changed = True
        if ts and ts in BIOMASS_TESTING_STATUS:
            b.testing_status = ts
            changed = True
        if tt and tt in BIOMASS_TESTING_TIMING:
            b.testing_timing = tt
            changed = True
        if notes_add:
            prev = (b.notes or "").strip()
            b.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            updated += 1
    return updated, errors


def apply_batch_suppliers(ids: list[str], form: Any) -> tuple[int, list[str]]:
    updated = 0
    errors: list[str] = []
    act = (form.get("is_active_action") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()
    if act not in ("", "activate", "deactivate"):
        return 0, ["Invalid active/inactive selection."]
    if not act and not notes_add:
        return 0, ["Nothing to apply: set active/inactive and/or append to notes."]

    val = True if act == "activate" else False if act == "deactivate" else None
    for sid in ids:
        s = db.session.get(Supplier, sid)
        if not s:
            errors.append(f"Supplier {sid[:8]}… not found.")
            continue
        changed = False
        if val is not None and s.is_active != val:
            s.is_active = val
            changed = True
        if notes_add:
            prev = (s.notes or "").strip()
            s.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            updated += 1
    return updated, errors


def apply_batch_costs(ids: list[str], form: Any) -> tuple[int, list[str]]:
    updated = 0
    errors: list[str] = []
    ct = (form.get("cost_type") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()

    for eid in ids:
        e = db.session.get(CostEntry, eid)
        if not e:
            errors.append(f"Cost {eid[:8]}… not found.")
            continue
        changed = False
        if ct and ct in COST_TYPES:
            e.cost_type = ct
            changed = True
        if notes_add:
            prev = (e.notes or "").strip()
            e.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            updated += 1
    return updated, errors


def apply_batch_inventory_lots(ids: list[str], form: Any) -> tuple[int, list[str]]:
    updated = 0
    errors: list[str] = []
    strain = (form.get("strain_name") or "").strip()
    loc = (form.get("location") or "").strip()
    notes_add = (form.get("notes_append") or "").strip()
    milled = _tri_bool(form.get("set_milled") or "")
    pot_raw = (form.get("potency_pct") or "").strip()
    potency = None
    if pot_raw:
        try:
            potency = float(pot_raw.replace(",", ""))
        except ValueError:
            return 0, ["Invalid potency value."]

    for lid in ids:
        lot = db.session.get(PurchaseLot, lid)
        if not lot or lot.deleted_at is not None:
            errors.append(f"Lot {lid[:8]}… not found.")
            continue
        changed = False
        if strain:
            lot.strain_name = strain[:200]
            changed = True
        if form.get("apply_location") == "1":
            lot.location = loc or None
            changed = True
        if milled is not None:
            lot.milled = milled
            changed = True
        if potency is not None and form.get("apply_potency") == "1":
            lot.potency_pct = potency
            changed = True
        if notes_add:
            prev = (lot.notes or "").strip()
            lot.notes = (prev + "\n" + notes_add).strip() if prev else notes_add
            changed = True
        if changed:
            updated += 1
    return updated, errors


def apply_batch_strain_rename(pairs: list[str], new_name: str) -> tuple[int, list[str]]:
    """pairs: strain_name + STRAIN_PAIR_SEP + supplier_name."""
    updated = 0
    errors: list[str] = []
    nn = (new_name or "").strip()
    if not nn:
        return 0, ["New strain name is required."]
    if len(nn) > 200:
        return 0, ["New strain name is too long (max 200)."]

    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        if STRAIN_PAIR_SEP not in pair:
            continue
        strain, sup_name = pair.split(STRAIN_PAIR_SEP, 1)
        strain = strain.strip()
        sup_name = sup_name.strip()
        if not strain or not sup_name:
            continue
        key = (strain.lower(), sup_name.lower())
        if key in seen:
            continue
        seen.add(key)
        sup = Supplier.query.filter(func.lower(Supplier.name) == sup_name.lower()).first()
        if not sup:
            errors.append(f"No supplier match for {sup_name!r}.")
            continue
        lots = (
            PurchaseLot.query.join(Purchase)
            .filter(
                Purchase.supplier_id == sup.id,
                PurchaseLot.strain_name == strain,
                PurchaseLot.deleted_at.is_(None),
                Purchase.deleted_at.is_(None),
            )
            .all()
        )
        for lot in lots:
            lot.strain_name = nn[:200]
            updated += 1
    if not seen:
        return 0, ["No valid strain rows selected."]
    return updated, errors
