import database


def test_ssl_context_disables_hostname_check_for_ip_host(monkeypatch):
    # Default is hostname-check enabled.
    monkeypatch.delenv("DB_SSL_CHECK_HOSTNAME", raising=False)

    ctx = database._create_ssl_context_for_database_url(
        "postgresql+asyncpg://user:pass@10.0.0.5:5432/errandbridge"
    )
    assert ctx.check_hostname is False


def test_ssl_context_keeps_hostname_check_for_dns_host(monkeypatch):
    monkeypatch.delenv("DB_SSL_CHECK_HOSTNAME", raising=False)

    ctx = database._create_ssl_context_for_database_url(
        "postgresql+asyncpg://user:pass@db.example.com:5432/errandbridge"
    )
    assert ctx.check_hostname is True


def test_ssl_context_honors_db_ssl_check_hostname_env(monkeypatch):
    monkeypatch.setenv("DB_SSL_CHECK_HOSTNAME", "0")

    ctx = database._create_ssl_context_for_database_url(
        "postgresql+asyncpg://user:pass@db.example.com:5432/errandbridge"
    )
    assert ctx.check_hostname is False


def test_ssl_context_does_not_fail_if_bundle_path_missing(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist.pem"
    monkeypatch.setenv("RDS_SSL_BUNDLE_PATH", str(missing))

    # Should fall back to system trust store and not raise.
    ctx = database._create_ssl_context_for_database_url(
        "postgresql+asyncpg://user:pass@db.example.com:5432/errandbridge"
    )
    assert isinstance(ctx, type(database.ssl.create_default_context()))
