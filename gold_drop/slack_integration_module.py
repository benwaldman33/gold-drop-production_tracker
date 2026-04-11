from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime


SLACK_SYNC_CHANNEL_SLOTS = 6


def slack_enabled(root) -> bool:
    return (root.SystemSetting.get("slack_enabled", "0") or "0").strip() in ("1", "true", "yes", "on")


def slack_webhook_url(root) -> str | None:
    return (root.SystemSetting.get("slack_webhook_url", "") or "").strip() or None


def slack_signing_secret(root) -> str | None:
    return (root.SystemSetting.get("slack_signing_secret", "") or "").strip() or None


def slack_bot_token(root) -> str | None:
    return (root.SystemSetting.get("slack_bot_token", "") or "").strip() or None


def slack_channel(root) -> str | None:
    return (root.SystemSetting.get("slack_default_channel", "") or "").strip() or None


def notify_slack(root, text_value: str) -> None:
    _post_slack_webhook(root, text_value)
    _post_slack_api_message(root, text_value)


def _post_slack_webhook(root, text_value: str) -> None:
    webhook = slack_webhook_url(root)
    if not webhook or not slack_enabled(root):
        return
    payload = json.dumps({"text": text_value}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=6):
            pass
    except Exception:
        root.app.logger.exception("Slack webhook send failed")


def _post_slack_api_message(root, text_value: str) -> None:
    token = slack_bot_token(root)
    channel = slack_channel(root)
    if not token or not channel or not slack_enabled(root):
        return
    payload = json.dumps({"channel": channel, "text": text_value}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6):
            pass
    except Exception:
        root.app.logger.exception("Slack API send failed")


def verify_slack_signature(root, req) -> bool:
    secret = slack_signing_secret(root)
    if not secret:
        return False
    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > 60 * 5:
        return False
    raw_body = req.get_data(cache=True, as_text=False) or b""
    basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    digest = "v0=" + hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def slack_web_api(root, token: str, method: str, params: dict) -> dict:
    body = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _slack_looks_like_conversation_id(hint: str) -> bool:
    value = (hint or "").strip()
    if len(value) < 9:
        return False
    if value[0].upper() not in "CGD":
        return False
    return all(ch.isalnum() for ch in value[1:])


