from __future__ import annotations

import json
import re
from datetime import datetime, date, timezone

from gold_drop.list_state import app_display_zoneinfo
from models import SystemSetting

SLACK_IMPORT_KIND_FILTER_CHOICES = (
    ("all", "All kinds"),
    ("yield_report", "yield_report"),
    ("production_log", "production_log"),
    ("biomass_intake", "biomass_intake"),
    ("unknown", "unknown"),
)
SLACK_IMPORT_TEXT_FILTER_OPS = (
    ("contains", "contains"),
    ("not_contains", "does not contain"),
    ("equals", "equals"),
)
SLACK_IMPORT_TEXT_OPS_ALLOWED = frozenset({"contains", "not_contains", "equals"})

SLACK_RUN_MAPPINGS_KEY = "slack_run_field_mappings"
SLACK_MAPPING_ALLOWED_SOURCE_KEYS = frozenset({
    "__message_ts__",
    "slack_message_date",
    "strain", "source", "bio_lbs", "bio_weight_lbs", "wet_thca_g", "wet_hte_g", "wet_total_g",
    "yield_pct_mentioned", "reactor", "notes_line", "message_kind",
    "end_time", "mixer_time", "flush_time_start", "recovery_at", "flush_at",
    "manifest_raw", "manifest_id_normalized", "manifest_wt_lbs", "actual_wt_lbs", "discrepancy_lbs",
    "intake_received_date", "intake_order_date",
})
SLACK_MAPPING_ALLOWED_TARGET_FIELDS = frozenset({
    "run_date", "reactor_number", "load_source_reactors", "bio_in_reactor_lbs", "bio_in_house_lbs", "grams_ran",
    "wet_thca_g", "wet_hte_g", "dry_thca_g", "dry_hte_g",
    "overall_yield_pct", "thca_yield_pct", "hte_yield_pct",
    "butane_in_house_lbs", "solvent_ratio", "system_temp", "fuel_consumption",
    "run_type", "notes",
})
RUN_PREVIEW_RECOMMENDED_FIELDS = ("run_date", "reactor_number", "bio_in_reactor_lbs")
SLACK_RUN_MAPPING_MAX_FORM_ROWS = 80
SLACK_MAPPING_MESSAGE_KINDS = frozenset({"yield_report", "production_log", "biomass_intake", "unknown"})
SLACK_MAPPING_TRANSFORM_TYPES = (
    "passthrough", "slack_ts_to_date", "from_iso_date", "to_float", "to_reactor_int", "multiply", "prefix", "suffix",
)
SLACK_MAPPING_SOURCE_HELP = {
    "__message_ts__": "Slack message time (raw ts) -> run date",
    "slack_message_date": "Calendar date from Slack post time (YYYY-MM-DD in derived_json; use with from_iso_date -> run_date)",
    "strain": "Parsed strain (yield / production templates)",
    "source": "Parsed source/supplier line",
    "bio_lbs": "Bio lbs (yield template)",
    "bio_weight_lbs": "Bio weight lbs (production template)",
    "wet_thca_g": "Wet THCA (g)",
    "wet_hte_g": "Wet HTE (g)",
    "wet_total_g": "Wet total (g)",
    "yield_pct_mentioned": "Yield % from text",
    "reactor": "Reactor token (e.g. A) - map twice for load source + equipment #",
    "notes_line": "Parsed notes line",
    "message_kind": "Classifier string as data (rare)",
    "end_time": "Line End Time: ...",
    "mixer_time": "Line Mixer Time: ...",
    "flush_time_start": "Line Flush Time Start: ...",
    "recovery_at": "Line Recovery at: ...",
    "flush_at": "Line Flush at: ...",
}
SLACK_MAPPING_SOURCE_META = {
    "__message_ts__": {"label": "Slack message timestamp", "description": SLACK_MAPPING_SOURCE_HELP["__message_ts__"]},
    "slack_message_date": {"label": "Slack message date", "description": SLACK_MAPPING_SOURCE_HELP["slack_message_date"]},
    "strain": {"label": "Strain", "description": SLACK_MAPPING_SOURCE_HELP["strain"]},
    "source": {"label": "Source / supplier line", "description": SLACK_MAPPING_SOURCE_HELP["source"]},
    "bio_lbs": {"label": "Biomass lbs (yield template)", "description": SLACK_MAPPING_SOURCE_HELP["bio_lbs"]},
    "bio_weight_lbs": {"label": "Biomass weight lbs (production template)", "description": SLACK_MAPPING_SOURCE_HELP["bio_weight_lbs"]},
    "wet_thca_g": {"label": "Wet THCA (g)", "description": SLACK_MAPPING_SOURCE_HELP["wet_thca_g"]},
    "wet_hte_g": {"label": "Wet HTE (g)", "description": SLACK_MAPPING_SOURCE_HELP["wet_hte_g"]},
    "wet_total_g": {"label": "Wet total (g)", "description": SLACK_MAPPING_SOURCE_HELP["wet_total_g"]},
    "yield_pct_mentioned": {"label": "Yield % mentioned", "description": SLACK_MAPPING_SOURCE_HELP["yield_pct_mentioned"]},
    "reactor": {"label": "Reactor token", "description": SLACK_MAPPING_SOURCE_HELP["reactor"]},
    "notes_line": {"label": "Notes line", "description": SLACK_MAPPING_SOURCE_HELP["notes_line"]},
    "message_kind": {"label": "Message kind", "description": SLACK_MAPPING_SOURCE_HELP["message_kind"]},
    "end_time": {"label": "End time", "description": SLACK_MAPPING_SOURCE_HELP["end_time"]},
    "mixer_time": {"label": "Mixer time", "description": SLACK_MAPPING_SOURCE_HELP["mixer_time"]},
    "flush_time_start": {"label": "Flush start time", "description": SLACK_MAPPING_SOURCE_HELP["flush_time_start"]},
    "recovery_at": {"label": "Recovery at", "description": SLACK_MAPPING_SOURCE_HELP["recovery_at"]},
    "flush_at": {"label": "Flush at", "description": SLACK_MAPPING_SOURCE_HELP["flush_at"]},
    "manifest_raw": {"label": "Manifest raw", "description": "Raw manifest text from a biomass intake message."},
    "manifest_id_normalized": {"label": "Manifest ID normalized", "description": "Normalized manifest identifier derived from the Slack intake message."},
    "manifest_wt_lbs": {"label": "Manifest weight lbs", "description": "Manifest weight from the intake message."},
    "actual_wt_lbs": {"label": "Actual weight lbs", "description": "Actual received weight from the intake message."},
    "discrepancy_lbs": {"label": "Discrepancy lbs", "description": "Difference between manifest and actual weight."},
    "intake_received_date": {"label": "Intake received date", "description": "Received date parsed from a biomass intake message."},
    "intake_order_date": {"label": "Intake order date", "description": "Order/intake date parsed from a biomass intake message."},
}
SLACK_MAPPING_TARGET_HELP = {
    "run_date": "Run date",
    "reactor_number": "Processing reactor 1-3 (use to_reactor_int)",
    "load_source_reactors": "Biomass load A/B/A+B (string; pair with reactor source)",
    "bio_in_reactor_lbs": "Lbs in reactor",
    "bio_in_house_lbs": "Bio in house",
    "grams_ran": "Grams ran",
    "wet_thca_g": "Wet THCA (g)",
    "wet_hte_g": "Wet HTE (g)",
    "dry_thca_g": "Dry THCA (g)",
    "dry_hte_g": "Dry HTE (g)",
    "overall_yield_pct": "Overall yield %",
    "thca_yield_pct": "THCA yield %",
    "hte_yield_pct": "HTE yield %",
    "butane_in_house_lbs": "Butane in house",
    "solvent_ratio": "Solvent ratio",
    "system_temp": "System temp",
    "fuel_consumption": "Fuel consumption",
    "run_type": "Run type (string)",
    "notes": "Notes (concatenates multiple rules)",
}
SLACK_MAPPING_RUN_TARGET_META = {
    "run_date": {"label": "Run date", "description": SLACK_MAPPING_TARGET_HELP["run_date"]},
    "reactor_number": {"label": "Reactor number", "description": SLACK_MAPPING_TARGET_HELP["reactor_number"]},
    "load_source_reactors": {"label": "Load source reactors", "description": SLACK_MAPPING_TARGET_HELP["load_source_reactors"]},
    "bio_in_reactor_lbs": {"label": "Biomass in reactor lbs", "description": SLACK_MAPPING_TARGET_HELP["bio_in_reactor_lbs"]},
    "bio_in_house_lbs": {"label": "Biomass in house lbs", "description": SLACK_MAPPING_TARGET_HELP["bio_in_house_lbs"]},
    "grams_ran": {"label": "Grams ran", "description": SLACK_MAPPING_TARGET_HELP["grams_ran"]},
    "wet_thca_g": {"label": "Wet THCA (g)", "description": SLACK_MAPPING_TARGET_HELP["wet_thca_g"]},
    "wet_hte_g": {"label": "Wet HTE (g)", "description": SLACK_MAPPING_TARGET_HELP["wet_hte_g"]},
    "dry_thca_g": {"label": "Dry THCA (g)", "description": SLACK_MAPPING_TARGET_HELP["dry_thca_g"]},
    "dry_hte_g": {"label": "Dry HTE (g)", "description": SLACK_MAPPING_TARGET_HELP["dry_hte_g"]},
    "overall_yield_pct": {"label": "Overall yield %", "description": SLACK_MAPPING_TARGET_HELP["overall_yield_pct"]},
    "thca_yield_pct": {"label": "THCA yield %", "description": SLACK_MAPPING_TARGET_HELP["thca_yield_pct"]},
    "hte_yield_pct": {"label": "HTE yield %", "description": SLACK_MAPPING_TARGET_HELP["hte_yield_pct"]},
    "butane_in_house_lbs": {"label": "Butane in house lbs", "description": SLACK_MAPPING_TARGET_HELP["butane_in_house_lbs"]},
    "solvent_ratio": {"label": "Solvent ratio", "description": SLACK_MAPPING_TARGET_HELP["solvent_ratio"]},
    "system_temp": {"label": "System temperature", "description": SLACK_MAPPING_TARGET_HELP["system_temp"]},
    "fuel_consumption": {"label": "Fuel consumption", "description": SLACK_MAPPING_TARGET_HELP["fuel_consumption"]},
    "run_type": {"label": "Run type", "description": SLACK_MAPPING_TARGET_HELP["run_type"]},
    "notes": {"label": "Notes", "description": SLACK_MAPPING_TARGET_HELP["notes"]},
}
SLACK_MAPPING_KIND_PRESETS = (
    ("all", "All message kinds"),
    ("yield_report", "yield_report only"),
    ("production_log", "production_log only"),
    ("biomass_intake", "biomass_intake only"),
    ("unknown", "unknown only"),
    ("yield_report,production_log", "yield_report + production_log"),
)
SLACK_MAPPING_ALLOWED_DESTINATIONS = frozenset({
    "run", "biomass", "purchase", "inventory", "photo_library", "supplier", "strain", "cost",
})
SLACK_MAPPING_DESTINATION_CHOICES = (
    ("run", "Runs (preview active)"),
    ("biomass", "Biomass Pipeline"),
    ("purchase", "Purchases"),
    ("inventory", "Inventory"),
    ("photo_library", "Photo Library"),
    ("supplier", "Suppliers"),
    ("strain", "Strains"),
    ("cost", "Costs"),
)
SLACK_MAPPING_DESTINATION_TARGET_META = {
    "run": SLACK_MAPPING_RUN_TARGET_META,
    "biomass": {
        "supplier_name": {"label": "Supplier name", "description": "Supplier/farm name for a future biomass pipeline mapping."},
        "strain": {"label": "Strain", "description": "Strain name for a future biomass pipeline mapping."},
        "availability_date": {"label": "Availability date", "description": "Date the biomass is expected to be available."},
        "declared_weight_lbs": {"label": "Declared weight lbs", "description": "Declared biomass weight in pounds."},
        "declared_price_per_lb": {"label": "Declared price per lb", "description": "Expected or declared price per pound."},
        "testing_notes": {"label": "Testing notes", "description": "Notes about testing or COA status."},
        "queue_placement": {"label": "Queue placement", "description": "Biomass queue placement such as indoor/outdoor/aggregate."},
        "notes": {"label": "Notes", "description": "General biomass pipeline notes."},
    },
    "purchase": {
        "supplier_name": {"label": "Supplier name", "description": "Supplier/farm name on the purchase record."},
        "purchase_date": {"label": "Purchase date", "description": "Purchase or order date."},
        "delivery_date": {"label": "Delivery date", "description": "Actual or expected delivery date."},
        "batch_id": {"label": "Batch ID", "description": "Batch or manifest identifier."},
        "stated_weight_lbs": {"label": "Stated weight lbs", "description": "Invoice or stated biomass weight."},
        "actual_weight_lbs": {"label": "Actual weight lbs", "description": "Actual received biomass weight."},
        "stated_potency_pct": {"label": "Stated potency %", "description": "Declared potency percentage."},
        "tested_potency_pct": {"label": "Tested potency %", "description": "Lab-tested potency percentage."},
        "price_per_lb": {"label": "Price per lb", "description": "Purchase price per pound."},
        "total_cost": {"label": "Total cost", "description": "Total purchase amount."},
        "harvest_date": {"label": "Harvest date", "description": "Harvest date if known."},
        "storage_note": {"label": "Storage note", "description": "Storage / handling note."},
        "license_info": {"label": "License info", "description": "License or compliance information."},
        "coa_status_text": {"label": "COA status", "description": "COA or testing status text."},
        "queue_placement": {"label": "Queue placement", "description": "Biomass queue placement."},
        "clean_or_dirty": {"label": "Clean or dirty", "description": "Clean / dirty classification."},
        "indoor_outdoor": {"label": "Indoor / outdoor", "description": "Cultivation environment classification."},
        "notes": {"label": "Notes", "description": "General purchase notes."},
        "strain": {"label": "Strain", "description": "Primary strain label for the purchase."},
    },
    "inventory": {
        "tracking_id": {"label": "Tracking ID", "description": "Lot tracking identifier."},
        "strain_name": {"label": "Strain name", "description": "Lot strain name."},
        "location": {"label": "Location", "description": "Current lot location."},
        "floor_state": {"label": "Floor state", "description": "Operational floor state for the lot."},
        "prep_state": {"label": "Prep state", "description": "Preparation state such as milled / not milled."},
        "potency_pct": {"label": "Potency %", "description": "Lot potency percentage."},
        "milled": {"label": "Milled", "description": "Whether the lot is milled."},
        "notes": {"label": "Notes", "description": "Lot-level notes."},
    },
    "photo_library": {
        "category": {"label": "Category", "description": "Photo library category."},
        "tags": {"label": "Tags", "description": "Comma-separated tags."},
        "caption": {"label": "Caption", "description": "Photo caption or summary."},
        "source_context": {"label": "Source context", "description": "What workflow the photo came from."},
        "notes": {"label": "Notes", "description": "Library note or description."},
    },
    "supplier": {
        "name": {"label": "Supplier name", "description": "Supplier or farm name."},
        "contact_name": {"label": "Contact name", "description": "Primary supplier contact."},
        "contact_phone": {"label": "Contact phone", "description": "Primary supplier phone number."},
        "contact_email": {"label": "Contact email", "description": "Primary supplier email."},
        "location": {"label": "Location", "description": "Supplier location."},
        "license_info": {"label": "License info", "description": "Supplier licensing or compliance details."},
        "notes": {"label": "Notes", "description": "Supplier notes."},
    },
    "strain": {
        "name": {"label": "Strain name", "description": "Displayed strain name."},
        "canonical_name": {"label": "Canonical strain name", "description": "Canonicalized name used for mapping and cleanup."},
        "supplier_name": {"label": "Supplier name", "description": "Supplier associated with the strain."},
        "notes": {"label": "Notes", "description": "Strain notes or metadata."},
    },
    "cost": {
        "cost_type": {"label": "Cost type", "description": "Cost category such as solvent or personnel."},
        "name": {"label": "Cost name", "description": "Cost entry name."},
        "total_cost": {"label": "Total cost", "description": "Total amount for the cost entry."},
        "start_date": {"label": "Start date", "description": "Cost effective start date."},
        "end_date": {"label": "End date", "description": "Cost effective end date."},
        "notes": {"label": "Notes", "description": "Cost notes."},
    },
}
SLACK_NON_RUN_TARGET_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SLACK_MAPPING_NON_RUN_TARGET_HINT = (
    "Snake_case field label for this module (real columns come when that destination ships)."
)


