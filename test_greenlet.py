from __future__ import annotations
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from auth_user_query import auth_safe_user_by_email_query

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/errandbridge")

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def main():
    async with async_session() as db:
        result = await db.execute(auth_safe_user_by_email_query("test@example.com"))
        user = result.scalar_one_or_none()
        if not user:
            print("No user")
            return
        print(f"User ID: {user.id}")
        
        # Now try to access must_change_password WITHOUT refreshing
        try:
            print(f"must_change_password before refresh: {user.must_change_password}")
        except Exception as e:
            print(f"Error before refresh: {e}")
            
        await db.refresh(user)
        try:
            print(f"must_change_password after refresh: {user.must_change_password}")
        except Exception as e:
            print(f"Error after refresh: {e}")

if __name__ == "__main__":
    asyncio.run(main())
