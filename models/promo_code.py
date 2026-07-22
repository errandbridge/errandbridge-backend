from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from database import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)

    # Human-facing code customers can type at checkout.
    code = Column(String, nullable=False, unique=True, index=True)

    # Discount percent (e.g. 10 means 10% off).
    percent_off = Column(Integer, nullable=False, default=10)

    # Optional: promo can be tied to a specific customer.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # For auditability.
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    source = Column(String, nullable=True)  # e.g. 'review_reward', 'admin_manual'

    max_redemptions = Column(Integer, nullable=False, default=1)
    redeemed_count = Column(Integer, nullable=False, default=0)

    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    redeemed_errand_id = Column(Integer, ForeignKey("errands.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
