"""Policy tests for purchase status transitions."""

import pytest

from policies.purchase_status import (
    require_approval_for_on_hand_status,
    validate_delivered_requires_prior_commitment,
    validate_pipeline_commitment_transition,
)


def test_on_hand_requires_approval():
    with pytest.raises(ValueError):
        require_approval_for_on_hand_status(
            new_status="delivered",
            is_approved=False,
            on_hand_statuses=("delivered", "in_testing", "available", "processing"),
        )


def test_pipeline_commitment_requires_capability():
    with pytest.raises(ValueError):
        validate_pipeline_commitment_transition(
            prev_status="declared",
            new_status="committed",
            can_approve_purchase=False,
        )


def test_pipeline_commitment_transition_flags():
    enters, leaves = validate_pipeline_commitment_transition(
        prev_status="declared",
        new_status="committed",
        can_approve_purchase=True,
    )
    assert enters is True
    assert leaves is False


def test_delivered_requires_prior_commitment():
    with pytest.raises(ValueError):
        validate_delivered_requires_prior_commitment(
            prev_status="in_testing",
            new_status="delivered",
        )
