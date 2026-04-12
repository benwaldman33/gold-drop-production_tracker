from __future__ import annotations

import json
import re
from datetime import date, datetime


SLACK_APPLY_PASSTHROUGH_FORM_KEYS = frozenset({
    "slack_supplier_mode",
    "slack_supplier_id",
    "slack_new_supplier_name",
    "slack_confirm_create_supplier",
    "slack_confirm_fuzzy_supplier",
    "slack_canonical_strain",
    "slack_confirm_fuzzy_strain",
    "slack_biomass_declared",
    "slack_biomass_strain",
    "slack_biomass_weight_lbs",
    "slack_availability_date",
    "slack_selected_allocations_json",
})

SLACK_SUPPLIER_ALIAS_STOPWORDS = frozenset({
    "and",
    "co",
    "company",
    "corp",
    "corporation",
    "cultivation",
    "cultivator",
    "cultivators",
    "farm",
    "farms",
    "garden",
    "gardens",
    "grow",
    "group",
    "inc",
    "llc",
    "ltd",
    "organics",
    "the",
})


def slack_apply_form_passthrough(form) -> dict[str, str]:
    if not form:
        return {}
    out: dict[str, str] = {}
    for key in SLACK_APPLY_PASSTHROUGH_FORM_KEYS:
        value = form.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text
    return out


def slack_run_prefill_put(
    session_store,
    *,
    msg_id: str,
    channel_id: str,
    message_ts: str,
    filled: dict,
    allow_duplicate: bool,
    resolution: dict | None = None,
    suggested_allocations: list[dict] | None = None,
    lot_candidates: list[dict] | None = None,
) -> None:
    payload: dict = {
        "ingested_message_id": msg_id,
        "channel_id": channel_id,
        "message_ts": message_ts,
        "filled": _slack_filled_json_safe(filled),
        "allow_duplicate": bool(allow_duplicate),
    }
    if resolution:
        payload["resolution"] = _slack_resolution_json_safe(resolution)
    if suggested_allocations:
        payload["suggested_allocations"] = [
            {
                "lot_id": str(item.get("lot_id") or "").strip(),
                "weight_lbs": float(item.get("weight_lbs") or 0),
            }
            for item in suggested_allocations
            if item.get("lot_id") and float(item.get("weight_lbs") or 0) > 0
        ]
    if lot_candidates:
        payload["lot_candidates"] = [
            {
                "lot_id": item.get("lot_id"),
                "tracking_id": item.get("tracking_id"),
                "batch_id": item.get("batch_id"),
                "supplier_name": item.get("supplier_name"),
                "strain_name": item.get("strain_name"),
                "remaining_weight_lbs": item.get("remaining_weight_lbs"),
                "received_date": item.get("received_date"),
                "score": item.get("score"),
                "match_reason": item.get("match_reason"),
            }
            for item in lot_candidates
        ]
    session_store["slack_run_prefill"] = payload


def slack_selected_allocations_from_form(form, *, requested_run_lbs: float | None = None) -> tuple[list[dict], str | None]:
    raw = (form.get("slack_selected_allocations_json") or "").strip()
    if not raw:
        return [], None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], "Selected lot allocations could not be parsed."
    if not isinstance(payload, list):
        return [], "Selected lot allocations must be a list."

    merged: dict[str, float] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        lot_id = str(item.get("lot_id") or "").strip()
        if not lot_id:
            continue
        try:
            weight = float(item.get("weight_lbs") or 0)
        except (TypeError, ValueError):
            return [], "Selected lot allocation weight must be numeric."
        if weight <= 0:
            continue
        merged[lot_id] = merged.get(lot_id, 0.0) + weight

    allocations = [
        {"lot_id": lot_id, "weight_lbs": weight_lbs}
        for lot_id, weight_lbs in merged.items()
    ]
    if not allocations:
        return [], None
    if requested_run_lbs is not None:
        total = sum(float(item["weight_lbs"] or 0) for item in allocations)
        if abs(total - float(requested_run_lbs)) > 0.1:
            return [], "Selected lot allocations must equal the parsed run weight before opening the run form."
    return allocations, None