def _slack_mapping_grid_row_count(rules: list | None) -> int:
    n = len(rules) if rules else 0
    return min(SLACK_RUN_MAPPING_MAX_FORM_ROWS, max(2, n + 2))


def _slack_run_mappings_template_kwargs(rules: list, rules_json: str) -> dict:
    source_choices = [
        {
            "value": key,
            "label": f"{meta['label']} ({key})",
        }
        for key, meta in sorted(SLACK_MAPPING_SOURCE_META.items(), key=lambda item: item[1]["label"].lower())
    ]
    destination_target_choices = {
        dest: [
            {
                "value": key,
                "label": f"{meta['label']} ({key})",
            }
            for key, meta in sorted(meta_map.items(), key=lambda item: item[1]["label"].lower())
        ]
        for dest, meta_map in SLACK_MAPPING_DESTINATION_TARGET_META.items()
    }
    destination_target_values = {
        dest: sorted(meta_map.keys())
        for dest, meta_map in SLACK_MAPPING_DESTINATION_TARGET_META.items()
    }
    target_help = {}
    for meta_map in SLACK_MAPPING_DESTINATION_TARGET_META.values():
        for key, meta in meta_map.items():
            target_help[key] = meta["description"]
    return {
        "rules": rules,
        "rules_json": rules_json,
        "source_choices": source_choices,
        "source_keys": sorted(SLACK_MAPPING_ALLOWED_SOURCE_KEYS),
        "target_fields": sorted(SLACK_MAPPING_ALLOWED_TARGET_FIELDS),
        "run_target_choices": destination_target_choices["run"],
        "destination_target_choices": destination_target_choices,
        "destination_target_values": destination_target_values,
        "destination_choices": SLACK_MAPPING_DESTINATION_CHOICES,
        "destination_choices_meta": [{"value": v, "label": lbl} for v, lbl in SLACK_MAPPING_DESTINATION_CHOICES],
        "destination_values": sorted(SLACK_MAPPING_ALLOWED_DESTINATIONS),
        "kind_presets": SLACK_MAPPING_KIND_PRESETS,
        "kind_presets_meta": [{"value": v, "label": lbl} for v, lbl in SLACK_MAPPING_KIND_PRESETS],
        "transform_types": SLACK_MAPPING_TRANSFORM_TYPES,
        "source_help": SLACK_MAPPING_SOURCE_HELP,
        "target_help": target_help,
        "non_run_target_hint": SLACK_MAPPING_NON_RUN_TARGET_HINT,
        "rule_slots": _slack_mapping_grid_row_count(rules),
        "rule_slots_max": SLACK_RUN_MAPPING_MAX_FORM_ROWS,
    }


