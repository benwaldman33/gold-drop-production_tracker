"""Shared purchase status transition policy helpers."""

from __future__ import annotations


COMMITTED_STATUSES = frozenset({"committed", "delivered"})


def require_approval_for_on_hand_status(
    new_status: str,
    is_approved: bool,
    on_hand_statuses: set[str] | frozenset[str] | tuple[str, ...],
) -> None:
    """Raise when attempting to move into on-hand without purchase approval."""
    if new_status in on_hand_statuses and not is_approved:
        raise ValueError(
            f"Cannot set status to \"{new_status.replace('_', ' ').title()}\" — "
            "this purchase has not been approved yet. Approve it first, then change status."
        )


def validate_pipeline_commitment_transition(
    prev_status: str | None,
    new_status: str,
    can_approve_purchase: bool,
) -> tuple[bool, bool]:
    """Validate commitment transitions and return (enters_commitment, leaves_commitment)."""
    enters_commitment = new_status == "committed" and prev_status not in COMMITTED_STATUSES
    leaves_commitment = (prev_status in COMMITTED_STATUSES) and new_status not in COMMITTED_STATUSES
    if enters_commitment or leaves_commitment:
        if not can_approve_purchase:
            raise ValueError(
                "Only Super Admin or users with purchase approval permission can move a batch "
                "to or from Committed / Delivered."
            )
    return enters_commitment, leaves_commitment


def validate_delivered_requires_prior_commitment(prev_status: str | None, new_status: str) -> None:
    """Enforce Delivered can only follow Committed (or stay Delivered)."""
    if new_status == "delivered" and prev_status not in ("committed", "delivered", None):
        raise ValueError(
            "Material cannot be marked as Delivered without first being Committed. "
            "Move the batch to Committed, then to Delivered."
        )
