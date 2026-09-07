import asyncio
from database import engine, Base
from models import (
    User,  # noqa: F401
    Errand,  # noqa: F401
    ErrandAttachment,  # noqa: F401
    AttachmentShareLink,  # noqa: F401
    PilotEmploymentApplication,  # noqa: F401
    PilotEmploymentAttachment,  # noqa: F401
)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tables created successfully")


if __name__ == "__main__":
    asyncio.run(create_tables())
