from datetime import datetime, timezone
from types import SimpleNamespace

from schema import (
    build_assigned_pilot_trust_snapshot,
    build_client_lifecycle_snapshot,
    build_referral_code_for_user,
)


def test_build_referral_code_for_user_is_stable_and_uppercase():
    user = SimpleNamespace(
        id=18,
        first_name="Akin",
        last_name="Johnson",
        email="akin@example.com",
    )

    code_a = build_referral_code_for_user(user)
    code_b = build_referral_code_for_user(user)

    assert code_a == code_b
    assert code_a.startswith("AKIN18")
    assert code_a == code_a.upper()



def test_build_client_lifecycle_snapshot_tracks_pending_reviews_and_share_state():
    user = SimpleNamespace(
        id=42,
        first_name="Akin",
        last_name="Johnson",
        email="akin@example.com",
    )
    errands = [
        SimpleNamespace(
            id=100,
            status="completed",
            review_status="pending",
            completed_at=None,
            review_completed_at=None,
            created_at=datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id=101,
            status="accepted",
            review_status="reviewed",
            completed_at=None,
            review_completed_at=None,
            created_at=datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc),
        ),
    ]

    snapshot = build_client_lifecycle_snapshot(
        user=user,
        errands=errands,
        promo_codes=[],
        public_base_url="https://www.errandbridge.com",
    )

    assert snapshot["isLoggedIn"] is True
    assert snapshot["hasSubmittedRequest"] is True
    assert snapshot["isReturningClient"] is True
    assert snapshot["completedErrandCount"] == 2
    assert snapshot["pendingReviewErrandIds"] == [100]
    assert snapshot["hasPendingReview"] is True
    assert snapshot["hasSubmittedAnyReview"] is True
    assert snapshot["referralCode"].startswith("AKIN42")
    assert snapshot["referralShareLink"].startswith("https://www.errandbridge.com/signup?ref=")
    assert snapshot["hasReferralShareAvailable"] is True
    assert snapshot["referralCampaignEndsAt"] == "2026-12-31T23:59:59Z"



def test_build_client_lifecycle_snapshot_detects_unused_referral_rewards():
    user = SimpleNamespace(
        id=7,
        first_name="Ada",
        last_name="Bridge",
        email="ada@example.com",
    )
    promo_codes = [
        SimpleNamespace(
            source="referral_reward:77",
            redeemed_count=0,
            max_redemptions=1,
        ),
    ]

    snapshot = build_client_lifecycle_snapshot(
        user=user,
        errands=[],
        promo_codes=promo_codes,
        public_base_url="https://www.errandbridge.com",
    )

    assert snapshot["hasEarnedReferralReward"] is True
    assert snapshot["hasUnusedReferralReward"] is True
    assert snapshot["referralRewardExpiresAt"] == "2026-12-31T23:59:59Z"


def test_build_assigned_pilot_trust_snapshot_prefers_review_average_and_recent_reviews():
    pilot = SimpleNamespace(
        id=9,
        first_name="Nora",
        last_name="Bridge",
        email="nora@example.com",
        is_email_verified=True,
        id_verification_status="verified",
        rating=4.2,
        profile_image_url="https://cdn.example.com/pilot-9.png",
    )
    reviewed_errands = [
        SimpleNamespace(
            id=201,
            title="Airport pickup",
            reference_number="EB-201-7781",
            reviewer_rating=5,
            reviewer_notes="Very calm and professional.",
            review_completed_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
            completed_at=None,
            created_at=datetime(2026, 4, 10, 8, 0, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            id=202,
            title="Document run",
            reference_number="EB-202-1123",
            reviewer_rating=4,
            reviewer_notes="Fast handoff.",
            review_completed_at=datetime(2026, 4, 9, 9, 0, tzinfo=timezone.utc),
            completed_at=None,
            created_at=datetime(2026, 4, 9, 8, 0, tzinfo=timezone.utc),
        ),
    ]

    snapshot = build_assigned_pilot_trust_snapshot(
        pilot=pilot,
        reviewed_errands=reviewed_errands,
        completed_errands_count=28,
    )

    assert snapshot["pilotId"] == 9
    assert snapshot["displayName"] == "Nora Bridge"
    assert snapshot["rating"] == 4.5
    assert snapshot["reviewCount"] == 2
    assert snapshot["completedErrands"] == 28
    assert snapshot["verificationLabel"] == "Identity verified"
    assert snapshot["trustLabel"] == "Trusted by clients"
    assert snapshot["recentReviews"][0]["title"] == "Airport pickup"
    assert snapshot["recentReviews"][0]["rating"] == 5
