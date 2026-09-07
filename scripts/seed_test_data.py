#!/usr/bin/env python3
import asyncio
import os
import time
from datetime import datetime

os.chdir("/app")
import sys

sys.path.insert(0, "/app")

from database import AsyncSessionLocal
from models import User, Errand
from auth import hash_password


def _make_reference_number(errand_id: int) -> str:
    """Generate a stable customer-facing reference number."""
    check = (int(errand_id) * 7919) % 10000
    return f"EB-{int(errand_id)}-{check:04d}"


async def seed_data():
    async with AsyncSessionLocal() as session:
        # Create test customer user
        customer = User(
            email="customer@test.com",
            password_hash=hash_password("Password123!"),
            is_email_verified=True,
            id_verification_status="pending",
            address_verification_status="pending",
            email_otp_attempts=0,
            first_name="John",
            last_name="Doe",
            phone="+1234567890",
        )
        session.add(customer)
        await session.flush()  # Get the customer ID

        # Create test errands
        errands = [
            Errand(
                user_id=customer.id,
                reference_number=_make_reference_number(
                    int(time.time() * 1_000_000) + 1
                ),
                title="Pick up groceries",
                description="Pick up groceries from Whole Foods",
                template_id="market_run",
                sensitivity="low",
                pickup_location="123 Main St, New York, NY",
                dropoff_location="456 Park Ave, New York, NY",
                status="submitted",
                created_at=datetime.utcnow(),
            ),
            Errand(
                user_id=customer.id,
                reference_number=_make_reference_number(
                    int(time.time() * 1_000_000) + 2
                ),
                title="Document delivery",
                description="Deliver important documents to downtown office",
                template_id="diaspora_pickup",
                sensitivity="high",
                pickup_location="789 Broadway, New York, NY",
                dropoff_location="321 5th Ave, New York, NY",
                status="submitted",
                created_at=datetime.utcnow(),
            ),
            Errand(
                user_id=customer.id,
                reference_number=_make_reference_number(
                    int(time.time() * 1_000_000) + 3
                ),
                title="Airport pickup",
                description="Pick up visitor from JFK airport",
                template_id="driver_dispatch",
                sensitivity="medium",
                pickup_location="JFK Airport, New York, NY",
                dropoff_location="Manhattan Hotel, 42nd St, New York, NY",
                status="submitted",
                created_at=datetime.utcnow(),
            ),
        ]

        for errand in errands:
            session.add(errand)

        await session.commit()
        print("✅ Test data created successfully!")
        print(f"   - Customer: customer@test.com / Password123!")
        print(f"   - 3 test errands created and visible in Admin Dashboard")


asyncio.run(seed_data())