def slack_supplier_candidates_for_source(root, source_raw: str, limit: int = 12) -> list[dict]:
    norm = _slack_normalize_match_name(source_raw)
    tokens = list(dict.fromkeys(_slack_name_tokens(source_raw, alias=True)))[:6]
    if not (norm or tokens):
        return []
    query = root.Supplier.query.filter(root.Supplier.is_active.is_(True))
    conditions = []
    if norm:
        conditions.append(root.func.lower(root.Supplier.name) == norm)
    for token in tokens:
        conditions.append(root.func.lower(root.Supplier.name).like(f"%{token}%"))
    suppliers = (
        query.filter(root.or_(*conditions)).order_by(root.Supplier.name).limit(max(limit * 4, 20)).all()
        if conditions else
        query.order_by(root.Supplier.name).limit(max(limit * 2, 12)).all()
    )
    scored: list[dict] = []
    seen_ids: set[str] = set()
    for supplier in suppliers:
        if supplier.id in seen_ids:
            continue
        candidate = _slack_build_supplier_candidate(source_raw, supplier)
        if not candidate:
            continue
        seen_ids.add(supplier.id)
        scored.append(candidate)
    scored.sort(key=lambda item: (-int(item["score"]), item["name"].lower()))
    return scored[:limit]


def slack_supplier_mapping_needs_fuzzy_confirm(root, source_raw: str, supplier_id: str | None) -> bool:
    if not (source_raw or "").strip() or not (supplier_id or "").strip():
        return False
    supplier = root.db.session.get(root.Supplier, supplier_id)
    candidate = _slack_build_supplier_candidate(source_raw, supplier)
    if candidate is None:
        return not _slack_supplier_exact_name_match(source_raw, supplier)
    return candidate.get("requires_confirmation", True)


def slack_supplier_exact_name_match(source_raw: str, supplier) -> bool:
    return _slack_supplier_exact_name_match(source_raw, supplier)


def slack_build_supplier_candidate(source_raw: str, supplier) -> dict | None:
    return _slack_build_supplier_candidate(source_raw, supplier)


def slack_strain_candidates_for_name(
    root,
    raw_strain: str,
    *,
    supplier_ids: list[str] | None = None,
    limit: int = 12,
) -> list[dict]:
    raw_norm = _slack_normalize_strain_name(raw_strain)
    if not raw_norm:
        return []
    rows = (
        root.db.session.query(root.PurchaseLot.strain_name, root.Purchase.supplier_id, root.Supplier.name)
        .join(root.Purchase, root.Purchase.id == root.PurchaseLot.purchase_id)
        .join(root.Supplier, root.Supplier.id == root.Purchase.supplier_id)
        .filter(
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.PurchaseLot.strain_name.isnot(None),
            root.PurchaseLot.strain_name != "",
        )
        .all()
    )
    preferred_supplier_ids = {sid for sid in (supplier_ids or []) if sid}
    by_name: dict[str, dict] = {}
    for strain_name, supplier_id, supplier_name in rows:
        key = (strain_name or "").strip()
        if not key:
            continue
        bucket = by_name.setdefault(key, {"supplier_ids": set(), "supplier_names": set(), "uses": 0})
        if supplier_id:
            bucket["supplier_ids"].add(str(supplier_id))
        if supplier_name:
            bucket["supplier_names"].add(str(supplier_name))
        bucket["uses"] += 1
    scored: list[dict] = []
    for name, meta in by_name.items():
        candidate = _slack_build_strain_candidate(
            raw_strain,
            name,
            supplier_ids=preferred_supplier_ids,
            candidate_supplier_ids=meta["supplier_ids"],
            candidate_supplier_names=sorted(meta["supplier_names"]),
            uses=meta["uses"],
        )
        if candidate:
            scored.append(candidate)
    scored.sort(key=lambda item: (-int(item["score"]), item["name"].lower()))
    return scored[:limit]


def slack_selected_canonical_strain(
    form,
    *,
    raw_strain: str,
    text_field: str,
    canonical_field: str,
    confirm_field: str,
    required_for_label: str,
) -> tuple[str, str | None]:
    free_text = (form.get(text_field) or "").strip()
    canonical = (form.get(canonical_field) or "").strip()
    selected = (canonical or free_text or raw_strain or "").strip()
    if canonical and slack_strain_mapping_needs_fuzzy_confirm(raw_strain, canonical):
        if form.get(confirm_field) != "1":
            return "", (
                f"The selected {required_for_label} does not exactly match the Slack strain line "
                'check "Confirm canonical strain mapping" or choose a closer match.'
            )
    return selected, None


