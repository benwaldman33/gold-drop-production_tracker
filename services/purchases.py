"""Purchase-domain service helpers extracted from route handlers."""

from __future__ import annotations

from datetime import datetime

from models import Purchase
from policies.purchase_status import (
    require_approval_for_on_hand_status,
    validate_delivered_requires_prior_commitment,
    validate_pipeline_commitment_transition,
)


def stamp_purchase_approval(purchase: Purchase, approver_user_id: str) -> None:
    """Apply approval stamp in one place to keep transitions consistent."""
    purchase.purchase_approved_at = datetime.utcnow()
    purchase.purchase_approved_by_user_id = approver_user_id


def validate_purchase_status_change_requires_approval(
    *,
    new_status: str,
    is_approved: bool,
    on_hand_statuses: set[str] | frozenset[str] | tuple[str, ...],
) -> None:
    """Enforce approval gating for direct purchase form status edits."""
    require_approval_for_on_hand_status(
        new_status=new_status,
        is_approved=is_approved,
        on_hand_statuses=on_hand_statuses,
    )


def apply_pipeline_stage_transition(
    purchase: Purchase,
    *,
    prev_status: str | None,
    new_status: str,
    can_approve_purchase: bool,
    approver_user_id: str,
) -> None:
    """Run pipeline transition policy checks and stamp approval on commitment entry."""
    validate_delivered_requires_prior_commitment(prev_status=prev_status, new_status=new_status)
    enters_commitment, _leaves_commitment = validate_pipeline_commitment_transition(
        prev_status=prev_status,
        new_status=new_status,
        can_approve_purchase=can_approve_purchase,
    )
    if enters_commitment:
        stamp_purchase_approval(purchase=purchase, approver_user_id=approver_user_id)
