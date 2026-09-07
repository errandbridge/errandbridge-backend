import database


def test_normalize_async_from_postgres_scheme():
    url = "postgres://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="async").startswith(
        "postgresql+asyncpg://"
    )


def test_normalize_async_from_postgresql_scheme():
    url = "postgresql://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="async").startswith(
        "postgresql+asyncpg://"
    )


def test_normalize_async_forces_asyncpg_driver():
    url = "postgresql+psycopg://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="async").startswith(
        "postgresql+asyncpg://"
    )


def test_normalize_sync_from_postgresql_scheme():
    url = "postgresql://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="sync").startswith(
        "postgresql+psycopg://"
    )


def test_normalize_sync_from_asyncpg_scheme():
    url = "postgresql+asyncpg://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="sync").startswith(
        "postgresql+psycopg://"
    )


def test_normalize_sync_from_psycopg2_scheme():
    url = "postgresql+psycopg2://user:pass@host:5432/db"
    assert database._normalize_database_url(url, mode="sync").startswith(
        "postgresql+psycopg://"
    )


def test_rewrite_docker_db_hostname_for_host_maps_to_localhost_port_5433():
    url = "postgresql+asyncpg://postgres:postgres@db:5432/errandbridge"
    rewritten = database._rewrite_docker_db_hostname_for_host(url)
    assert "@127.0.0.1:5433/errandbridge" in rewritten


def test_rewrite_docker_db_hostname_for_host_noop_for_non_db_host():
    url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/errandbridge"
    rewritten = database._rewrite_docker_db_hostname_for_host(url)
    assert rewritten == url