def slack_resolve_channel_id(root, token: str, channel_setting: str) -> str | None:
    hint = (channel_setting or "").strip()
    if not hint:
        return None
    if _slack_looks_like_conversation_id(hint):
        return hint
    name = hint.lstrip("#").strip().lower()
    cursor = None
    for _ in range(40):
        params: dict[str, str] = {"types": "public_channel,private_channel", "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        data = slack_web_api(root, token, "conversations.list", params)
        if not data.get("ok"):
            root.app.logger.warning("Slack conversations.list failed: %s", data.get("error"))
            return None
        for channel in data.get("channels") or []:
            if (channel.get("name") or "").lower() == name:
                return channel.get("id")
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    return None


def ensure_sync_configs(root) -> None:
    count = root.SlackChannelSyncConfig.query.count()
    if count == 0:
        default_channel = (root.SystemSetting.get("slack_default_channel") or "").strip()
        for index in range(SLACK_SYNC_CHANNEL_SLOTS):
            hint = default_channel if index == 0 else ""
            root.db.session.add(root.SlackChannelSyncConfig(slot_index=index, channel_hint=hint))
        root.db.session.commit()
        return
    have = {row.slot_index for row in root.SlackChannelSyncConfig.query.all()}
    added = False
    for index in range(SLACK_SYNC_CHANNEL_SLOTS):
        if index not in have:
            root.db.session.add(root.SlackChannelSyncConfig(slot_index=index, channel_hint=""))
            added = True
    if added:
        root.db.session.commit()


def slack_ingest_channel_history(root, token: str, channel_id: str, oldest: str, ingested_by: str) -> tuple[int, int, str | None, str | None]:
    new_rows = 0
    scanned = 0
    max_ts_seen: str | None = None
    cursor = None
    for _page in range(50):
        params: dict[str, str] = {"channel": channel_id, "limit": "200", "oldest": oldest}
        if cursor:
            params["cursor"] = cursor
        data = slack_web_api(root, token, "conversations.history", params)
        if not data.get("ok"):
            return new_rows, scanned, max_ts_seen, str(data.get("error", "unknown"))
        for msg in data.get("messages") or []:
            scanned += 1
            if msg.get("subtype") in ("channel_join", "channel_leave", "channel_topic", "channel_purpose"):
                continue
            ts = msg.get("ts")
            if not ts:
                continue
            if max_ts_seen is None or float(ts) > float(max_ts_seen):
                max_ts_seen = str(ts)
            if root.SlackIngestedMessage.query.filter_by(channel_id=channel_id, message_ts=str(ts)).first():
                continue
            txt = (msg.get("text") or "").strip()
            if not txt:
                if msg.get("files"):
                    txt = "[attachment or file only]"
                elif msg.get("blocks"):
                    txt = "[block kit / rich layout - see raw in Slack]"
                else:
                    for attachment in msg.get("attachments") or []:
                        if not isinstance(attachment, dict):
                            continue
                        piece = (attachment.get("text") or attachment.get("fallback") or "").strip()
                        if piece:
                            txt = piece
                            break
                if not txt:
                    continue
            derived = root._derive_slack_production_message(txt)
            root._ensure_slack_message_date_derived(derived, str(ts))
            root.db.session.add(root.SlackIngestedMessage(
                channel_id=channel_id,
                message_ts=str(ts),
                slack_user_id=(msg.get("user") or None),
                raw_text=txt,
                message_kind=derived.get("message_kind"),
                derived_json=json.dumps(derived),
                ingested_by=ingested_by,
            ))
            new_rows += 1
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    return new_rows, scanned, max_ts_seen, None


def handle_settings_form(root) -> None:
    slack_map = {
        "slack_enabled": "Enable Slack integration",
        "slack_webhook_url": "Slack incoming webhook URL",
        "slack_signing_secret": "Slack signing secret",
        "slack_bot_token": "Slack bot token",
        "slack_default_channel": "Default Slack channel",
    }
    for key, desc in slack_map.items():
        if key == "slack_enabled":
            value = "1" if root.request.form.get("slack_enabled") else "0"
        else:
            value = (root.request.form.get(key) or "").strip()
        existing = root.db.session.get(root.SystemSetting, key)
        if existing:
            existing.value = value
        else:
            root.db.session.add(root.SystemSetting(key=key, value=value, description=desc))
    ensure_sync_configs(root)
    for index in range(SLACK_SYNC_CHANNEL_SLOTS):
        hint = (root.request.form.get(f"sync_ch_{index}") or "").strip()
        row = root.SlackChannelSyncConfig.query.filter_by(slot_index=index).first()
        if not row:
            row = root.SlackChannelSyncConfig(slot_index=index, channel_hint=hint)
            root.db.session.add(row)
        else:
            old = (row.channel_hint or "").strip()
            row.channel_hint = hint
            if old != hint:
                row.resolved_channel_id = None
                row.last_watermark_ts = None
    root.db.session.commit()
    root.flash("Slack integration saved (webhook, tokens, default channel, and up to six history-sync channels).", "success")


def register_routes(app, root):
    @root.admin_required
    def settings_slack_sync_channel():
        return settings_slack_sync_channel_view(root)

    @root.slack_importer_required
    def settings_slack_imports():
        return settings_slack_imports_view(root)

    @root.slack_importer_required
    def settings_slack_import_triage_hide(msg_id):
        return settings_slack_import_triage_hide_view(root, msg_id)

    @root.slack_importer_required
    def settings_slack_import_triage_unhide(msg_id):
        return settings_slack_import_triage_unhide_view(root, msg_id)

    @root.slack_importer_required
    def settings_slack_import_preview(msg_id):
        return settings_slack_import_preview_view(root, msg_id)

    @root.slack_importer_required
    def settings_slack_import_apply_run(msg_id):
        return settings_slack_import_apply_run_view(root, msg_id)

    @root.slack_importer_required
    def settings_slack_import_apply_intake(msg_id):
        return settings_slack_import_apply_intake_view(root, msg_id)

    @root.admin_required
    def settings_slack_run_mappings():
        return settings_slack_run_mappings_view(root)

    def slack_events():
        return slack_events_view(root)

    def slack_command():
        return slack_command_view(root)

    def slack_interactivity():
        return slack_interactivity_view(root)

    app.add_url_rule("/settings/slack_sync_channel", endpoint="settings_slack_sync_channel", view_func=settings_slack_sync_channel, methods=["POST"])
    app.add_url_rule("/settings/slack-imports", endpoint="settings_slack_imports", view_func=settings_slack_imports)
    app.add_url_rule("/settings/slack-imports/<msg_id>/triage-hide", endpoint="settings_slack_import_triage_hide", view_func=settings_slack_import_triage_hide, methods=["POST"])
    app.add_url_rule("/settings/slack-imports/<msg_id>/triage-unhide", endpoint="settings_slack_import_triage_unhide", view_func=settings_slack_import_triage_unhide, methods=["POST"])
    app.add_url_rule("/settings/slack-imports/<msg_id>/preview", endpoint="settings_slack_import_preview", view_func=settings_slack_import_preview)
    app.add_url_rule("/settings/slack-imports/<msg_id>/apply-run", endpoint="settings_slack_import_apply_run", view_func=settings_slack_import_apply_run, methods=["GET", "POST"])
    app.add_url_rule("/settings/slack-imports/<msg_id>/apply-intake", endpoint="settings_slack_import_apply_intake", view_func=settings_slack_import_apply_intake, methods=["POST"])
    app.add_url_rule("/settings/slack-run-mappings", endpoint="settings_slack_run_mappings", view_func=settings_slack_run_mappings, methods=["GET", "POST"])
    app.add_url_rule("/api/slack/events", endpoint="slack_events", view_func=slack_events, methods=["POST"])
    app.add_url_rule("/api/slack/command", endpoint="slack_command", view_func=slack_command, methods=["POST"])
    app.add_url_rule("/api/slack/interactivity", endpoint="slack_interactivity", view_func=slack_interactivity, methods=["POST"])


def settings_slack_sync_channel_view(root):
    days_raw = (root.request.form.get("sync_days") or "90").strip()
    try:
        days = int(days_raw)
    except ValueError:
        days = 90
    days = max(1, min(365, days))
    root.session["slack_sync_days"] = days
    root.session.permanent = True

    token = slack_bot_token(root)
    if not token:
        root.flash("Set Bot Token in Slack settings first.", "error")
        return root.settings_module.settings_redirect(root)
    oldest_window = str(time.time() - days * 86400)
    try:
        ensure_sync_configs(root)
        configs = [
            cfg for cfg in root.SlackChannelSyncConfig.query.order_by(root.SlackChannelSyncConfig.slot_index).all()
            if (cfg.channel_hint or "").strip()
        ]
        if not configs:
            root.flash(
                "No channels configured for history sync. Under Settings -> Slack Integration, fill in at least one "
                "channel (e.g. #biomass-intake) in Channel history sync and save.",
                "error",
            )
            return root.settings_module.settings_redirect(root)
        total_new = 0
        total_scanned = 0
        errors: list[str] = []
        audit_channels: list[dict] = []
        for cfg in configs:
            hint = cfg.channel_hint.strip()
            channel_id = slack_resolve_channel_id(root, token, hint)
            if not channel_id:
                root.app.logger.warning(
                    "Slack sync: could not resolve channel hint %r (need #name bot can list, or full ID starting with C/G/D)",
                    hint,
                )
                errors.append(hint)
                continue
            cfg.resolved_channel_id = channel_id
            oldest = (cfg.last_watermark_ts or "").strip() or oldest_window
            new_rows, scanned, max_ts_seen, err = slack_ingest_channel_history(
                root, token, channel_id, oldest, root.current_user.id,
            )
            if err:
                errors.append(f"{hint}:{err}")
                root.db.session.commit()
                continue
            total_new += new_rows
            total_scanned += scanned
            if max_ts_seen:
                cfg.last_watermark_ts = max_ts_seen
            elif not (cfg.last_watermark_ts or "").strip():
                cfg.last_watermark_ts = str(time.time())
            root.db.session.commit()
            audit_channels.append({"hint": hint, "channel_id": channel_id, "new": new_rows, "scanned": scanned})
        if errors and not audit_channels:
            root.flash(
                "Could not sync any channel. Check names or IDs, invite the bot, and add OAuth scopes "
                "channels:history, channels:read (private: groups:history, groups:read). "
                "If you paste a channel ID, use the full ID (public C..., private G..., DM D...). "
                f"Details: {', '.join(errors)}",
                "error",
            )
            return root.settings_module.settings_redirect(root)
        root.log_audit(
            "slack_channel_sync",
            "slack",
            "multi",
            details=json.dumps({"days": days, "new": total_new, "scanned": total_scanned, "channels": audit_channels, "errors": errors}),
        )
        msg = (
            f"Slack sync: {total_new} new message(s) saved, {total_scanned} row(s) seen "
            f"across {len(audit_channels)} channel(s)."
        )
        if total_new == 0 and total_scanned > 0:
            msg += " (Everything seen was already imported, or had no ingestible text - increase Days back only helps before the first successful sync for that channel, or after clearing that channel row to reset the cursor.)"
        if errors:
            msg += " Could not sync: " + "; ".join(errors) + "."
        msg += " Open Slack imports to review parsed fields."
        root.flash(msg, "success")
    except urllib.error.HTTPError as exc:
        root.db.session.rollback()
        root.flash(f"Slack HTTP error: {exc}", "error")
    except Exception as exc:
        root.db.session.rollback()
        root.app.logger.exception("Slack channel sync failed")
        root.flash(f"Slack sync failed: {exc}", "error")
    return root.settings_module.settings_redirect(root)


def settings_slack_imports_view(root):
    ep = "settings_slack_imports"
    redir = root._list_filters_clear_redirect(ep)
    if redir:
        return redir

    bucket = root.session.setdefault(root.LIST_FILTERS_SESSION_KEY, {})
    prev = dict(bucket.get(ep) or {})
    allowed_kinds = {choice[0] for choice in root.SLACK_IMPORT_KIND_FILTER_CHOICES}

    def _norm_promo(value):
        value = (value or "all").strip().lower()
        return value if value in ("all", "not_linked", "linked") else "all"

    def _norm_cov(value):
        value = (value or "all").strip().lower()
        return value if value in ("all", "full", "partial", "none") else "all"

    def _norm_kind(value):
        value = (value or "all").strip().lower()
        return value if value in allowed_kinds else "all"

    if len(root.request.args) == 0:
        start_raw = (prev.get("start_date") or "").strip()
        end_raw = (prev.get("end_date") or "").strip()
        channel_pick = [c for c in (prev.get("channel_ids_csv") or "").split(",") if (c or "").strip()]
        promotion = _norm_promo(prev.get("promotion"))
        coverage_f = _norm_cov(prev.get("coverage"))
        kind_filter = _norm_kind(prev.get("kind_filter"))
        text_filter_raw = (prev.get("text_filter") or "").strip()
        text_op = (prev.get("text_op") or "contains").strip().lower()
        if text_op not in root.SLACK_IMPORT_TEXT_OPS_ALLOWED:
            text_op = "contains"
        include_hidden = (prev.get("include_hidden") or "").strip().lower() in ("1", "true", "yes", "on")
    elif root.request.args.get("filter_form") == "1":
        start_raw = (root.request.args.get("start_date") or "").strip()
        end_raw = (root.request.args.get("end_date") or "").strip()
        channel_pick = [c for c in root.request.args.getlist("channel_id") if (c or "").strip()]
        promotion = _norm_promo(root.request.args.get("promotion"))
        coverage_f = _norm_cov(root.request.args.get("coverage"))
        kind_filter = _norm_kind(root.request.args.get("kind_filter"))
        text_filter_raw = (root.request.args.get("text_filter") or "").strip()
        text_op = (root.request.args.get("text_op") or "contains").strip().lower()
        if text_op not in root.SLACK_IMPORT_TEXT_OPS_ALLOWED:
            text_op = "contains"
        include_hidden = (root.request.args.get("include_hidden") or "").strip().lower() in ("1", "true", "yes", "on")
    else:
        start_raw = ((root.request.args.get("start_date") if "start_date" in root.request.args else prev.get("start_date", "")) or "").strip()
        end_raw = ((root.request.args.get("end_date") if "end_date" in root.request.args else prev.get("end_date", "")) or "").strip()
        if "channel_id" in root.request.args:
            channel_pick = [c for c in root.request.args.getlist("channel_id") if (c or "").strip()]
        else:
            channel_pick = [c for c in (prev.get("channel_ids_csv") or "").split(",") if (c or "").strip()]
        promotion = _norm_promo(root.request.args.get("promotion", prev.get("promotion")))
        coverage_f = _norm_cov(root.request.args.get("coverage", prev.get("coverage")))
        kind_filter = _norm_kind(root.request.args.get("kind_filter", prev.get("kind_filter")))
        text_filter_raw = ((root.request.args.get("text_filter") if "text_filter" in root.request.args else prev.get("text_filter", "")) or "").strip()
        text_op = ((root.request.args.get("text_op") if "text_op" in root.request.args else prev.get("text_op", "contains")) or "contains").strip().lower()
        if text_op not in root.SLACK_IMPORT_TEXT_OPS_ALLOWED:
            text_op = "contains"
        if "include_hidden" in root.request.args:
            include_hidden = (root.request.args.get("include_hidden") or "").strip().lower() in ("1", "true", "yes", "on")
        else:
            include_hidden = (prev.get("include_hidden") or "").strip().lower() in ("1", "true", "yes", "on")

    bucket[ep] = {
        "start_date": start_raw,
        "end_date": end_raw,
        "channel_ids_csv": ",".join(sorted(channel_pick)),
        "promotion": promotion,
        "coverage": coverage_f,
        "kind_filter": kind_filter,
        "text_filter": text_filter_raw,
        "text_op": text_op,
        "include_hidden": "1" if include_hidden else "",
    }
    root.session.modified = True

    slack_filters_active = bool(
        start_raw or end_raw or channel_pick or promotion != "all" or coverage_f != "all"
        or kind_filter != "all" or text_filter_raw or text_op != "contains" or include_hidden
    )

    try:
        start_d = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_d = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_d, end_d = None, None

    hint_by_resolved = root._slack_resolved_channel_hint_map()
    channel_ids = [
        cid for (cid,) in root.db.session.query(root.SlackIngestedMessage.channel_id).distinct().order_by(
            root.SlackIngestedMessage.channel_id,
        ).all() if cid
    ]
    channel_options = [{"id": cid, "label": root._slack_channel_filter_label(cid, hint_by_resolved)} for cid in channel_ids]
    channel_options.sort(key=lambda item: (item["label"].lower(), item["id"]))

    rules = root._load_slack_run_field_rules()
    link_index = root._slack_linked_run_ids_index()
    pool = root.SlackIngestedMessage.query.order_by(root.desc(root.SlackIngestedMessage.message_ts)).limit(2500).all()
    rows: list = []
    for row in pool:
        ts_date = root._slack_ts_to_date_value(row.message_ts)
        if start_d and ts_date is not None and ts_date < start_d:
            continue
        if end_d and ts_date is not None and ts_date > end_d:
            continue
        if channel_pick and row.channel_id not in channel_pick:
            continue
        if not include_hidden and bool(getattr(row, "hidden_from_imports", False)):
            continue
        linked = link_index.get((row.channel_id, row.message_ts), [])
        if promotion == "not_linked" and linked:
            continue
        if promotion == "linked" and not linked:
            continue
        derived = root._derive_slack_production_message(row.raw_text or "")
        eff_kind = (derived.get("message_kind") or row.message_kind or "unknown").strip()
        if not root._slack_imports_row_matches_kind_text(kind_filter, text_filter_raw, text_op, eff_kind, row.raw_text):
            continue
        preview = root._preview_slack_to_run_fields(derived, str(row.message_ts or ""), eff_kind, rules)
        cov = root._slack_coverage_label(preview)
        if coverage_f != "all" and cov != coverage_f:
            continue
        row.derived = derived
        row._preview = preview
        row._linked_run_ids = linked
        row._coverage = cov
        rows.append(row)
        if len(rows) >= 500:
            break

    return root.render_template(
        "slack_imports.html",
        rows=rows,
        start_date=start_raw,
        end_date=end_raw,
        channel_pick=channel_pick,
        promotion=promotion,
        coverage=coverage_f,
        channel_options=channel_options,
        kind_filter=kind_filter,
        text_filter=text_filter_raw,
        text_op=text_op,
        slack_import_kind_choices=root.SLACK_IMPORT_KIND_FILTER_CHOICES,
        slack_import_text_ops=root.SLACK_IMPORT_TEXT_FILTER_OPS,
        include_hidden=include_hidden,
        list_filters_active=slack_filters_active,
        clear_filters_url=root.url_for("settings_slack_imports", clear_filters=1),
    )


def settings_slack_import_triage_hide_view(root, msg_id):
    row = root.db.session.get(root.SlackIngestedMessage, msg_id)
    if not row:
        root.flash("Slack import row not found.", "error")
        return root.redirect(root.url_for("settings_slack_imports"))
    row.hidden_from_imports = True
    root.log_audit(
        "slack_import_triage_hide",
        "slack_ingested_message",
        row.id,
        details=json.dumps({"channel_id": row.channel_id, "message_ts": row.message_ts}),
    )
    root.db.session.commit()
    root.flash(
        'Message hidden from this list for everyone. Check "Include hidden messages" in filters to find it and restore.',
        "success",
    )
    return root._redirect_settings_slack_imports_preserved()


def settings_slack_import_triage_unhide_view(root, msg_id):
    row = root.db.session.get(root.SlackIngestedMessage, msg_id)
    if not row:
        root.flash("Slack import row not found.", "error")
        return root.redirect(root.url_for("settings_slack_imports"))
    row.hidden_from_imports = False
    root.log_audit(
        "slack_import_triage_unhide",
        "slack_ingested_message",
        row.id,
        details=json.dumps({"channel_id": row.channel_id, "message_ts": row.message_ts}),
    )
    root.db.session.commit()
    root.flash("Message is visible in the imports list again.", "success")
    return root._redirect_settings_slack_imports_preserved()


def settings_slack_import_preview_view(root, msg_id):
    row = root.db.session.get(root.SlackIngestedMessage, msg_id)
    if not row:
        root.flash("Slack import row not found.", "error")
        return root.redirect(root.url_for("settings_slack_imports"))
    derived = root._derive_slack_production_message(row.raw_text or "")
    eff_kind = derived.get("message_kind") or row.message_kind
    rules = root._load_slack_run_field_rules()
    preview = root._preview_slack_to_run_fields(derived, str(row.message_ts or ""), eff_kind, rules)
    link_index = root._slack_linked_run_ids_index()
    linked = link_index.get((row.channel_id, row.message_ts), [])
    dup_run = root._first_run_for_slack_message(row.channel_id, row.message_ts)
    needs_res = root._slack_message_needs_resolution_ui(derived)
    source_raw = (derived.get("source") or "").strip()
    strain_raw = (derived.get("strain") or "").strip()
    suppliers_all = root.Supplier.query.filter(root.Supplier.is_active.is_(True)).order_by(root.Supplier.name).all()
    supplier_candidates = root._slack_supplier_candidates_for_source(source_raw) if source_raw else []
    default_supplier_id = ""
    if supplier_candidates and not supplier_candidates[0].get("requires_confirmation"):
        default_supplier_id = str(supplier_candidates[0]["id"])
    strain_candidates = root._slack_strain_candidates_for_name(
        strain_raw,
        supplier_ids=[str(candidate["id"]) for candidate in supplier_candidates[:3]],
    ) if strain_raw else []
    default_canonical_strain = ""
    if strain_candidates and not strain_candidates[0].get("requires_confirmation"):
        default_canonical_strain = str(strain_candidates[0]["name"])
    default_availability = root._slack_default_availability_date_iso(derived, str(row.message_ts or "")) or ""
    default_bio_weight = root._slack_default_bio_weight_lbs(derived)
    intake_candidates: list = []
    intake_manifest_key = ""
    if (derived.get("message_kind") or "") == "biomass_intake":
        intake_manifest_key = (derived.get("manifest_id_normalized") or "").strip()
        if intake_manifest_key:
            intake_candidates = root._find_intake_purchase_candidates(intake_manifest_key)
    slack_channel_label = root._slack_channel_filter_label(row.channel_id, root._slack_resolved_channel_hint_map())
    return root.render_template(
        "slack_import_preview.html",
        row=row,
        slack_channel_label=slack_channel_label,
        derived=derived,
        preview=preview,
        rules=rules,
        non_run_mapping_rule_count=root._slack_non_run_mapping_rule_count(rules),
        coverage_label=root._slack_coverage_label(preview),
        linked_run_ids=linked,
        duplicate_run=dup_run,
        needs_resolution_ui=needs_res,
        supplier_all=suppliers_all,
        supplier_candidates=supplier_candidates,
        default_supplier_id=default_supplier_id,
        source_raw=source_raw,
        strain_raw=strain_raw,
        strain_candidates=strain_candidates,
        default_canonical_strain=default_canonical_strain,
        default_availability_date=default_availability,
        default_bio_weight=default_bio_weight,
        intake_candidates=intake_candidates,
        intake_manifest_key=intake_manifest_key,
        can_edit_purchase=bool(root.current_user.can_edit),
    )


def settings_slack_import_apply_run_view(root, msg_id):
    row = root.db.session.get(root.SlackIngestedMessage, msg_id)
    if not row:
        root.flash("Slack import row not found.", "error")
        return root.redirect(root.url_for("settings_slack_imports"))

    derived = root._derive_slack_production_message(row.raw_text or "")
    if root.request.method == "GET" and root._slack_message_needs_resolution_ui(derived):
        root.flash(
            "This Slack message includes source: and/or strain: - use the preview page, then apply using the form "
            "(supplier / optional biomass) before a run is opened.",
            "warning",
        )
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))

    resolution = None
    if root.request.method == "POST":
        resolution, res_err = root._slack_resolution_from_apply_form(
            root.request.form,
            derived=derived,
            message_ts=str(row.message_ts or ""),
        )
        if res_err:
            root.flash(res_err, "error")
            return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))

    confirm = root.request.form.get("slack_apply_confirm_duplicate") == "1" or (
        root.request.method == "GET" and (root.request.args.get("confirm") or "").strip() == "1"
    )
    dup = root._first_run_for_slack_message(row.channel_id, row.message_ts)
    if dup and not confirm:
        passthrough = root._slack_apply_form_passthrough(root.request.form) if root.request.method == "POST" else None
        slack_channel_label = root._slack_channel_filter_label(row.channel_id, root._slack_resolved_channel_hint_map())
        return root.render_template(
            "slack_import_apply_confirm.html",
            row=row,
            slack_channel_label=slack_channel_label,
            existing_run=dup,
            apply_passthrough=passthrough,
        )

    if dup and confirm:
        root.log_audit(
            "slack_duplicate_apply_confirm",
            "slack_ingested_message",
            row.id,
            details=json.dumps({
                "channel_id": row.channel_id,
                "message_ts": row.message_ts,
                "existing_run_id": dup.id,
            }),
        )
        root.db.session.commit()

    rules = root._load_slack_run_field_rules()
    eff_kind = derived.get("message_kind") or row.message_kind
    preview = root._preview_slack_to_run_fields(derived, str(row.message_ts or ""), eff_kind, rules)
    root._slack_run_prefill_put(
        msg_id=row.id,
        channel_id=row.channel_id,
        message_ts=row.message_ts,
        filled=preview.get("filled") or {},
        allow_duplicate=bool(dup and confirm),
        resolution=resolution,
    )
    root.flash("Opening new run with Slack prefilled fields. Review and save when ready.", "success")
    return root.redirect(root.url_for("run_new"))


