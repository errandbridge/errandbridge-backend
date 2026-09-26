from __future__ import annotations
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from database import Base
from models.user import User
from app.utils.otp import hash_code, now_ts
from routes_auth import otp_verify, OtpVerifyRequest
from database import get_db

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as db:
        user = User(
            email="test@example.com",
            email_otp_hash=hash_code("123456"),
            email_otp_expires_at=now_ts() + 600,
            is_email_verified=False
        )
        db.add(user)
        await db.commit()
    
    async with SessionLocal() as db:
        req = OtpVerifyRequest(email="test@example.com", otp_code="123456", purpose="login")
        try:
            res = await otp_verify(req, db=db)
            print("SUCCESS:", res.email, res.is_email_verified)
        except Exception as e:
            print("ERROR:", type(e), e)

asyncio.run(main())
