import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from models import User, Errand
from database import engine

async def check():
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as db:
        pilot = await db.scalar(select(User).where(User.id == 2))
        errand = await db.scalar(select(Errand).where(Errand.id == 4))
        print("Pilot city:", getattr(pilot, 'city', None))
        print("Pilot state:", getattr(pilot, 'state_province', None))
        print("Pilot vehicle:", getattr(pilot, 'vehicle_type', None))
        print("Pilot cross city:", getattr(pilot, 'cross_city_available', None))
        print("Pilot radius:", getattr(pilot, 'service_radius_km', None))
        
        print("Errand support:", getattr(errand, 'support_type', None))
        print("Errand distance:", getattr(errand, 'distance_km', None))
        print("Errand pickup:", getattr(errand, 'pickup_location', None))
        print("Errand dropoff:", getattr(errand, 'dropoff_location', None))

asyncio.run(check())