def settings_slack_import_apply_intake_view(root, msg_id):
    if not root.current_user.can_edit:
        root.flash("Saving purchases requires User or Super Admin access.", "error")
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))
    row = root.db.session.get(root.SlackIngestedMessage, msg_id)
    if not row:
        root.flash("Slack import row not found.", "error")
        return root.redirect(root.url_for("settings_slack_imports"))
    derived = root._derive_slack_production_message(row.raw_text or "")
    if derived.get("message_kind") != "biomass_intake":
        root.flash("This message is not classified as a biomass intake report.", "error")
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))
    mkey = (derived.get("manifest_id_normalized") or "").strip()
    if not mkey:
        root.flash(
            "Could not parse a manifest / batch id (Manifest # ...). Check the message format or paste the id manually on the Purchase.",
            "error",
        )
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))
    manifest_wt = derived.get("manifest_wt_lbs")
    actual_wt = derived.get("actual_wt_lbs")
    if manifest_wt is None and actual_wt is None:
        root.flash("Manifest weight or actual weight is required in the Slack text.", "error")
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))
    if manifest_wt is None:
        manifest_wt = actual_wt
    if actual_wt is None:
        actual_wt = manifest_wt

    received = None
    if derived.get("intake_received_date"):
        try:
            received = datetime.strptime(str(derived["intake_received_date"])[:10], "%Y-%m-%d").date()
        except ValueError:
            received = None
    intake_order = None
    if derived.get("intake_order_date"):
        try:
            intake_order = datetime.strptime(str(derived["intake_order_date"])[:10], "%Y-%m-%d").date()
        except ValueError:
            intake_order = None
    intake_strain, intake_strain_err = root._slack_selected_canonical_strain(
        root.request.form,
        raw_strain=(derived.get("strain") or "").strip(),
        text_field="intake_strain_name",
        canonical_field="intake_canonical_strain",
        confirm_field="intake_confirm_fuzzy_strain",
        required_for_label="intake strain",
    )
    if intake_strain_err:
        root.flash(intake_strain_err, "error")
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))

    action = (root.request.form.get("intake_action") or "").strip()
    try:
        if action == "update":
            pid = (root.request.form.get("intake_purchase_id") or "").strip()
            if not pid:
                raise ValueError("Select which purchase to update.")
            purchase = root.db.session.get(root.Purchase, pid)
            if not purchase or purchase.deleted_at:
                raise ValueError("Purchase not found.")
            root._apply_slack_intake_update_purchase(
                purchase,
                derived,
                row,
                resolved_strain=intake_strain,
                manifest_wt=float(manifest_wt) if manifest_wt is not None else None,
                actual_wt=float(actual_wt) if actual_wt is not None else None,
                received=received,
            )
            root._purchase_sync_biomass_pipeline(purchase)
            root.log_audit(
                "update",
                "purchase",
                purchase.id,
                details=json.dumps({
                    "slack_biomass_intake": True,
                    "channel_id": row.channel_id,
                    "message_ts": row.message_ts,
                }),
            )
            root.db.session.commit()
            root.flash("Purchase updated from Slack biomass intake.", "success")
            return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))
        if action == "create":
            supplier = root._slack_intake_supplier_from_form(root.request.form)
            purchase = root._create_purchase_from_slack_intake(
                supplier,
                derived,
                row,
                resolved_strain=intake_strain,
                manifest_key=mkey,
                manifest_wt=float(manifest_wt),
                actual_wt=float(actual_wt),
                received=received,
                intake_order=intake_order,
            )
            root._purchase_sync_biomass_pipeline(purchase)
            root.db.session.commit()
            root.flash("Purchase created from Slack biomass intake.", "success")
            return root.redirect(root.url_for("purchase_edit", purchase_id=purchase.id))
        raise ValueError("Choose whether to update an existing purchase or create a new one.")
    except ValueError as exc:
        root.db.session.rollback()
        root.flash(str(exc), "error")
        return root.redirect(root.url_for("settings_slack_import_preview", msg_id=msg_id))


