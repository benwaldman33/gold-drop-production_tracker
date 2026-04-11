"""Unit tests for purchase service orchestration helpers."""

from __future__ import annotations

import pytest

from models import Purchase
from services.purchases import (
    apply_pipeline_stage_transition,
    validate_purchase_status_change_requires_approval,
)


def test_validate_purchase_status_change_requires_approval_blocks_on_hand_when_unapproved():
    with pytest.raises(ValueError, match="has not been approved yet"):
        validate_purchase_status_change_requires_approval(
            new_status="delivered",
            is_approved=False,
            on_hand_statuses=("delivered", "in_testing", "available", "processing"),
        )


def test_apply_pipeline_stage_transition_stamps_approval_on_commitment_entry():
    purchase = Purchase()
    assert purchase.purchase_approved_at is None
    assert purchase.purchase_approved_by_user_id is None

    apply_pipeline_stage_transition(
        purchase=purchase,
        prev_status="declared",
        new_status="committed",
        can_approve_purchase=True,
        approver_user_id="approver-123",
    )

    assert purchase.purchase_approved_at is not None
    assert purchase.purchase_approved_by_user_id == "approver-123"


def test_apply_pipeline_stage_transition_rejects_unauthorized_commitment_transition():
    purchase = Purchase()
    with pytest.raises(ValueError, match="Only Super Admin or users with purchase approval permission"):
        apply_pipeline_stage_transition(
            purchase=purchase,
            prev_status="declared",
            new_status="committed",
            can_approve_purchase=False,
            approver_user_id="approver-123",
        )