def slack_strain_mapping_needs_fuzzy_confirm(raw_strain: str, selected_strain: str | None) -> bool:
    if not (raw_strain or "").strip() or not (selected_strain or "").strip():
        return False
    return _slack_normalize_strain_name(raw_strain) != _slack_normalize_strain_name(selected_strain)


def slack_resolution_from_apply_form(root, form, *, derived: dict, message_ts: str) -> tuple[dict | None, str | None]:
    derived = derived or {}
    source_raw = (derived.get("source") or "").strip()
    strain_raw = (derived.get("strain") or "").strip()
    needs_supplier_line = bool(source_raw)

    supplier_mode = (form.get("slack_supplier_mode") or "").strip() or "skip"
    supplier_id = (form.get("slack_supplier_id") or "").strip() or None
    new_name = (form.get("slack_new_supplier_name") or "").strip()
    confirm_create = form.get("slack_confirm_create_supplier") == "1"
    confirm_fuzzy = form.get("slack_confirm_fuzzy_supplier") == "1"

    biomass_declared = form.get("slack_biomass_declared") == "1"
    biomass_strain, strain_err = slack_selected_canonical_strain(
        form,
        raw_strain=strain_raw,
        text_field="slack_biomass_strain",
        canonical_field="slack_canonical_strain",
        confirm_field="slack_confirm_fuzzy_strain",
        required_for_label="canonical strain",
    )
    if strain_err:
        return None, strain_err
    bw_raw = (form.get("slack_biomass_weight_lbs") or "").strip()
    if bw_raw:
        try:
            biomass_weight = float(bw_raw)
        except ValueError:
            return None, "Biomass weight must be a number."
    else:
        biomass_weight = root._slack_default_bio_weight_lbs(derived)
    if biomass_weight < 0:
        return None, "Biomass weight cannot be negative."

    avail_raw = (form.get("slack_availability_date") or "").strip()
    if avail_raw and len(avail_raw) >= 10:
        try:
            datetime.strptime(avail_raw[:10], "%Y-%m-%d")
            availability_date = avail_raw[:10]
        except ValueError:
            return None, "Availability date must be YYYY-MM-DD."
    else:
        availability_date = root._slack_default_availability_date_iso(derived, message_ts)

    if needs_supplier_line:
        if supplier_mode not in ("existing", "create"):
            return None, "Slack message includes source: choose an existing supplier or confirm creating a new one."
        if supplier_mode == "existing":
            if not supplier_id:
                return None, "Select a supplier that matches the Slack source line."
            if slack_supplier_mapping_needs_fuzzy_confirm(root, source_raw, supplier_id) and not confirm_fuzzy:
                return None, (
                    "The selected supplier name does not exactly match the Slack source line "
                    'check "Confirm supplier mapping" or pick a different supplier.'
                )
        else:
            if not new_name:
                return None, "Enter the new supplier name to create."
            if not confirm_create:
                return None, "Check the box to confirm creating this supplier."
    elif biomass_declared:
        if supplier_mode not in ("existing", "create"):
            return None, "Declared biomass requires a supplier pick existing or create new."
        if supplier_mode == "existing" and not supplier_id:
            return None, "Select a supplier for the biomass pipeline row."
        if supplier_mode == "create":
            if not new_name:
                return None, "Enter the supplier name for the biomass pipeline row."
            if not confirm_create:
                return None, "Confirm creating the supplier for this biomass row."

    if biomass_declared and not (biomass_strain or strain_raw or "").strip():
        return None, "Strain is required for a declared biomass pipeline row."

    resolution: dict = {
        "source_raw": source_raw,
        "strain_raw": strain_raw,
        "supplier_mode": supplier_mode,
        "supplier_id": supplier_id,
        "new_supplier_name": new_name if supplier_mode == "create" else "",
        "confirm_create_supplier": bool(confirm_create),
        "confirm_fuzzy_supplier": bool(confirm_fuzzy),
        "canonical_strain": (form.get("slack_canonical_strain") or "").strip(),
        "confirm_fuzzy_strain": form.get("slack_confirm_fuzzy_strain") == "1",
        "biomass_declared": bool(biomass_declared),
        "biomass_strain": (biomass_strain or strain_raw or "").strip(),
        "biomass_weight_lbs": float(biomass_weight),
        "availability_date": availability_date or "",
    }
    has_work = needs_supplier_line or biomass_declared or (supplier_mode == "create" and confirm_create and new_name)
    if not has_work and not biomass_declared:
        return None, None
    if not needs_supplier_line and not biomass_declared and supplier_mode == "skip":
        return None, None
    return resolution, None


