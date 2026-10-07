import pytest

from app.errand_lifecycle import validate_errand_transition


@pytest.mark.parametrize(
    ("actor", "current_status", "next_status"),
    [
        ("pilot", "accepted", "in_progress"),
        ("pilot", "in_progress", "arrived_at_pickup"),
        ("pilot", "arrived_at_pickup", "picked_up"),
        ("pilot", "picked_up", "arrived_at_dropoff"),
        ("pilot", "arrived_at_dropoff", "proof_submitted"),
        ("pilot", "proof_submitted", "delivered"),
        ("customer", "delivered", "completed"),
        ("customer", "delivered", "disputed"),
        ("admin", "delivered", "completed"),
        ("admin", "disputed", "completed"),
    ],
)
def test_allows_coordinated_transition(actor, current_status, next_status):
    assert validate_errand_transition(
        actor=actor,
        current_status=current_status,
        next_status=next_status,
    ) == next_status


@pytest.mark.parametrize(
    ("actor", "current_status", "next_status"),
    [
        ("pilot", "assigned", "in_progress"),
        ("pilot", "accepted", "completed"),
        ("pilot", "in_progress", "delivered"),
        ("customer", "submitted", "completed"),
        ("customer", "proof_submitted", "completed"),
        ("admin", "submitted", "completed"),
        ("admin", "assigned", "completed"),
        ("admin", "in_progress", "completed"),
    ],
)
def test_rejects_skipped_or_unauthorized_transition(actor, current_status, next_status):
    with pytest.raises(ValueError):
        validate_errand_transition(
            actor=actor,
            current_status=current_status,
            next_status=next_status,
        )