def _default_slack_run_field_rules():
    return [
        {"message_kinds": [], "source_key": "__message_ts__", "target_field": "run_date", "transform": {"type": "slack_ts_to_date"}},
        {"message_kinds": ["yield_report", "production_log"], "source_key": "strain", "target_field": "notes", "transform": {"type": "prefix", "value": "Strain: "}},
        {"message_kinds": ["yield_report"], "source_key": "bio_lbs", "target_field": "bio_in_reactor_lbs", "transform": {"type": "to_float"}},
        {"message_kinds": ["production_log"], "source_key": "bio_weight_lbs", "target_field": "bio_in_reactor_lbs", "transform": {"type": "to_float"}},
        {"message_kinds": ["production_log"], "source_key": "reactor", "target_field": "reactor_number", "transform": {"type": "to_reactor_int"}},
        {"message_kinds": ["production_log"], "source_key": "reactor", "target_field": "load_source_reactors", "transform": {"type": "passthrough"}},
        {"message_kinds": ["yield_report"], "source_key": "wet_thca_g", "target_field": "wet_thca_g", "transform": {"type": "to_float"}},
        {"message_kinds": ["yield_report"], "source_key": "wet_hte_g", "target_field": "wet_hte_g", "transform": {"type": "to_float"}},
        {"message_kinds": ["yield_report"], "source_key": "yield_pct_mentioned", "target_field": "overall_yield_pct", "transform": {"type": "to_float"}},
        {"message_kinds": ["yield_report", "production_log"], "source_key": "source", "target_field": "notes", "transform": {"type": "prefix", "value": "Source: "}},
    ]


