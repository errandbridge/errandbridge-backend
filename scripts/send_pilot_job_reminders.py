import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Errand, ErrandEvent, User
from app.utils.notification_utils import (
    notify_pilot_job_reminder,
    build_pilot_availability_token,
    pilot_web_base,
)

REMINDER_INTERVAL_MINUTES = int(os.getenv("PILOT_REMINDER_INTERVAL_MINUTES", "60"))
REMINDER_CLOSE_WINDOW_MINUTES = int(
    os.getenv("PILOT_REMINDER_CLOSE_WINDOW_MINUTES", "120")
)
REMINDER_CLOSE_INTERVAL_MINUTES = int(
    os.getenv("PILOT_REMINDER_CLOSE_INTERVAL_MINUTES", "15")
)
AVAILABILITY_CHECK_MINUTES = int(os.getenv("PILOT_AVAILABILITY_CHECK_MINUTES", "60"))
AVAILABILITY_LINK_EXPIRES_MINUTES = int(
    os.getenv("PILOT_AVAILABILITY_LINK_EXPIRES_MINUTES", "120")
)


async def _should_send_reminder(db, errand: Errand, interval_minutes: int) -> bool:
    result = await db.execute(
        select(ErrandEvent)
        .where(ErrandEvent.errand_id == errand.id)
        .where(ErrandEvent.event_type == "pilot_reminder")
        .order_by(ErrandEvent.created_at.desc())
        .limit(1)
    )
    last_event = result.scalar_one_or_none()
    if not last_event or not last_event.created_at:
        return True
    elapsed = datetime.now(timezone.utc) - last_event.created_at
    return elapsed.total_seconds() >= interval_minutes * 60


async def _availability_request_sent(db, errand: Errand) -> bool:
    result = await db.execute(
        select(ErrandEvent)
        .where(ErrandEvent.errand_id == errand.id)
        .where(ErrandEvent.event_type == "pilot_availability_request")
        .order_by(ErrandEvent.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def send_reminders() -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Errand)
            .where(Errand.pilot_id.isnot(None))
            .where(Errand.status.in_(["assigned", "accepted"]))
        )
        errands = result.scalars().all()

        for errand in errands:
            if errand.started_at:
                continue

            minutes_to_start = None
            interval_minutes = REMINDER_INTERVAL_MINUTES
            if errand.pickup_time_slot_start:
                delta = errand.pickup_time_slot_start - now
                minutes_to_start = delta.total_seconds() / 60
                if minutes_to_start <= 0:
                    continue
                if minutes_to_start <= REMINDER_CLOSE_WINDOW_MINUTES:
                    interval_minutes = REMINDER_CLOSE_INTERVAL_MINUTES

            should_send = await _should_send_reminder(db, errand, interval_minutes)
            if not should_send:
                continue

            availability_links = None
            if (
                minutes_to_start is not None
                and minutes_to_start <= AVAILABILITY_CHECK_MINUTES
            ):
                if not await _availability_request_sent(db, errand):
                    expires_at = int(
                        (now.timestamp()) + (AVAILABILITY_LINK_EXPIRES_MINUTES * 60)
                    )
                    token = build_pilot_availability_token(
                        errand.id, int(errand.pilot_id), expires_at
                    )
                    base_url = pilot_web_base()
                    availability_links = {
                        "yes": f"{base_url}/?mode=pilot&availability=yes&errandId={errand.id}&pilotId={errand.pilot_id}&expires={expires_at}&token={token}",
                        "no": f"{base_url}/?mode=pilot&availability=no&errandId={errand.id}&pilotId={errand.pilot_id}&expires={expires_at}&token={token}",
                    }

            pilot = (
                await db.get(User, int(errand.pilot_id)) if errand.pilot_id else None
            )
            await notify_pilot_job_reminder(
                db,
                errand=errand,
                pilot_user=pilot,
                minutes_to_start=minutes_to_start,
                availability_links=availability_links,
            )

            db.add(
                ErrandEvent(
                    errand_id=errand.id,
                    event_type="pilot_reminder",
                    old_status=errand.status,
                    new_status=errand.status,
                    note=f"interval={interval_minutes}m; minutes_to_start={minutes_to_start}",
                    user_id=errand.pilot_id,
                )
            )
            if availability_links:
                db.add(
                    ErrandEvent(
                        errand_id=errand.id,
                        event_type="pilot_availability_request",
                        old_status=errand.status,
                        new_status=errand.status,
                        note=f"expires_at={expires_at}",
                        user_id=errand.pilot_id,
                    )
                )
            await db.commit()


def main() -> None:
    asyncio.run(send_reminders())


if __name__ == "__main__":
    main()
