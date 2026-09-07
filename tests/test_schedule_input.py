import asyncio

import pytest

import schema as schema_module


@pytest.mark.parametrize(
    "input_schedule, expected_date",
    [
        (
            {"type": "now"},
            None,
        ),
        (
            {
                "type": "one_time",
                "date": "2026-03-31",
                "startTime": "16:00",
                "endTime": "21:45",
            },
            "2026-03-31",
        ),
    ],
)
def test_create_errand_accepts_schedule_input(input_schedule, expected_date):
    # Unit-test the schedule mapping logic without requiring a running Postgres.
    # This keeps the test suite runnable in CI/local without docker-compose.
    class _FakeSession:
        def __init__(self):
            self._added = []

        def add(self, _obj):
            self._added.append(_obj)
            return None

        async def flush(self):
            for obj in self._added:
                if getattr(obj, "id", None) is None:
                    obj.id = 123
            return None

        async def commit(self):
            return None

        async def refresh(self, _obj):
            if getattr(_obj, "id", None) is None:
                _obj.id = 123
            return None

    class _FakeInfo:
        context = {"db": _FakeSession(), "current_user_id": 1}

    mutation_root = schema_module.Mutation()

    # Build CreateErrandInput using only the fields this test cares about.
    schedule_input = schema_module.ScheduleInput(**input_schedule)

    create_input = schema_module.CreateErrandInput(
        title=f"Schedule test {input_schedule['type']}",
        pickupLocation="Lagos, Nigeria",
        dropoffLocation="Ibadan, Nigeria",
        sensitivity="Normal",
        scheduleType=input_schedule["type"],
        schedule=schedule_input,
        userId=1,
    )

    created = asyncio.run(mutation_root.create_errand(_FakeInfo(), create_input))
    assert created.title == create_input.title
    assert created.pickupTimeSlotDate == expected_date
