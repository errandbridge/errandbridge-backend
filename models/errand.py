import os

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float
from sqlalchemy.sql import func
from database import Base


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


# IMPORTANT:
# The production DB can lag behind the code during deployments.
# Mapping columns that don't exist yet causes INSERT/SELECT failures.
#
# Enable payment metadata columns only when the DB migration has been applied.
# (For example, after applying alembic revision 009_add_payment_metadata.)
ENABLE_PAYMENT_METADATA_COLUMNS = _env_truthy(
    os.getenv("ENABLE_PAYMENT_METADATA_COLUMNS")
)

class Errand(Base):
    __tablename__ = "errands"
    id = Column(Integer, primary_key=True, index=True)
    reference_number = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    note = Column(String, nullable=True)
    category_id = Column(String, nullable=True)
    template_id = Column(String, nullable=True)
    support_type = Column(String, nullable=True)
    preferred_time = Column(String, nullable=True)
    priority_level = Column(String, nullable=True)
    distance_km = Column(Float, nullable=True)
    final_price_minor = Column(Integer, nullable=True)
    final_price_currency = Column(String, nullable=True)
    sensitivity = Column(String, nullable=True)
    confirmation_sent_at = Column(Integer, nullable=True)
    issue_reason = Column(String, nullable=True)
    issue_notes = Column(String, nullable=True)
    issue_reported_at = Column(DateTime(timezone=True), nullable=True)
    issue_preferred_resolution = Column(String, nullable=True)
    issue_status = Column(String, nullable=True)
    issue_resolved_at = Column(DateTime(timezone=True), nullable=True)
    issue_resolution_notes = Column(String, nullable=True)
    issue_evidence_attachment_ids = Column(String, nullable=True)
    pickup_location = Column(String, nullable=True)
    dropoff_location = Column(String, nullable=True)
    pickup_contact_name = Column(String, nullable=True)
    pickup_contact_phone = Column(String, nullable=True)
    dropoff_contact_name = Column(String, nullable=True)
    dropoff_contact_phone = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    user_id = Column(Integer, nullable=False)
    
    # Assignment tracking
    assigned_to = Column(Integer, nullable=True, index=True)  # Admin user ID who is assigned
    assigned_at = Column(DateTime(timezone=True), nullable=True)  # When assigned
    
    # Review fields (after completion)
    review_status = Column(String, nullable=True)  # 'pending', 'reviewed', 'appealed'
    reviewer_rating = Column(Integer, nullable=True)  # 1-5 stars
    reviewer_notes = Column(String, nullable=True)  # Customer review text
    review_completed_at = Column(DateTime(timezone=True), nullable=True)

    # Pickup time slot (when customer wants to pick up the errand)
    pickup_time_slot_start = Column(DateTime(timezone=True), nullable=True)  # e.g., 9:00 AM
    pickup_time_slot_end = Column(DateTime(timezone=True), nullable=True)    # e.g., 5:00 PM
    pickup_time_slot_date = Column(String, nullable=True)  # Date in YYYY-MM-DD format

    # Pilot delivery tracking fields
    pilot_id = Column(Integer, nullable=True, index=True)  # FK to pilot user
    started_at = Column(DateTime(timezone=True), nullable=True)  # When pilot started delivery
    completed_at = Column(DateTime(timezone=True), nullable=True)  # When delivery completed
    delivery_time = Column(Float, nullable=True)  # Delivery duration in seconds
    tracking_paused = Column(Boolean, default=False)  # Whether tracking is paused
    
    # Proof of delivery
    signature_url = Column(String, nullable=True)  # URL to signature image
    photo_url = Column(String, nullable=True)  # URL to delivery photo
    completion_notes = Column(String, nullable=True)  # Notes added at completion
    pilot_notes = Column(String, nullable=True)  # Pilot's notes during delivery
    tip = Column(Float, default=0)  # Customer tip amount

    # Tip metadata (Stripe-verified, separate from initial payment metadata)
    # Stored for internal reconciliation and pilot reporting.
    tip_amount_total_minor = Column(Integer, nullable=True)  # e.g., Stripe session.amount_total
    tip_currency = Column(String, nullable=True)  # e.g., 'usd', 'ngn'
    tip_paid_at = Column(DateTime(timezone=True), nullable=True)
    tip_stripe_session_id = Column(String, nullable=True)

    # Payment metadata (Stripe-verified)
    # Stored for internal reconciliation and pilot reporting.
    # These columns are optional and only mapped when enabled.
    if ENABLE_PAYMENT_METADATA_COLUMNS:
        payment_amount_total_minor = Column(Integer, nullable=True)  # e.g., Stripe session.amount_total
        payment_currency = Column(String, nullable=True)  # e.g., 'usd', 'ngn'
        payment_amount_ngn_major = Column(Integer, nullable=True)  # canonical NGN amount (rounded major units)