def settings_slack_run_mappings_view(root):
    if root.request.method == "POST":
        action = (root.request.form.get("action") or "").strip()
        if action == "reset_defaults":
            rules = root._default_slack_run_field_rules()
            blob = json.dumps({"rules": rules}, indent=2)
            existing = root.db.session.get(root.SystemSetting, root.SLACK_RUN_MAPPINGS_KEY)
            if existing:
                existing.value = blob
            else:
                root.db.session.add(root.SystemSetting(
                    key=root.SLACK_RUN_MAPPINGS_KEY,
                    value=blob,
                    description="Slack derived_json -> Run field preview mappings (Phase 1 JSON)",
                ))
            root.db.session.commit()
            root.flash("Restored default Slack -> Run mapping rules.", "success")
            return root.redirect(root.url_for("settings_slack_run_mappings"))

        if action == "save_json":
            raw_json = (root.request.form.get("rules_json") or "").strip()
            try:
                data = json.loads(raw_json)
                rules = data.get("rules")
                if not isinstance(rules, list):
                    raise ValueError('Top-level key "rules" must be a JSON array.')
                root._validate_slack_run_field_rules(rules)
            except (json.JSONDecodeError, ValueError) as exc:
                root.flash(f"Could not save JSON rules: {exc}", "error")
                rules = root._load_slack_run_field_rules()
                return root.render_template(
                    "slack_run_mappings.html",
                    **root._slack_run_mappings_template_kwargs(
                        rules,
                        raw_json or json.dumps({"rules": rules}, indent=2),
                    ),
                )
        else:
            rules = root._slack_run_rules_from_mapping_form(root.request.form)
            try:
                root._validate_slack_run_field_rules(rules)
            except ValueError as exc:
                root.flash(f"Could not save rules: {exc}", "error")
                return root.render_template(
                    "slack_run_mappings.html",
                    **root._slack_run_mappings_template_kwargs(rules, json.dumps({"rules": rules}, indent=2)),
                )
        blob = json.dumps({"rules": rules}, indent=2)
        existing = root.db.session.get(root.SystemSetting, root.SLACK_RUN_MAPPINGS_KEY)
        if existing:
            existing.value = blob
        else:
            root.db.session.add(root.SystemSetting(
                key=root.SLACK_RUN_MAPPINGS_KEY,
                value=blob,
                description="Slack derived_json -> Run field preview mappings (Phase 1 JSON)",
            ))
        root.db.session.commit()
        root.flash("Slack -> Run mapping rules saved. Previews use these rules on the next request.", "success")
        return root.redirect(root.url_for("settings_slack_run_mappings"))

    rules = root._load_slack_run_field_rules()
    pretty = json.dumps({"rules": rules}, indent=2)
    return root.render_template(
        "slack_run_mappings.html",
        **root._slack_run_mappings_template_kwargs(rules, pretty),
    )


