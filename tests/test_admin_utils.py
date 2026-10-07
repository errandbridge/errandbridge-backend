from __future__ import annotations

from app.utils.admin_utils import (
    admin_emails,
    elevated_admin_emails,
    is_elevated_admin_email,
)


def test_ade_is_admin_and_elevated_without_environment(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("ELEVATED_ADMIN_EMAILS", raising=False)

    assert "ade@errandbridge.com" in admin_emails()
    assert "ade@errandbridge.com" in elevated_admin_emails()
    assert is_elevated_admin_email(" ADE@ERRANDBRIDGE.COM ") is True


def test_environment_admins_remain_supported(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " Other@Example.com ")
    monkeypatch.setenv("ELEVATED_ADMIN_EMAILS", " Owner@Example.com ")

    assert admin_emails() == {"ade@errandbridge.com", "other@example.com"}
    assert elevated_admin_emails() == {
        "ade@errandbridge.com",
        "owner@example.com",
    }
