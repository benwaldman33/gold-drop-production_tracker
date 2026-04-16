from __future__ import annotations

from datetime import datetime, timezone

from flask_login import current_user

from models import AuditLog, db


def log_audit(action, entity_type, entity_id, details=None, user_id=None):
    uid = user_id or (current_user.id if getattr(current_user, "is_authenticated", False) else None)
    audit = AuditLog(
        user_id=uid,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(audit)
