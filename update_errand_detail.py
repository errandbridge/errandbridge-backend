import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/errandbridge"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE errands SET distance_km = 5.0, pickup_location = '123 Main St', dropoff_location = '456 Market St' WHERE id = 4"
            )
        )
        await session.commit()
        print("Updated successfully")
    await engine.dispose()


asyncio.run(main())
