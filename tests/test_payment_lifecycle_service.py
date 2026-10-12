from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import payment_lifecycle_service as service


@pytest.mark.asyncio
async def test_capture_errand_payment_captures_authorized_intent(monkeypatch):
    async def _reference(*args, **kwargs):
        return "cs_test_authorized"

    captured_ids = []

    class _CheckoutSessionApi:
        @staticmethod
        def retrieve(*args, **kwargs):
            return SimpleNamespace(
                payment_intent=SimpleNamespace(
                    id="pi_test_authorized",
                    status="requires_capture",
                )
            )

    class _PaymentIntentApi:
        @staticmethod
        def capture(intent_id):
            captured_ids.append(intent_id)
            return SimpleNamespace(id=intent_id, status="succeeded")

    monkeypatch.setattr(service, "_linked_payment_reference", _reference)
    monkeypatch.setattr(
        service,
        "stripe",
        SimpleNamespace(
            checkout=SimpleNamespace(Session=_CheckoutSessionApi),
            PaymentIntent=_PaymentIntentApi,
        ),
    )

    result = await service.capture_errand_payment(SimpleNamespace(), "errand-1")

    assert result.action == "captured"
    assert result.status == "succeeded"
    assert captured_ids == ["pi_test_authorized"]


@pytest.mark.asyncio
async def test_capture_errand_payment_is_idempotent_when_already_captured(monkeypatch):
    async def _reference(*args, **kwargs):
        return "pi_test_captured"

    class _PaymentIntentApi:
        @staticmethod
        def retrieve(intent_id):
            return SimpleNamespace(id=intent_id, status="succeeded")

        @staticmethod
        def capture(intent_id):
            raise AssertionError("already-captured intent must not be captured again")

    monkeypatch.setattr(service, "_linked_payment_reference", _reference)
    monkeypatch.setattr(
        service,
        "stripe",
        SimpleNamespace(PaymentIntent=_PaymentIntentApi),
    )

    result = await service.capture_errand_payment(SimpleNamespace(), "errand-1")

    assert result.action == "already_captured"


@pytest.mark.asyncio
async def test_cancel_errand_authorization_releases_hold(monkeypatch):
    async def _reference(*args, **kwargs):
        return "pi_test_authorized"

    cancelled_ids = []

    class _PaymentIntentApi:
        @staticmethod
        def retrieve(intent_id):
            return SimpleNamespace(id=intent_id, status="requires_capture")

        @staticmethod
        def cancel(intent_id):
            cancelled_ids.append(intent_id)
            return SimpleNamespace(id=intent_id, status="canceled")

    monkeypatch.setattr(service, "_linked_payment_reference", _reference)
    monkeypatch.setattr(
        service,
        "stripe",
        SimpleNamespace(PaymentIntent=_PaymentIntentApi),
    )

    result = await service.cancel_errand_authorization(
        SimpleNamespace(), "errand-1"
    )

    assert result.action == "authorization_cancelled"
    assert result.status == "canceled"
    assert cancelled_ids == ["pi_test_authorized"]