def slack_resolution_materialize_supplier(root, res: dict, slack_meta: dict) -> str | None:
    mode = (res.get("supplier_mode") or "").strip()
    if mode == "existing":
        supplier_id = (res.get("supplier_id") or "").strip()
        if not supplier_id:
            raise ValueError("Slack import: supplier was not selected.")
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Slack import: selected supplier no longer exists.")
        return supplier_id
    if mode == "create":
        if not res.get("confirm_create_supplier"):
            raise ValueError("Slack import: new supplier was not confirmed.")
        name = (res.get("new_supplier_name") or "").strip()
        if not name:
            raise ValueError("Slack import: new supplier name missing.")
        existing = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == name.lower()).first()
        if existing:
            return existing.id
        provenance = {
            "source": "slack_import_apply",
            "slack_ingested_message_id": slack_meta.get("ingested_message_id"),
            "channel_id": slack_meta.get("channel_id"),
            "message_ts": slack_meta.get("message_ts"),
            "parsed_source_raw": res.get("source_raw"),
        }
        note_line = (
            f"Created from Slack import (channel {slack_meta.get('channel_id')}, ts {slack_meta.get('message_ts')}). "
            f"Parsed source line: {res.get('source_raw') or '-'}."
        )
        supplier = root.Supplier(name=name, is_active=True, notes=note_line)
        root.db.session.add(supplier)
        root.db.session.flush()
        root.log_audit("create", "supplier", supplier.id, details=json.dumps(provenance))
        return supplier.id
    return None


def slack_resolution_create_declared_biomass(root, res: dict, supplier_id: str, slack_meta: dict, run_date: date) -> None:
    if not res.get("biomass_declared"):
        return
    strain = (res.get("biomass_strain") or res.get("strain_raw") or "").strip()
    if not strain:
        raise ValueError("Slack import: biomass strain missing.")
    ad_iso = (res.get("availability_date") or "").strip()
    if len(ad_iso) >= 10:
        try:
            availability_date = datetime.strptime(ad_iso[:10], "%Y-%m-%d").date()
        except ValueError:
            availability_date = run_date
    else:
        availability_date = run_date
    weight = float(res.get("biomass_weight_lbs") or 0)
    provenance = (
        f"Declared from Slack import channel {slack_meta.get('channel_id')}, ts {slack_meta.get('message_ts')}, "
        f"ingested row {slack_meta.get('ingested_message_id') or '-'}. "
        f"Slack source: {res.get('source_raw') or '-'}; parsed strain: {res.get('strain_raw') or '-'}."
    )
    purchase = root.Purchase(
        supplier_id=supplier_id,
        availability_date=availability_date,
        declared_weight_lbs=weight,
        stated_weight_lbs=weight,
        purchase_date=availability_date,
        status="declared",
        notes=provenance,
    )
    root.db.session.add(purchase)
    root.db.session.flush()
    root.db.session.add(root.PurchaseLot(
        purchase_id=purchase.id,
        strain_name=strain,
        weight_lbs=weight,
        remaining_weight_lbs=weight,
    ))
    supplier = root.db.session.get(root.Supplier, supplier_id)
    supplier_name = supplier.name if supplier else "BATCH"
    purchase.batch_id = root._ensure_unique_batch_id(
        root._generate_batch_id(supplier_name, availability_date, weight),
        exclude_purchase_id=purchase.id,
    )
    root.log_audit(
        "create",
        "purchase",
        purchase.id,
        details=json.dumps({
            "source": "slack_import_apply",
            "pipeline_stage": "declared",
            "slack_ingested_message_id": slack_meta.get("ingested_message_id"),
            "channel_id": slack_meta.get("channel_id"),
            "message_ts": slack_meta.get("message_ts"),
            "supplier_id": supplier_id,
            "strain": strain,
        }),
    )


