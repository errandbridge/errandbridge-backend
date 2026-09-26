from __future__ import annotations
import asyncio
import os

# Override DATABASE_URL before importing anything
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from database import engine, get_db
from models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from routes_auth import otp_verify, OtpVerifyRequest
from auth import hash_password

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def main():
    async with engine.begin() as conn:
        from database import Base
        await conn.run_sync(Base.metadata.create_all)

    # 1. Create User
    async with AsyncSessionLocal() as db:
        user = User(
            email="test@example.com",
            password_hash=hash_password("fakehash"),
            is_email_verified=False,
            email_otp_hash="6689c5287bd1a944f9f5a74354429534c077fbfdb012807706fb203da91a6626", # 123456
            email_otp_expires_at=9999999999
        )
        db.add(user)
        try:
            await db.commit()
        except Exception as e:
            print("DB error:", e)

    # 2. Run otp_verify
    async with AsyncSessionLocal() as db:
        req = OtpVerifyRequest(email="test@example.com", otp_code="123456")
        try:
            res = await otp_verify(req, db)
            print("Verify response:", res)
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