def slack_events_view(root):
    if not verify_slack_signature(root, root.request):
        return "Unauthorized", 401
    payload = root.request.get_json(silent=True) or {}
    if payload.get("type") == "url_verification":
        return root.jsonify({"challenge": payload.get("challenge") or ""})
    if payload.get("type") == "event_callback":
        return "", 200
    return "", 200


def slack_command_view(root):
    if not verify_slack_signature(root, root.request):
        return "Unauthorized", 401
    cmd_text = (root.request.form.get("text") or "").strip().lower()
    if cmd_text.startswith("pending"):
        pending = root.FieldPurchaseSubmission.query.filter_by(status="pending").count()
        return root.jsonify({"response_type": "ephemeral", "text": f"Pending field submissions: {pending}"})
    if cmd_text.startswith("inventory"):
        on_hand = root.db.session.query(root.func.sum(root.PurchaseLot.remaining_weight_lbs)).join(root.Purchase).filter(
            root.PurchaseLot.remaining_weight_lbs > 0,
            root.PurchaseLot.deleted_at.is_(None),
            root.Purchase.deleted_at.is_(None),
            root.Purchase.status.in_(root.INVENTORY_ON_HAND_PURCHASE_STATUSES),
        ).scalar() or 0
        return root.jsonify({"response_type": "ephemeral", "text": f"Current biomass on hand: {on_hand:,.1f} lbs"})
    if cmd_text.startswith("export runs"):
        link = root.url_for("export_csv", entity="runs", _external=True)
        return root.jsonify({"response_type": "ephemeral", "text": f"Runs export: {link}"})
    return root.jsonify({"response_type": "ephemeral", "text": "Try: pending, inventory, export runs"})


def slack_interactivity_view(root):
    if not verify_slack_signature(root, root.request):
        return "Unauthorized", 401
    payload_raw = (root.request.form.get("payload") or "").strip()
    if not payload_raw:
        return "OK", 200
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return "OK", 200
    action = ((payload.get("actions") or [{}])[0].get("action_id") or "").strip()
    submission_id = ((payload.get("actions") or [{}])[0].get("value") or "").strip()
    if action in ("approve_submission", "reject_submission") and submission_id:
        root.log_audit("slack_action", "field_purchase_submission", submission_id, details=json.dumps({"action": action}))
        root.db.session.commit()
    return "OK", 200