def hydrate_run_from_slack_prefill(root, prefill: dict, today: date):
    run = root.Run()
    filled = dict(prefill.get("filled") or {})
    run_date = filled.pop("run_date", None)
    if isinstance(run_date, str) and run_date.strip():
        try:
            run.run_date = datetime.strptime(run_date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            run.run_date = today
    elif isinstance(run_date, date):
        run.run_date = run_date
    else:
        run.run_date = today

    def _flt(key):
        value = filled.pop(key, None)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _int(key):
        value = filled.pop(key, None)
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    run.reactor_number = _int("reactor_number") or 1
    run.load_source_reactors = filled.pop("load_source_reactors", None) or None
    if run.load_source_reactors is not None:
        run.load_source_reactors = str(run.load_source_reactors).strip() or None
    run.bio_in_reactor_lbs = _flt("bio_in_reactor_lbs")
    run.bio_in_house_lbs = _flt("bio_in_house_lbs")
    run.grams_ran = _flt("grams_ran")
    run.butane_in_house_lbs = _flt("butane_in_house_lbs")
    run.solvent_ratio = _flt("solvent_ratio")
    run.system_temp = _flt("system_temp")
    run.wet_hte_g = _flt("wet_hte_g")
    run.wet_thca_g = _flt("wet_thca_g")
    run.dry_hte_g = _flt("dry_hte_g")
    run.dry_thca_g = _flt("dry_thca_g")
    run.overall_yield_pct = _flt("overall_yield_pct")
    run.thca_yield_pct = _flt("thca_yield_pct")
    run.hte_yield_pct = _flt("hte_yield_pct")
    run.fuel_consumption = _flt("fuel_consumption")
    run_type = filled.pop("run_type", None)
    if run_type is not None:
        run_type = str(run_type).strip().lower()
        if run_type in ("standard", "kief", "ld"):
            run.run_type = run_type
    notes = filled.pop("notes", None)
    if notes is not None:
        run.notes = str(notes).strip() or None
    return run


def slack_linked_run_ids_index(root) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    rows = root.Run.query.filter(
        root.Run.deleted_at.is_(None),
        root.Run.slack_channel_id.isnot(None),
        root.Run.slack_message_ts.isnot(None),
    ).all()
    for run in rows:
        key = (run.slack_channel_id, run.slack_message_ts)
        out.setdefault(key, []).append(run.id)
    return out


def slack_intake_supplier_from_form(root, form):
    source_raw = (form.get("intake_source_raw") or "").strip()
    mode = (form.get("intake_supplier_mode") or "").strip()
    if mode == "existing":
        supplier_id = (form.get("intake_supplier_id") or "").strip()
        if not supplier_id:
            raise ValueError("Select a supplier for this intake purchase.")
        if slack_supplier_mapping_needs_fuzzy_confirm(root, source_raw, supplier_id):
            if form.get("intake_confirm_fuzzy_supplier") != "1":
                raise ValueError("Confirm the supplier mapping or choose a closer supplier match.")
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        return supplier
    if mode == "create":
        if form.get("intake_confirm_create_supplier") != "1":
            raise ValueError("Check the box to confirm creating this supplier.")
        name = (form.get("intake_new_supplier_name") or "").strip()
        if not name:
            raise ValueError("New supplier name is required.")
        existing = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == name.lower()).first()
        if existing:
            return existing
        supplier = root.Supplier(name=name, is_active=True, notes="Created from Slack biomass intake apply.")
        root.db.session.add(supplier)
        root.db.session.flush()
        root.log_audit("create", "supplier", supplier.id, details=json.dumps({"source": "slack_biomass_intake"}))
        return supplier
    raise ValueError("Choose an existing supplier or confirm creating the farm / supplier.")


