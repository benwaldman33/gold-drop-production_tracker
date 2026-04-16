"""Purchase-domain service helpers extracted from route handlers."""

from __future__ import annotations

from datetime import datetime, timezone

from models import Purchase


def stamp_purchase_approval(purchase: Purchase, approver_user_id: str) -> None:
    """Apply approval stamp in one place to keep transitions consistent."""
    purchase.purchase_approved_at = datetime.now(timezone.utc)
    purchase.purchase_approved_by_user_id = approver_user_id
