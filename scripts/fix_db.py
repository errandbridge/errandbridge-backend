import asyncio
from sqlalchemy import text
from database import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_uuid VARCHAR(36)")
        )
        # Give existing users a uuid
        await session.execute(
            text(
                "UPDATE users SET user_uuid = gen_random_uuid() WHERE user_uuid IS NULL"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE users ADD CONSTRAINT users_user_uuid_key UNIQUE (user_uuid)"
            )
        )
        await session.commit()
        print("Done!")


asyncio.run(main())
