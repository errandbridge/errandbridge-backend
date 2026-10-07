from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import routes_admin
from models import Errand, ErrandAttachment, User
from models.errand_event import ErrandEvent


@pytest.mark.asyncio
async def test_admin_can_approve_uuid_attachment_and_record_audit(monkeypatch):
    admin_id = uuid4()
    errand_id = uuid4()
    attachment_id = uuid4()
    owner_id = uuid4()
    admin = SimpleNamespace(id=admin_id)
    attachment = SimpleNamespace(
        id=attachment_id,
        errand_id=errand_id,
        original_filename="proof.png",
        review_status="pending",
        review_note=None,
        reviewed_at=None,
        reviewed_by_user_id=None,
    )
    errand = SimpleNamespace(
        id=errand_id,
        user_id=owner_id,
        pilot_id=None,
        status="proof_submitted",
    )

    async def get_model(model, model_id):
        if model is ErrandAttachment and model_id == attachment_id:
            return attachment
        if model is Errand and model_id == errand_id:
            return errand
        if model is User and model_id == owner_id:
            return None
        return None

    db = SimpleNamespace(
        get=AsyncMock(side_effect=get_model),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    monkeypatch.setattr(
        routes_admin, "_require_admin", AsyncMock(return_value=admin)
    )

    result = await routes_admin.review_attachment(
        attachment_id=attachment_id,
        payload=routes_admin.AdminAttachmentReviewIn(action="approve"),
        authorization="Bearer token",
        db=db,
    )

    assert result["reviewStatus"] == "approved"
    assert result["attachment_id"] == attachment_id
    assert result["status"] == "approved"
    assert result["reviewedByUserId"] == admin_id
    routes_admin.AdminReviewAttachmentResponse.model_validate(result)
    assert attachment.reviewed_by_user_id == admin_id
    audit_event = next(
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ErrandEvent)
    )
    assert audit_event.errand_id == errand_id
    assert audit_event.user_id == admin_id
    assert audit_event.event_type == "admin_attachment_approved"

    await routes_admin.review_attachment(
        attachment_id=attachment_id,
        payload=routes_admin.AdminAttachmentReviewIn(action="approve"),
        authorization="Bearer token",
        db=db,
    )
    audit_events = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ErrandEvent)
    ]
    assert len(audit_events) == 1