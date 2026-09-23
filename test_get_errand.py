import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, cast, String
import os
import uuid
import sys

# Import models
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import Errand

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/errandbridge")

async def test():
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as session:
        result = await session.execute(select(Errand.id).limit(1))
        first_id = result.scalar_one_or_none()
        print("First id:", first_id, type(first_id))
        
        if first_id:
            # test the where clause exactly as in main.py
            stmt = select(Errand).where(cast(Errand.id, String) == str(first_id))
            res2 = await session.execute(stmt)
            model = res2.scalar_one_or_none()
            print("Found model with cast:", model is not None)
            
            # Now test if a wrong user trying to access returns 404 via some other mechanism?
            
asyncio.run(test())
