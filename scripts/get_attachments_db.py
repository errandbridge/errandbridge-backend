import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.errand_attachment import ErrandAttachment


async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(ErrandAttachment).order_by(ErrandAttachment.id.desc()).limit(2)
        )
        items = res.scalars().all()

        response = []
        for a in items:
            response.append(
                {
                    "id": a.id,
                    "errandId": a.errand_id,
                    "filename": a.original_filename,
                    "contentType": a.content_type,
                    "sizeBytes": a.size_bytes,
                    "url": f"/attachments/{a.id}/download",
                    "label": getattr(a, "label", None),
                    "reviewStatus": str(
                        getattr(a, "review_status", "pending") or "pending"
                    ),
                    "reviewNote": getattr(a, "review_note", None),
                    "reviewedAt": (
                        a.reviewed_at.isoformat()
                        if getattr(a, "reviewed_at", None)
                        else None
                    ),
                    "reviewedByUserId": getattr(a, "reviewed_by_user_id", None),
                    "createdAt": a.created_at.isoformat() if a.created_at else None,
                }
            )

        import json

        print(json.dumps(response, indent=2))


asyncio.run(main())
