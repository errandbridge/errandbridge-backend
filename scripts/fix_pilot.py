import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
from models import User, Errand
from database import engine


async def fix():
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as db:
        await db.execute(
            update(User)
            .where(User.id == 2)
            .values(city="London", state_province="London", vehicle_type="car")
        )
        await db.execute(
            update(Errand)
            .where(Errand.id == 4)
            .values(
                pickup_location="123 Main St, London",
                dropoff_location="456 Market St, London",
                support_type="car_support",
                distance_km=5.0,
            )
        )
        await db.commit()
        print("Updated pilot 2 and errand 4.")


asyncio.run(fix())