def apply_slack_intake_update_purchase(
    root,
    purchase,
    derived: dict,
    row,
    *,
    resolved_strain: str | None = None,
    manifest_wt: float | None,
    actual_wt: float | None,
    received: date | None,
) -> None:
    if received:
        purchase.delivery_date = received
    if manifest_wt is not None:
        purchase.stated_weight_lbs = float(manifest_wt)
    if actual_wt is not None:
        purchase.actual_weight_lbs = float(actual_wt)
    if purchase.status in ("ordered", "in_transit", "committed"):
        purchase.status = "delivered"
    weight = purchase.actual_weight_lbs or purchase.stated_weight_lbs
    if weight and purchase.price_per_lb:
        purchase.total_cost = weight * purchase.price_per_lb
    if purchase.tested_potency_pct and purchase.stated_potency_pct and purchase.actual_weight_lbs:
        rate = root.SystemSetting.get_float("potency_rate", 1.50)
        purchase.true_up_amount = (
            (purchase.tested_potency_pct - purchase.stated_potency_pct) * rate * purchase.actual_weight_lbs
        )
        if not purchase.true_up_status:
            purchase.true_up_status = "pending"

    strain = (resolved_strain or derived.get("strain") or "").strip()
    active_lots = [lot for lot in purchase.lots if lot.deleted_at is None]
    if len(active_lots) == 1 and actual_wt is not None:
        lot = active_lots[0]
        consumed = max(0.0, float(lot.weight_lbs) - float(lot.remaining_weight_lbs))
        lot.weight_lbs = float(actual_wt)
        lot.remaining_weight_lbs = max(0.0, float(actual_wt) - consumed)
        if strain:
            lot.strain_name = strain[:200]

    tail = (
        f"Slack biomass intake ({row.channel_id} ts {row.message_ts}): "
        f"manifest {manifest_wt} lbs, actual {actual_wt} lbs."
    )
    purchase.notes = f"{purchase.notes}\n{tail}".strip() if purchase.notes else tail


def create_purchase_from_slack_intake(
    root,
    supplier,
    derived: dict,
    row,
    *,
    resolved_strain: str | None = None,
    manifest_key: str,
    manifest_wt: float,
    actual_wt: float | None,
    received: date | None,
    intake_order: date | None,
):
    purchase_date = intake_order or received or date.today()
    delivery_date = received
    actual_weight = actual_wt if actual_wt is not None else float(manifest_wt)
    purchase = root.Purchase(
        supplier_id=supplier.id,
        purchase_date=purchase_date,
        delivery_date=delivery_date,
        status="ordered",
        stated_weight_lbs=float(manifest_wt),
        actual_weight_lbs=float(actual_weight),
    )
    root.db.session.add(purchase)
    root.db.session.flush()
    batch_id = manifest_key.strip().upper()
    if batch_id:
        conflict = root.Purchase.query.filter(
            root.Purchase.batch_id == batch_id,
            root.Purchase.deleted_at.is_(None),
            root.Purchase.id != purchase.id,
        ).first()
        if conflict:
            raise ValueError(
                f"Batch / manifest ID {batch_id} is already used on another purchase. "
                "Use Update existing purchase instead."
            )
        purchase.batch_id = batch_id
    else:
        purchase.batch_id = root._ensure_unique_batch_id(
            root._generate_batch_id(supplier.name, delivery_date or purchase_date, actual_weight),
            exclude_purchase_id=purchase.id,
        )
    strain = ((resolved_strain or derived.get("strain") or "").strip() or "Unknown")[:200]
    root.db.session.add(root.PurchaseLot(
        purchase_id=purchase.id,
        strain_name=strain,
        weight_lbs=float(actual_weight),
        remaining_weight_lbs=float(actual_weight),
    ))
    return purchase


def _slack_filled_json_safe(filled: dict) -> dict:
    out: dict = {}
    for key, value in (filled or {}).items():
        if value is None:
            continue
        if isinstance(value, date) and not isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, datetime):
            out[key] = value.date().isoformat()
        else:
            out[key] = value
    return out


