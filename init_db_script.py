#!/usr/bin/env python3
import asyncio
import os
os.chdir('/app')
import sys
sys.path.insert(0, '/app')

from database import engine, Base
from models import User, Errand, ErrandAttachment, AttachmentShareLink, ErrandEvent

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
