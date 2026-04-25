from __future__ import annotations

import json
import urllib.error
import urllib.request

from datetime import datetime, timezone


NOTIFICATION_CLASS_LABELS = {
    "completions": "Completions",
    "warnings": "Warnings",
    "reminders": "Reminders",
}

NOTIFICATION_SEVERITY_LABELS = {
    "info": "Info",
    "warning": "Warning",
    "critical": "Critical",
}

SLACK_WEBHOOK_SETTING_BY_CLASS = {
    "completions": "slack_webhook_completions_url",
    "warnings": "slack_webhook_warnings_url",
    "reminders": "slack_webhook_reminders_url",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def supervisor_notifications_enabled(root) -> bool:
    raw = (root.SystemSetting.get("supervisor_notifications_enabled", "1") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def slack_notifications_enabled(root) -> bool:
    raw = (root.SystemSetting.get("slack_outbound_notifications_enabled", "0") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def manager_can_review(user) -> bool:
    if user is None:
        return False
    return bool(getattr(user, "is_super_admin", False) or getattr(user, "can_edit_purchases", False))


def _class_label(class_key: str) -> str:
    return NOTIFICATION_CLASS_LABELS.get(class_key, (class_key or "Notification").replace("_", " ").title())


def _severity_label(severity: str) -> str:
    return NOTIFICATION_SEVERITY_LABELS.get(severity, (severity or "Info").replace("_", " ").title())


def _slack_webhook_url(root, notification_class: str) -> str | None:
    setting_key = SLACK_WEBHOOK_SETTING_BY_CLASS.get(notification_class)
    if setting_key:
        candidate = (root.SystemSetting.get(setting_key, "") or "").strip()
        if candidate:
            return candidate
    return (root.SystemSetting.get("slack_webhook_url", "") or "").strip() or None


def _delivery_row(root, notification, *, delivery_type: str, target_label: str, status: str):
    row = root.NotificationDelivery(
        notification_id=notification.id,
        delivery_type=delivery_type,
        target_label=target_label,
        status=status,
        attempted_at=utc_now(),
    )
    root.db.session.add(row)
    return row


def _slack_message(notification) -> str:
    title = (notification.title or "").strip()
    message = (notification.message or "").strip()
    header = f"[{_class_label(notification.notification_class)} · {_severity_label(notification.severity)}]"
    if title and message:
        return f"{header} {title}\n{message}"
    if title:
        return f"{header} {title}"
    return f"{header} {message}"


def deliver_notification_to_slack(root, notification) -> None:
    target_url = _slack_webhook_url(root, notification.notification_class)
    target_label = notification.notification_class or "slack"
    if not slack_notifications_enabled(root) or not target_url:
        row = _delivery_row(root, notification, delivery_type="slack", target_label=target_label, status="skipped")
        row.error_message = "Slack outbound delivery disabled or webhook URL not configured."
        return

    row = _delivery_row(root, notification, delivery_type="slack", target_label=target_label, status="pending")
    body = json.dumps({"text": _slack_message(notification)}).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            row.status = "delivered"
            row.delivered_at = utc_now()
            row.response_code = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        row.status = "failed"
        row.response_code = int(exc.code or 0)
        row.error_message = str(exc)
        root.app.logger.exception("Slack notification delivery failed")
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)
        root.app.logger.exception("Slack notification delivery failed")


def create_notification(
    root,
    *,
    event_key: str,
    title: str,
    message: str,
    notification_class: str = "warnings",
    severity: str = "warning",
    run=None,
    booth_session=None,
    dedupe_key: str | None = None,
    operator_reason: str | None = None,
    auto_deliver: bool = True,
):
    if not supervisor_notifications_enabled(root):
        return None
    normalized_key = (event_key or "").strip() or "notification"
    normalized_dedupe = (dedupe_key or normalized_key).strip()
    if run is not None:
        existing = root.SupervisorNotification.query.filter(
            root.SupervisorNotification.run_id == run.id,
            root.SupervisorNotification.dedupe_key == normalized_dedupe,
            root.SupervisorNotification.status.in_(("open", "acknowledged")),
        ).order_by(root.SupervisorNotification.created_at.desc()).first()
        if existing is not None:
            existing.title = title
            existing.message = message
            existing.notification_class = notification_class
            existing.severity = severity
            existing.operator_reason = operator_reason or existing.operator_reason
            existing.updated_at = utc_now()
            return existing

    notification = root.SupervisorNotification(
        run_id=getattr(run, "id", None),
        booth_session_id=getattr(booth_session, "id", None),
        event_key=normalized_key,
        dedupe_key=normalized_dedupe,
        notification_class=notification_class,
        severity=severity,
        title=title,
        message=message,
        operator_reason=operator_reason,
        status="open",
    )
    root.db.session.add(notification)
    root.db.session.flush()
    if auto_deliver:
        deliver_notification_to_slack(root, notification)
    return notification


def resolve_matching_notifications(root, *, run=None, dedupe_keys: list[str] | tuple[str, ...], note: str | None = None) -> int:
    if run is None or not dedupe_keys:
        return 0
    rows = root.SupervisorNotification.query.filter(
        root.SupervisorNotification.run_id == run.id,
        root.SupervisorNotification.dedupe_key.in_(tuple(dedupe_keys)),
        root.SupervisorNotification.status.in_(("open", "acknowledged")),
    ).all()
    now = utc_now()
    for row in rows:
        row.status = "resolved"
        row.resolved_at = now
        row.resolution_note = note or row.resolution_note
        row.updated_at = now
    return len(rows)


def summarize_notifications(root, *, limit: int = 12) -> dict:
    open_query = root.SupervisorNotification.query.filter(
        root.SupervisorNotification.status.in_(("open", "acknowledged"))
    )
    open_rows = open_query.order_by(root.SupervisorNotification.created_at.desc()).limit(limit).all()
    return {
        "open_count": open_query.count(),
        "critical_count": open_query.filter(root.SupervisorNotification.severity == "critical").count(),
        "warning_count": open_query.filter(root.SupervisorNotification.severity == "warning").count(),
        "info_count": open_query.filter(root.SupervisorNotification.severity == "info").count(),
        "rows": [notification_row_payload(root, row) for row in open_rows],
    }


def notification_row_payload(root, row) -> dict:
    run = getattr(row, "run", None)
    deliveries = (
        row.deliveries.order_by(root.NotificationDelivery.attempted_at.desc()).all()
        if hasattr(row.deliveries, "order_by")
        else []
    )
    return {
        "id": row.id,
        "event_key": row.event_key,
        "notification_class": row.notification_class,
        "notification_class_label": _class_label(row.notification_class),
        "severity": row.severity,
        "severity_label": _severity_label(row.severity),
        "title": row.title,
        "message": row.message,
        "operator_reason": row.operator_reason,
        "status": row.status,
        "created_at": root.display_local_timestamp(row.created_at) if hasattr(root, "display_local_timestamp") else (row.created_at.isoformat() if row.created_at else ""),
        "acknowledged_at": root.display_local_timestamp(row.acknowledged_at) if hasattr(root, "display_local_timestamp") else (row.acknowledged_at.isoformat() if row.acknowledged_at else ""),
        "resolved_at": root.display_local_timestamp(row.resolved_at) if hasattr(root, "display_local_timestamp") else (row.resolved_at.isoformat() if row.resolved_at else ""),
        "acknowledged_by_name": row.acknowledged_by.display_name if getattr(row, "acknowledged_by", None) else None,
        "override_decision": row.override_decision,
        "override_reason": row.override_reason,
        "override_at": root.display_local_timestamp(row.override_at) if hasattr(root, "display_local_timestamp") else (row.override_at.isoformat() if row.override_at else ""),
        "override_by_name": row.override_by.display_name if getattr(row, "override_by", None) else None,
        "resolved_by_name": row.resolved_by.display_name if getattr(row, "resolved_by", None) else None,
        "run_id": row.run_id,
        "run_label": (
            f"{run.run_date.isoformat()} · Reactor {run.reactor_number}"
            if run is not None and getattr(run, "run_date", None) is not None
            else None
        ),
        "run_edit_url": root.url_for("run_edit", run_id=row.run_id) if row.run_id else None,
        "delivery_statuses": [
            {
                "type": item.delivery_type,
                "target_label": item.target_label,
                "status": item.status,
                "attempted_at": root.display_local_timestamp(item.attempted_at) if hasattr(root, "display_local_timestamp") else (item.attempted_at.isoformat() if item.attempted_at else ""),
                "error_message": item.error_message,
            }
            for item in deliveries[:3]
        ],
    }


def notification_rows_for_run(root, run, *, limit: int = 10) -> list[dict]:
    if run is None or getattr(run, "id", None) is None:
        return []
    rows = root.SupervisorNotification.query.filter_by(run_id=run.id).order_by(
        root.SupervisorNotification.created_at.desc()
    ).limit(limit).all()
    return [notification_row_payload(root, row) for row in rows]
