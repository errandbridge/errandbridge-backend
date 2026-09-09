import uuid

from sqlalchemy import Column, Uuid, Integer, String, DateTime, Boolean, Date, Float
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    user_uuid = Column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    must_change_password = Column(Boolean, nullable=False, default=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_email_verified = Column(Boolean, nullable=False, default=False)
    email_otp_hash = Column(String, nullable=True)
    email_otp_expires_at = Column(Integer, nullable=True)
    email_otp_last_sent_at = Column(Integer, nullable=True)
    email_otp_attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    id_verification_method = Column(String, nullable=True)
    id_verification_status = Column(String, nullable=False, default="pending")
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)
    address_verification_status = Column(String, nullable=False, default="pending")

    # Profile and address fields
    date_of_birth = Column(Date, nullable=True)
    profile_image_url = Column(String, nullable=True)
    street_address = Column(String, nullable=True)
    state_province = Column(String, nullable=True)

    # Vehicle information
    vehicle_type = Column(String, nullable=True)
    vehicle_make = Column(String, nullable=True)
    vehicle_model = Column(String, nullable=True)
    vehicle_year = Column(Integer, nullable=True)
    license_plate = Column(String, nullable=True)
    insurance_provider = Column(String, nullable=True)
    insurance_expiry = Column(Date, nullable=True)
    is_pilot = Column(Boolean, nullable=False, default=False)
    pilot_availability = Column(String, nullable=False, default="offline")
    admin_dispatch_status = Column(String, nullable=False, default="enabled")
    admin_dispatch_note = Column(String, nullable=True)
    pilot_status_changed_at = Column(DateTime(timezone=True), nullable=True)
    pilot_status_changed_by = Column(Uuid, nullable=True)

    # Performance metrics
    rating = Column(Float, nullable=True, default=4.8)
