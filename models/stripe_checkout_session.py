import uuid
from sqlalchemy import Uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from database import Base


class StripeCheckoutSession(Base):
    __tablename__ = "stripe_checkout_sessions"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    stripe_session_id = Column(String, nullable=False, unique=True, index=True)

    user_id = Column(String, nullable=True, index=True)
    kind = Column(
        String, nullable=False, default="payment"
    )  # payment | subscription | tip
    mode = Column(String, nullable=True)  # payment | subscription (Stripe session.mode)

    paid = Column(Boolean, nullable=False, default=False)
    amount_total_minor = Column(Integer, nullable=True)
    currency = Column(String, nullable=True)

    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)

    used_for_errand_id = Column(String, nullable=True, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
