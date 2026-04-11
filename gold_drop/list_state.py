from __future__ import annotations

import re
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import redirect, request, session, url_for

from models import SlackChannelSyncConfig, SystemSetting

APP_DISPLAY_TIMEZONE_DEFAULT = "America/Los_Angeles"
APP_DISPLAY_TIMEZONE_CHOICES = (
    ("America/Los_Angeles", "Pacific - Los Angeles"),
    ("America/Vancouver", "Pacific - Vancouver"),
    ("America/Phoenix", "Mountain - Phoenix (no DST)"),
    ("America/Denver", "Mountain - Denver"),
    ("America/Chicago", "Central - Chicago"),
    ("America/New_York", "Eastern - New York"),
    ("America/Toronto", "Eastern - Toronto"),
    ("America/Anchorage", "Alaska"),
    ("Pacific/Honolulu", "Hawaii"),
    ("UTC", "UTC"),
)

LIST_FILTERS_SESSION_KEY = "list_filters_v1"


def app_display_timezone_name() -> str:
    try:
        raw = (SystemSetting.get("app_display_timezone", APP_DISPLAY_TIMEZONE_DEFAULT) or "").strip()
    except RuntimeError:
        raw = APP_DISPLAY_TIMEZONE_DEFAULT
    return raw or APP_DISPLAY_TIMEZONE_DEFAULT


def app_display_zoneinfo():
    for key in (app_display_timezone_name(), APP_DISPLAY_TIMEZONE_DEFAULT, "UTC"):
        k = (key or "").strip()
        if not k:
            continue
        try:
            return ZoneInfo(k)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            continue
    return timezone.utc


def slack_resolved_channel_hint_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for cfg in SlackChannelSyncConfig.query.order_by(SlackChannelSyncConfig.slot_index).all():
        cid = (cfg.resolved_channel_id or "").strip()
        hint = (cfg.channel_hint or "").strip()
        if cid and hint:
            out[cid] = hint
    return out


def slack_channel_filter_label(channel_id: str, hint_by_id: dict[str, str]) -> str:
    if not (channel_id or "").strip():
        return ""
    hint = (hint_by_id.get(channel_id) or "").strip()
    if not hint:
        return f"{channel_id} - set name in Settings -> Slack -> Channel history sync"
    if hint == channel_id or hint.lstrip("#").strip() == channel_id:
        return channel_id
    hnorm = hint.lstrip("#").strip()
    if " " not in hnorm and re.match(r"^[a-z0-9._-]+$", hnorm, re.I):
        disp = "#" + hnorm
    else:
        disp = hint
    return f"{disp} ({channel_id})"


def list_filters_clear_redirect(endpoint: str):
    if request.args.get("clear_filters") != "1":
        return None
    bucket = session.get(LIST_FILTERS_SESSION_KEY)
    if isinstance(bucket, dict):
        bucket.pop(endpoint, None)
        session.modified = True
    return redirect(url_for(endpoint))


def list_filters_merge(endpoint: str, keys: tuple[str, ...]) -> dict[str, str]:
    bucket = session.setdefault(LIST_FILTERS_SESSION_KEY, {})
    prev = dict(bucket.get(endpoint) or {})
    if not any(k in request.args for k in keys):
        merged = {k: (prev.get(k) or "").strip() for k in keys}
    else:
        merged = {k: (prev.get(k) or "").strip() for k in keys}
        for k in keys:
            if k in request.args:
                merged[k] = (request.args.get(k) or "").strip()
    bucket[endpoint] = {k: merged[k] for k in keys}
    session.modified = True
    return merged


def runs_list_filters_active(m: dict[str, str]) -> bool:
    try:
        if int(m.get("page") or 1) > 1:
            return True
    except ValueError:
        pass
    if (m.get("sort") or "run_date") != "run_date":
        return True
    if (m.get("order") or "desc") != "desc":
        return True
    for k in ("search", "start_date", "end_date", "supplier_id", "min_potency", "max_potency", "hte_stage"):
        if (m.get(k) or "").strip():
            return True
    return False