def _slack_ts_to_date_value(ts_str: str | None):
    try:
        ts = float(ts_str or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=app_display_zoneinfo()).date()
    except (OverflowError, OSError, ValueError):
        return None


def _ensure_slack_message_date_derived(derived: dict, message_ts: str) -> None:
    if derived.get("slack_message_date"):
        return
    ts_date = _slack_ts_to_date_value(message_ts)
    if ts_date is not None:
        derived["slack_message_date"] = ts_date.isoformat()


def _slack_ts_to_display_datetime_str(ts_str: str | None) -> str:
    if not (ts_str or "").strip():
        return "-"
    try:
        sec = float(str(ts_str).split(".")[0])
        utc_dt = datetime.fromtimestamp(sec, tz=timezone.utc)
        local_dt = utc_dt.astimezone(app_display_zoneinfo())
        return local_dt.strftime("%b %d, %Y %I:%M:%S %p %Z")
    except (ValueError, OSError, TypeError, OverflowError):
        return "-"


def _apply_slack_mapping_transform(raw_val, transform: dict | None, message_ts: str, source_key: str):
    t = (transform or {}).get("type") or "passthrough"
    if raw_val is None and source_key == "__message_ts__":
        raw_val = message_ts
    if t == "passthrough":
        return raw_val
    if t == "slack_ts_to_date":
        return _slack_ts_to_date_value(str(raw_val or message_ts or ""))
    if t == "from_iso_date":
        try:
            return datetime.strptime(str(raw_val or "").strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    if t == "to_float":
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            return None
    if t == "to_reactor_int":
        raw = str(raw_val or "").strip().upper()
        if raw in {"A", "1"}:
            return 1
        if raw in {"B", "2"}:
            return 2
        if raw in {"C", "3"}:
            return 3
        try:
            return int(raw)
        except ValueError:
            return None
    if t == "multiply":
        try:
            return float(raw_val) * float((transform or {}).get("value") or 1)
        except (TypeError, ValueError):
            return None
    if t == "prefix":
        val = str(raw_val or "").strip()
        return f"{(transform or {}).get('value') or ''}{val}" if val else None
    if t == "suffix":
        val = str(raw_val or "").strip()
        return f"{val}{(transform or {}).get('value') or ''}" if val else None
    return raw_val


def _validate_slack_run_field_rules(rules: list) -> None:
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule {i + 1}: each rule must be an object.")
        sk = (rule.get("source_key") or "").strip()
        tf = (rule.get("target_field") or "").strip()
        dest = (rule.get("destination") or "run").strip() or "run"
        if sk not in SLACK_MAPPING_ALLOWED_SOURCE_KEYS:
            raise ValueError(f"Rule {i + 1}: unknown source key {sk!r}.")
        if dest not in SLACK_MAPPING_ALLOWED_DESTINATIONS:
            raise ValueError(f"Rule {i + 1}: unknown destination {dest!r}.")
        if dest == "run":
            if tf not in SLACK_MAPPING_ALLOWED_TARGET_FIELDS:
                raise ValueError(f"Rule {i + 1}: target field {tf!r} is not allowed for Run preview.")
        elif not SLACK_NON_RUN_TARGET_FIELD_RE.match(tf):
            raise ValueError(f"Rule {i + 1}: non-run target field must be snake_case, got {tf!r}.")
        kinds = rule.get("message_kinds") or []
        if not isinstance(kinds, list):
            raise ValueError(f"Rule {i + 1}: message_kinds must be an array.")
        for k in kinds:
            if k not in SLACK_MAPPING_MESSAGE_KINDS:
                raise ValueError(f"Rule {i + 1}: unknown message kind {k!r}.")
        ttype = ((rule.get("transform") or {}).get("type") or "passthrough").strip()
        if ttype not in SLACK_MAPPING_TRANSFORM_TYPES:
            raise ValueError(f"Rule {i + 1}: unsupported transform {ttype!r}.")


def _preview_slack_to_run_fields(derived: dict, message_ts: str, message_kind: str, rules: list) -> dict:
    src = dict(derived or {})
    _ensure_slack_message_date_derived(src, message_ts)
    filled: dict[str, object] = {}
    notes_values: list[str] = []
    consumed_keys: set[str] = set()
    run_consumed_keys: set[str] = set()
    for rule in rules or []:
        kinds = rule.get("message_kinds") or []
        if kinds and message_kind not in kinds:
            continue
        source_key = (rule.get("source_key") or "").strip()
        target_field = (rule.get("target_field") or "").strip()
        dest = (rule.get("destination") or "run").strip() or "run"
        if source_key == "__message_ts__":
            raw_val = message_ts
        else:
            raw_val = src.get(source_key)
        val = _apply_slack_mapping_transform(raw_val, rule.get("transform"), message_ts, source_key)
        if val in (None, ""):
            continue
        consumed_keys.add(source_key)
        if dest != "run":
            continue
        run_consumed_keys.add(source_key)
        if target_field == "notes":
            sval = str(val).strip()
            if sval:
                notes_values.append(sval)
        else:
            filled[target_field] = val
    if notes_values:
        filled["notes"] = "\n".join(notes_values)
    unmapped_keys = sorted(
        k for k, v in src.items()
        if k not in consumed_keys and k != "message_kind" and v not in (None, "", [])
    )
    missing_recommended = [k for k in RUN_PREVIEW_RECOMMENDED_FIELDS if not filled.get(k)]
    return {
        "filled": filled,
        "unmapped_keys": unmapped_keys,
        "missing_recommended": missing_recommended,
        "consumed_run_keys": sorted(run_consumed_keys),
        "consumed_all_keys": sorted(consumed_keys),
    }


def _slack_coverage_label(preview: dict) -> str:
    filled = preview.get("filled") or {}
    if not filled:
        return "none"
    if (preview.get("unmapped_keys") or []) or (preview.get("missing_recommended") or []):
        return "partial"
    return "full"


def _load_slack_run_field_rules() -> list:
    raw = SystemSetting.get(SLACK_RUN_MAPPINGS_KEY)
    if not raw or not str(raw).strip():
        return _default_slack_run_field_rules()
    try:
        data = json.loads(raw)
        rules = data.get("rules")
        if isinstance(rules, list) and len(rules) > 0:
            return rules
    except (json.JSONDecodeError, TypeError):
        pass
    return _default_slack_run_field_rules()


def _slack_non_run_mapping_rule_count(rules: list) -> int:
    count = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        destination = (rule.get("destination") or "run").strip() or "run"
        if destination != "run" and destination in SLACK_MAPPING_ALLOWED_DESTINATIONS:
            count += 1
    return count


def _slack_mapping_transform_from_form(ttype: str, arg: str) -> dict:
    ttype = (ttype or "passthrough").strip()
    if ttype not in SLACK_MAPPING_TRANSFORM_TYPES:
        ttype = "passthrough"
    arg = (arg or "").strip()
    if ttype == "multiply":
        try:
            factor = float(arg) if arg else 1.0
        except ValueError:
            factor = 1.0
        return {"type": "multiply", "factor": factor}
    if ttype in ("prefix", "suffix"):
        return {"type": ttype, "value": arg}
    return {"type": ttype}


def _slack_run_rules_from_mapping_form(form) -> list:
    rules: list = []
    for i in range(SLACK_RUN_MAPPING_MAX_FORM_ROWS):
        source_key = (form.get(f"rule_source_{i}") or "").strip()
        destination = (form.get(f"rule_destination_{i}") or "run").strip() or "run"
        if destination not in SLACK_MAPPING_ALLOWED_DESTINATIONS:
            destination = "run"
        target_pick = (form.get(f"rule_target_select_{i}") or "").strip()
        target_custom = (form.get(f"rule_target_text_{i}") or "").strip()
        if destination == "run":
            target_field = target_pick
        elif target_pick == "__custom__":
            target_field = target_custom
        else:
            target_field = target_pick or target_custom
        if not source_key or not target_field:
            continue
        kinds_raw = (form.get(f"rule_kinds_{i}") or "all").strip()
        if kinds_raw.lower() in ("", "all"):
            message_kinds: list = []
        else:
            message_kinds = [kind.strip() for kind in kinds_raw.split(",") if kind.strip()]
        transform_type = (form.get(f"rule_transform_{i}") or "passthrough").strip()
        transform_arg = form.get(f"rule_transform_arg_{i}", "") or ""
        transform = _slack_mapping_transform_from_form(transform_type, transform_arg)
        row = {
            "message_kinds": message_kinds,
            "source_key": source_key,
            "target_field": target_field,
            "transform": transform,
        }
        if destination != "run":
            row["destination"] = destination
        rules.append(row)
    return rules


def _slack_rule_kind_select_value(kinds: list | None) -> str:
    if not kinds:
        return "all"
    return ",".join(kinds)


def _slack_message_needs_resolution_ui(derived: dict) -> bool:
    kind = (derived.get("message_kind") or "").strip()
    if kind == "biomass_intake":
        return False
    return bool((derived.get("source") or "").strip() or (derived.get("strain") or "").strip())


def _slack_imports_row_matches_kind_text(kind_filter: str, text_filter_raw: str, text_op: str, eff_kind: str, raw_text: str | None) -> bool:
    if kind_filter != "all" and eff_kind != kind_filter:
        return False
    tf = (text_filter_raw or "").strip().lower()
    if not tf:
        return True
    hay = (raw_text or "").strip().lower()
    if text_op == "equals":
        return hay == tf
    if text_op == "not_contains":
        return tf not in hay
    return tf in hay


def _slack_default_bio_weight_lbs(derived: dict) -> float:
    for key in ("bio_lbs", "bio_weight_lbs", "actual_wt_lbs", "manifest_wt_lbs"):
        try:
            val = float(derived.get(key))
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return 0.0


def _slack_default_availability_date_iso(derived: dict, message_ts: str) -> str | None:
    raw = (derived.get("intake_received_date") or derived.get("slack_message_date") or "").strip()
    if raw:
        return raw[:10]
    ts_date = _slack_ts_to_date_value(message_ts)
    return ts_date.isoformat() if ts_date else None


def _slack_strip_slack_links(value: str | None) -> str:
    txt = str(value or "")
    txt = re.sub(r"<tel:([^|>]+)\|[^>]+>", r"\1", txt)
    txt = re.sub(r"<([^|>]+)\|[^>]+>", r"\1", txt)
    txt = txt.replace("<", "").replace(">", "")
    return txt.strip()


def _slack_parse_mdy_date(value: str | None) -> date | None:
    txt = (value or "").strip()
    if not txt:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _slack_intake_manifest_normalized(manifest_raw: str | None) -> str:
    txt = _slack_strip_slack_links(manifest_raw)
    return re.sub(r"[^0-9A-Za-z]+", "", txt)


def _derive_slack_production_message(raw: str) -> dict:
    text = (raw or "").strip()
    lower = text.lower()
    out: dict[str, object] = {"message_kind": "unknown"}

    def grab(pattern: str):
        m = re.search(pattern, text, re.I)
        return (m.group(1).strip() if m else None)

    if "manifest" in lower and ("actual wt" in lower or "manifest wt" in lower):
        out["message_kind"] = "biomass_intake"
        received = _slack_parse_mdy_date(grab(r"(?:received|intake)\s*:\s*([^\n]+)"))
        ordered = _slack_parse_mdy_date(grab(r"order\s*:\s*([^\n]+)"))
        if received:
            out["intake_received_date"] = received.isoformat()
        if ordered:
            out["intake_order_date"] = ordered.isoformat()
        source = grab(r"source\s*:\s*([^\n]+)")
        if source:
            out["source"] = source
        strain = grab(r"strain\s*:\s*([^\n]+)")
        if strain:
            out["strain"] = strain
        manifest_raw = grab(r"manifest\s*#?\s*:\s*([^\n]+)") or grab(r"manifest\s*#\s*([^\n]+)")
        if manifest_raw:
            out["manifest_raw"] = manifest_raw
            out["manifest_id_normalized"] = _slack_intake_manifest_normalized(manifest_raw)
        for pat, key in (
            (r"manifest\s*wt\s*:\s*([\d.]+)", "manifest_wt_lbs"),
            (r"actual\s*wt\s*:\s*([\d.]+)", "actual_wt_lbs"),
            (r"discrepancy\s*:\s*([-\d.]+)", "discrepancy_lbs"),
        ):
            raw_num = grab(pat)
            if raw_num is None:
                continue
            try:
                out[key] = float(raw_num)
            except ValueError:
                pass
        return out

    if re.search(r"reactor\s*:", lower) and re.search(r"strain\s*:", lower):
        out["message_kind"] = "production_log"
    elif re.search(r"wet\s*thca", lower) or re.search(r"wet\s*hte", lower):
        out["message_kind"] = "yield_report"

    for pat, dkey in (
        (r"strain\s*:\s*([^\n]+)", "strain"),
        (r"source\s*:\s*([^\n]+)", "source"),
        (r"wet\s*thca\s*:\s*([\d.]+)", "wet_thca_g"),
        (r"wet\s*hte\s*:\s*([\d.]+)", "wet_hte_g"),
        (r"wet\s*total\s*:\s*([\d.]+)", "wet_total_g"),
        (r"yield\s*%?\s*:\s*([\d.]+)", "yield_pct_mentioned"),
    ):
        v = grab(pat)
        if not v:
            continue
        if dkey in {"strain", "source"}:
            out[dkey] = v
        else:
            try:
                out[dkey] = float(v)
            except ValueError:
                pass

    rm = re.search(r"reactor\s*:\s*([A-Za-z0-9]+)", text, re.I)
    if rm:
        out["reactor"] = rm.group(1).upper()
    wm = re.search(r"bio\s*(?:wt|lbs?)\s*:\s*([\d.]+)", text, re.I)
    if wm:
        try:
            out["bio_weight_lbs"] = float(wm.group(1))
            out["bio_lbs"] = float(wm.group(1))
        except ValueError:
            pass
    notes = grab(r"notes\s*:\s*([^\n]+)")
    if notes:
        out["notes_line"] = notes
    for pat, dkey in (
        (r"end\s*time\s*:\s*([^\n]+)", "end_time"),
        (r"mixer\s*time\s*:\s*([^\n]+)", "mixer_time"),
        (r"flush\s*time\s*start\s*:\s*([^\n]+)", "flush_time_start"),
        (r"recovery\s+at\s*:\s*([^\n]+)", "recovery_at"),
        (r"flush\s+at\s*:\s*([^\n]+)", "flush_at"),
    ):
        v = grab(pat)
        if v:
            out[dkey] = v.strip()
    return out