def _slack_resolution_json_safe(res: dict) -> dict:
    out: dict = {}
    for key, value in (res or {}).items():
        if value is None:
            continue
        if isinstance(value, date) and not isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, datetime):
            out[key] = value.date().isoformat()
        elif isinstance(value, (bool, int, float)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


def _slack_normalize_match_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _slack_name_tokens(value: str, *, alias: bool = False) -> list[str]:
    tokens = [
        token for token in re.split(r"[^a-z0-9]+", (value or "").strip().lower())
        if token and len(token) > 1
    ]
    if alias:
        tokens = [token for token in tokens if token not in SLACK_SUPPLIER_ALIAS_STOPWORDS]
    return tokens


def _slack_normalize_supplier_alias(value: str) -> str:
    return " ".join(_slack_name_tokens(value, alias=True))


def _slack_normalize_strain_name(value: str) -> str:
    return " ".join(_slack_name_tokens(value))


def _slack_token_overlap_score(left_tokens: list[str], right_tokens: list[str]) -> int:
    if not left_tokens or not right_tokens:
        return 0
    overlap = set(left_tokens) & set(right_tokens)
    if not overlap:
        return 0
    coverage = len(overlap) / max(len(set(left_tokens)), len(set(right_tokens)))
    return int(round(coverage * 100))


def _slack_build_supplier_candidate(source_raw: str, supplier) -> dict | None:
    if not supplier:
        return None
    source_norm = _slack_normalize_match_name(source_raw)
    supplier_norm = _slack_normalize_match_name(supplier.name)
    source_alias = _slack_normalize_supplier_alias(source_raw)
    supplier_alias = _slack_normalize_supplier_alias(supplier.name)
    source_tokens = _slack_name_tokens(source_raw, alias=True)
    supplier_tokens = _slack_name_tokens(supplier.name, alias=True)
    score = 0
    reason = ""
    exact = False
    if source_norm and source_norm == supplier_norm:
        score = 100
        reason = "exact name"
        exact = True
    elif source_alias and source_alias == supplier_alias:
        score = 96
        reason = "normalized alias"
    else:
        overlap = _slack_token_overlap_score(source_tokens, supplier_tokens)
        if overlap <= 0:
            return None
        score = 55 + min(35, overlap // 2)
        if supplier_alias and source_alias and (
            supplier_alias.startswith(source_alias) or source_alias.startswith(supplier_alias)
        ):
            score += 8
            reason = "prefix alias match"
        else:
            reason = "token overlap"
    score = min(score, 100)
    return {
        "id": supplier.id,
        "name": supplier.name,
        "score": score,
        "match_reason": reason,
        "exact": exact,
        "requires_confirmation": score < 96,
    }


def _slack_supplier_exact_name_match(source_raw: str, supplier) -> bool:
    if not supplier:
        return False
    return (
        _slack_normalize_match_name(source_raw) == _slack_normalize_match_name(supplier.name)
        or _slack_normalize_supplier_alias(source_raw) == _slack_normalize_supplier_alias(supplier.name)
    )


def _slack_build_strain_candidate(
    raw_strain: str,
    candidate_name: str,
    *,
    supplier_ids: set[str] | None = None,
    candidate_supplier_ids: set[str] | None = None,
    candidate_supplier_names: list[str] | None = None,
    uses: int = 0,
) -> dict | None:
    raw_norm = _slack_normalize_strain_name(raw_strain)
    candidate_norm = _slack_normalize_strain_name(candidate_name)
    if not (raw_norm and candidate_norm):
        return None
    raw_tokens = _slack_name_tokens(raw_strain)
    candidate_tokens = _slack_name_tokens(candidate_name)
    score = 0
    reason = ""
    if raw_norm == candidate_norm:
        score = 100
        reason = "exact strain"
    else:
        overlap = _slack_token_overlap_score(raw_tokens, candidate_tokens)
        if overlap <= 0:
            return None
        score = 55 + min(30, overlap // 2)
        if candidate_norm.startswith(raw_norm) or raw_norm.startswith(candidate_norm):
            score += 10
            reason = "prefix strain"
        else:
            reason = "token overlap"
    supplier_ids = supplier_ids or set()
    candidate_supplier_ids = candidate_supplier_ids or set()
    supplier_match = bool(supplier_ids and candidate_supplier_ids and (supplier_ids & candidate_supplier_ids))
    if supplier_match:
        score += 8
        if reason == "token overlap":
            reason = "supplier-weighted overlap"
    score += min(int(uses), 6)
    score = min(score, 100)
    return {
        "name": candidate_name,
        "score": score,
        "match_reason": reason,
        "supplier_match": supplier_match,
        "supplier_names": candidate_supplier_names or [],
        "requires_confirmation": score < 96,
    }
