from __future__ import annotations
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base
from routes_auth import otp_verify, request_otp
from schema import OtpRequest, OtpVerifyRequest
import time
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

async def test():
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async_session = sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    
    db = async_session()
    
    # Request OTP
    req = OtpRequest(email="local@example.com", first_name="Local", last_name="Test")
    await request_otp(req, db)
    
    # We need to extract the OTP code to test verify.
    # We can fetch the user and check the hash? No, hash is one-way.
    # We have to mock `send_email` or `generate_numeric_code`.
    pass

asyncio.run(test())
