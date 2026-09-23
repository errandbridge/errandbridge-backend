import asyncio
from database import async_session_maker
from models.user import User
from sqlalchemy import select
from app.utils.otp import hash_code
import time

async def main():
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == "test@example.com"))
        user = result.scalar_one_or_none()
        if not user:
            print("User not found.")
            return

        # Let's set the OTP explicitly to a known value
        user.email_otp_hash = hash_code("123456")
        user.email_otp_expires_at = time.time() + 600
        await session.commit()
        print("OTP set to 123456")

if __name__ == "__main__":
    asyncio.run(main())
