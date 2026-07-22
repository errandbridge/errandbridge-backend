import importlib

import database


def test_encode_db_password_encodes_percent_sequences_by_default(monkeypatch):
    # Password contains a substring that looks like URL encoding, but is actually literal.
    # If we don't encode it, URL parsers will decode it and corrupt the password.
    monkeypatch.delenv("DB_PASSWORD_URLENCODED", raising=False)
    assert database._encode_db_password("abc%2Fdef") == "abc%252Fdef"


def test_encode_db_password_can_skip_encoding_when_opted_in(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD_URLENCODED", "1")
    assert database._encode_db_password("abc%2Fdef") == "abc%2Fdef"


def test_placeholder_injection_encodes_percent_sequences(monkeypatch):
    # Reload the module because DATABASE_URL is constructed at import time.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db.example.com:5432/errandbridge",
    )
    monkeypatch.setenv("DB_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "abc%2Fdef")
    # Keep local mode to avoid SSL requirements in tests.
    monkeypatch.setenv("ENV", "local")
    monkeypatch.setenv("AWS_EXECUTION_ENV", "test")

    importlib.reload(database)
    assert "abc%252Fdef" in database.DATABASE_URL
