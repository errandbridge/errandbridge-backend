import os
import pathlib
import re
import ssl
import json
import ipaddress
from urllib.parse import quote_plus, urlsplit, urlunsplit
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv


def _running_in_docker_filesystem() -> bool:
    """Best-effort detection of whether we're running inside a Docker container."""
    try:
        if pathlib.Path("/.dockerenv").exists():
            return True
    except Exception:
        pass

    # Fallback: cgroup inspection (Linux). If this file doesn't exist, we assume not Docker.
    try:
        cgroup_path = pathlib.Path("/proc/1/cgroup")
        if cgroup_path.exists():
            text = cgroup_path.read_text(errors="ignore")
            if "docker" in text or "containerd" in text:
                return True
    except Exception:
        pass

    return False


def _rewrite_docker_db_hostname_for_host(url: str) -> str:
    """Rewrite docker-compose service hostnames to host-mapped localhost ports.

    If a developer runs the API *on the host* (not in Docker) but uses a compose
    Postgres service name like `db`, that hostname won't resolve and causes
    `[Errno -2] Name or service not known`.

    We translate `@db:5432` -> `@127.0.0.1:5433` (compose's default port mapping
    in this repo).
    """
    if not url:
        return url

    try:
        parts = urlsplit(url)
    except Exception:
        return url

    host = (parts.hostname or "").strip().lower()
    if host != "db":
        return url

    port = parts.port or 5432
    # This repo's docker-compose maps host 5433 -> container 5432.
    mapped_port = 5433 if int(port) == 5432 else int(port)

    username = parts.username or ""
    password = parts.password or ""
    auth = ""
    if username:
        auth = username
        if password:
            auth = f"{auth}:{quote_plus(password)}"
        auth = f"{auth}@"

    netloc = f"{auth}127.0.0.1:{mapped_port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


# Load environment variables from .env when running locally (avoid overriding ECS env vars).
_env_name = (os.getenv("ENV") or "local").lower()
_running_in_aws = bool(os.getenv("AWS_EXECUTION_ENV"))
_in_docker_fs = _running_in_docker_filesystem()
if not _running_in_aws:
    # Safe: does not override existing env vars by default.
    load_dotenv()

# Use asyncpg driver for async SQLAlchemy
# Keep defaults aligned with docker-compose.yml for a smooth local/dev experience.
# (docker-compose uses POSTGRES_USER=postgres, POSTGRES_PASSWORD=postgres, port 5433->5432)
_DEFAULT_DOCKER_DB_URL = "postgresql+asyncpg://postgres:postgres@db:5432/errandbridge"
_DEFAULT_LOCAL_DB_URL = (
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/errandbridge"
)

# Get DATABASE_URL from environment, prefer explicit DATABASE_URL over defaults

DATABASE_URL = os.getenv("DATABASE_URL")


def _select_db_secret_payload() -> dict | None:
    """Read a full DB/RDS secret JSON from an env var.

    Some platforms (ECS Secrets Manager, Render, etc.) can inject the entire
    SecretString as JSON. This is more robust than splitting host/user/password
    across separate env vars (which can drift / mismatch).

    Expected shapes include AWS RDS Secrets Manager:
      {"username":"...","password":"...","host":"...","port":5432,"dbname":"..."}
    """
    for key in (
        "DB_SECRET_JSON",
        "DATABASE_SECRET_JSON",
        "RDS_SECRET_JSON",
        "AWS_RDS_SECRET_JSON",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if not raw:
            continue
        if not (raw.startswith("{") and raw.endswith("}")):
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _inject_credentials_into_database_url(
    url: str,
    *,
    user: str | None,
    password: str | None,
) -> str:
    """Ensure DATABASE_URL includes credentials when provided separately.

    In some production setups (ECS/SSM/Secrets Manager), teams inject:
      - DATABASE_URL=postgresql://postgres@host:5432/db   (no password)
      - DB_PASSWORD=...                                  (secret)

    If the URL doesn't include a password and has a username (or a DB_USER
    override is supplied), Postgres will attempt auth with an empty password,
    which yields: "password authentication failed for user ...".

    This helper inserts the password (and optionally the user) into the URL.
    """
    if not url:
        return url

    try:
        parts = urlsplit(url)
    except Exception:
        return url

    # If the URL already has a password, do nothing.
    if parts.password:
        return url

    hostname = (parts.hostname or "").strip()
    if not hostname:
        return url

    effective_user = (parts.username or user or "").strip()
    effective_password = (password or "").strip() if password else ""
    if not effective_user:
        # Nothing we can safely inject.
        return url

    if not effective_password:
        # We *can* still return a user-only URL, but it's usually unintended.
        return url

    # Preserve existing encoding when possible.
    encoded_password = _encode_db_password(effective_password)
    auth = f"{effective_user}:{encoded_password}@"

    port = parts.port
    hostport = f"{hostname}:{port}" if port else hostname
    netloc = f"{auth}{hostport}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _normalize_database_url(url: str, *, mode: str) -> str:
    """Normalize common Postgres URL schemes for SQLAlchemy.

    ECS/Secrets Manager often provide URLs like:
      - postgres://user:pass@host:5432/db
      - postgresql://user:pass@host:5432/db

    But SQLAlchemy async requires an async driver, e.g. postgresql+asyncpg://...
    For Alembic/sync usage, we prefer psycopg: postgresql+psycopg://...
    """
    if not url:
        return url

    mode_norm = (mode or "").strip().lower()
    if mode_norm not in ("async", "sync"):
        return url

    if "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    scheme_norm = scheme.strip().lower()

    # Only normalize postgres URLs.
    if not (scheme_norm == "postgres" or scheme_norm.startswith("postgresql")):
        return url

    if mode_norm == "async":
        desired = "postgresql+asyncpg"
        if scheme_norm in ("postgres", "postgresql"):
            return f"{desired}://{rest}"

        if scheme_norm.startswith("postgresql+") and scheme_norm != desired:
            # If a sync driver was provided, force asyncpg for the async engine.
            return f"{desired}://{rest}"

        return url

    # mode_norm == "sync"
    desired = "postgresql+psycopg"
    if scheme_norm in ("postgres", "postgresql"):
        return f"{desired}://{rest}"
    if scheme_norm == "postgresql+asyncpg":
        return f"{desired}://{rest}"
    if scheme_norm == "postgresql+psycopg2":
        # psycopg2 isn't in requirements; prefer psycopg.
        return f"{desired}://{rest}"
    return url


def _redact_database_url(url: str | None) -> str:
    """Redact credentials from a DATABASE_URL for safe logging."""
    if not url:
        return ""
    # Common form: scheme://user:password@host:port/db
    return re.sub(r"://([^:/?#]+):([^@/?#]+)@", r"://\1:***@", url)


def _create_ssl_context_for_database_url(database_url: str) -> ssl.SSLContext:
    """Create an SSL context for Postgres connections.

    Default behavior:
    - Use the system trust store for CA verification.
    - If `RDS_SSL_BUNDLE_PATH` exists (or `/app/rds-global-bundle.pem`), layer it in.
    - Honor `DB_SSL_CHECK_HOSTNAME` unless the DB host is an IP address (then
      disable hostname matching to avoid common proxy/VPC-endpoint mismatches).

    This helper is intentionally side-effect free w.r.t. networking.
    """

    ssl_context = ssl.create_default_context()

    bundle_path = (
        os.getenv("RDS_SSL_BUNDLE_PATH") or "/app/rds-global-bundle.pem"
    ).strip()
    if bundle_path:
        try:
            if pathlib.Path(bundle_path).exists():
                ssl_context.load_verify_locations(cafile=bundle_path)
        except Exception as e:
            print(
                f"[DB CONFIG] Warning: failed to load RDS SSL bundle from {bundle_path}: {e}",
                flush=True,
            )

    ssl_context.check_hostname = os.getenv(
        "DB_SSL_CHECK_HOSTNAME", "1"
    ).strip().lower() not in (
        "0",
        "false",
        "no",
    )

    # If we're connecting via an IP address (common with some proxies/VPC endpoints),
    # strict hostname checking will fail. Keep CA verification, but disable hostname
    # matching automatically in that case.
    try:
        host = (urlsplit(database_url).hostname or "").strip()
        if host and ssl_context.check_hostname:
            try:
                ipaddress.ip_address(host)
                ssl_context.check_hostname = False
                print(
                    "[DB CONFIG] DB host is an IP address; disabling SSL hostname checking (CA verification remains enabled)",
                    flush=True,
                )
            except ValueError:
                pass
    except Exception:
        pass

    return ssl_context


def _select_db_password() -> str | None:
    for key in (
        "DB_PASSWORD",
        "DATABASE_PASSWORD",
        "RDS_PASSWORD",
        "POSTGRES_PASSWORD",
        "DB_PASS",
        # Postgres-standard env var name used by many platforms/tooling.
        "PGPASSWORD",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if not raw:
            continue

        # Support AWS Secrets Manager JSON (ECS can inject the whole SecretString)
        # Example: {"username":"...","password":"...","host":"...","port":5432,"dbname":"..."}
        if raw.startswith("{") and raw.endswith("}"):
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    candidate = payload.get("password") or payload.get("db_password")
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
            except Exception:
                # Fall back to treating it as a raw string if parsing fails.
                pass

        return raw

    # Fallback: full secret JSON env var.
    payload = _select_db_secret_payload()
    if payload:
        candidate = payload.get("password") or payload.get("db_password")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def _select_db_user() -> str | None:
    for key in (
        "DB_USER",
        "DATABASE_USER",
        "DB_USERNAME",
        "DATABASE_USERNAME",
        "RDS_USERNAME",
        "POSTGRES_USER",
        # Postgres-standard env var name used by many platforms/tooling.
        "PGUSER",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if raw:
            return raw

    # If someone injected a whole Secrets Manager JSON into a password variable,
    # try to recover username from it.
    for key in ("DB_PASSWORD", "DATABASE_PASSWORD", "RDS_PASSWORD"):
        raw = (os.getenv(key) or "").strip()
        if raw.startswith("{") and raw.endswith("}"):
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    candidate = payload.get("username") or payload.get("user")
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
            except Exception:
                pass

    payload = _select_db_secret_payload()
    if payload:
        candidate = (
            payload.get("username") or payload.get("user") or payload.get("db_user")
        )
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def _select_db_host() -> str | None:
    for key in (
        "DB_HOST",
        "DATABASE_HOST",
        "RDS_HOST",
        "POSTGRES_HOST",
        # Postgres-standard
        "PGHOST",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if raw:
            return raw

    payload = _select_db_secret_payload()
    if payload:
        candidate = payload.get("host") or payload.get("hostname")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def _select_db_port() -> int | None:
    for key in (
        "DB_PORT",
        "DATABASE_PORT",
        "RDS_PORT",
        "POSTGRES_PORT",
        # Postgres-standard
        "PGPORT",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            return int(raw)
        except Exception:
            continue

    payload = _select_db_secret_payload()
    if payload:
        candidate = payload.get("port")
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.strip():
            try:
                return int(candidate.strip())
            except Exception:
                pass

    return None


def _select_db_name() -> str | None:
    for key in (
        "DB_NAME",
        "DB_DATABASE",
        "DATABASE_NAME",
        "DATABASE_DB",
        "POSTGRES_DB",
        # Postgres-standard
        "PGDATABASE",
    ):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip()
        if raw:
            return raw

    payload = _select_db_secret_payload()
    if payload:
        candidate = (
            payload.get("dbname") or payload.get("database") or payload.get("db")
        )
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def _encode_db_password(password: str) -> str:
    """URL-encode a password for safe embedding in DATABASE_URL.

    Important: we intentionally *do not* try to detect whether the password is
    already encoded. Real passwords can contain substrings like "%2F" which would
    be misinterpreted as percent-encoding inside a URL and get decoded, corrupting
    the password and causing authentication failures.

    If you truly have a pre-encoded password string, set DB_PASSWORD_URLENCODED=1
    to skip encoding.
    """
    if not password:
        return password

    if os.getenv("DB_PASSWORD_URLENCODED", "0").strip().lower() in ("1", "true", "yes"):
        return password

    # Encode all reserved characters, including '/', ':' and '%'.
    return quote_plus(password, safe="")


_db_password = _select_db_password()
_db_user = _select_db_user()
_db_host = _select_db_host()
_db_port = _select_db_port()
_db_name = _select_db_name()
_postgres_password = os.getenv("POSTGRES_PASSWORD")

# Support ECS-style placeholders in DATABASE_URL for username as well.
if DATABASE_URL and _db_user:
    DATABASE_URL = DATABASE_URL.replace("${DB_USER}", _db_user)
    DATABASE_URL = DATABASE_URL.replace("$DB_USER", _db_user)
    DATABASE_URL = DATABASE_URL.replace("${DB_USERNAME}", _db_user)
    DATABASE_URL = DATABASE_URL.replace("$DB_USERNAME", _db_user)

# Support ECS-style secrets where DATABASE_URL includes a ${DB_PASSWORD} placeholder.
if DATABASE_URL and _db_password:
    encoded_password = _encode_db_password(_db_password)
    DATABASE_URL = DATABASE_URL.replace("${DB_PASSWORD}", encoded_password)
    DATABASE_URL = DATABASE_URL.replace("$DB_PASSWORD", encoded_password)
elif DATABASE_URL and "${DB_PASSWORD}" in DATABASE_URL:
    print(
        "[DB CONFIG] DATABASE_URL contains ${DB_PASSWORD} but no password env var was found",
        flush=True,
    )

# Support ECS-style placeholders for host/port/dbname as well.
if DATABASE_URL and _db_host:
    DATABASE_URL = DATABASE_URL.replace("${DB_HOST}", _db_host)
    DATABASE_URL = DATABASE_URL.replace("$DB_HOST", _db_host)
    DATABASE_URL = DATABASE_URL.replace("${PGHOST}", _db_host)
    DATABASE_URL = DATABASE_URL.replace("$PGHOST", _db_host)

if DATABASE_URL and _db_port:
    DATABASE_URL = DATABASE_URL.replace("${DB_PORT}", str(_db_port))
    DATABASE_URL = DATABASE_URL.replace("$DB_PORT", str(_db_port))
    DATABASE_URL = DATABASE_URL.replace("${PGPORT}", str(_db_port))
    DATABASE_URL = DATABASE_URL.replace("$PGPORT", str(_db_port))

if DATABASE_URL and _db_name:
    DATABASE_URL = DATABASE_URL.replace("${DB_NAME}", _db_name)
    DATABASE_URL = DATABASE_URL.replace("$DB_NAME", _db_name)
    DATABASE_URL = DATABASE_URL.replace("${PGDATABASE}", _db_name)
    DATABASE_URL = DATABASE_URL.replace("$PGDATABASE", _db_name)

# If DATABASE_URL is present but omits a password, inject DB_USER/DB_PASSWORD if available.
if DATABASE_URL:
    before = DATABASE_URL
    DATABASE_URL = _inject_credentials_into_database_url(
        DATABASE_URL,
        user=_db_user,
        password=_db_password or _postgres_password,
    )
    try:
        parsed_before = urlsplit(before)
        parsed_after = urlsplit(DATABASE_URL)
        if (parsed_before.password is None) and (parsed_after.password is None):
            # Don't spam logs in local/docker defaults.
            if os.getenv("AWS_EXECUTION_ENV") and parsed_before.username:
                print(
                    "[DB CONFIG] Warning: DATABASE_URL has username but no password; set DB_PASSWORD (or include password in DATABASE_URL)",
                    flush=True,
                )
    except Exception:
        pass

# Support task definitions that still include a placeholder like <RDS_PASSWORD>
if DATABASE_URL and "<RDS_PASSWORD>" in DATABASE_URL:
    fallback_password = _db_password or _postgres_password
    if fallback_password:
        encoded_password = _encode_db_password(fallback_password)
        DATABASE_URL = DATABASE_URL.replace("<RDS_PASSWORD>", encoded_password)
    else:
        print(
            "[DB CONFIG] DATABASE_URL contains <RDS_PASSWORD> but no password env var was found",
            flush=True,
        )

# Build DATABASE_URL from POSTGRES_* if not explicitly provided.
if not DATABASE_URL:
    _pg_user = os.getenv("POSTGRES_USER")
    _pg_host = os.getenv("POSTGRES_HOST")
    _pg_port = os.getenv("POSTGRES_PORT")
    _pg_db = os.getenv("POSTGRES_DB")
    _pg_password = _select_db_password()
    if _pg_user and _pg_host and _pg_port and _pg_db and _pg_password:
        encoded_password = _encode_db_password(_pg_password)
        DATABASE_URL = f"postgresql+asyncpg://{_pg_user}:{encoded_password}@{_pg_host}:{_pg_port}/{_pg_db}"

# Build DATABASE_URL from a full secret JSON if not provided.
if not DATABASE_URL:
    payload = _select_db_secret_payload()
    if payload:
        secret_user = (
            payload.get("username") or payload.get("user") or payload.get("db_user")
        )
        secret_password = payload.get("password") or payload.get("db_password")
        secret_host = payload.get("host") or payload.get("hostname")
        secret_port = payload.get("port")
        secret_db = (
            payload.get("dbname") or payload.get("database") or payload.get("db")
        )

        if isinstance(secret_port, str):
            try:
                secret_port = int(secret_port.strip())
            except Exception:
                secret_port = None

        if (
            isinstance(secret_user, str)
            and isinstance(secret_password, str)
            and isinstance(secret_host, str)
            and isinstance(secret_db, str)
        ):
            secret_user = secret_user.strip()
            secret_password = secret_password.strip()
            secret_host = secret_host.strip()
            secret_db = secret_db.strip()

            if secret_user and secret_password and secret_host and secret_db:
                encoded_password = _encode_db_password(secret_password)
                port_part = (
                    f":{int(secret_port)}" if isinstance(secret_port, int) else ""
                )
                DATABASE_URL = f"postgresql+asyncpg://{secret_user}:{encoded_password}@{secret_host}{port_part}/{secret_db}"

# If no explicit DATABASE_URL, use environment-based defaults
if DATABASE_URL is None:
    _default_url = _DEFAULT_DOCKER_DB_URL
    # Prefer host-mapped Postgres when running on the host.
    if (not _in_docker_fs) or os.getenv("ENV") == "local":
        _default_url = _DEFAULT_LOCAL_DB_URL
    DATABASE_URL = _default_url


IS_ALEMBIC = os.getenv("ALEMBIC", "0") == "1"
DATABASE_URL = _normalize_database_url(
    DATABASE_URL, mode=("sync" if IS_ALEMBIC else "async")
)


# If we're on the host (not in Docker), rewrite docker-compose service hostname to localhost.
if not _running_in_aws and not _in_docker_fs and DATABASE_URL:
    DATABASE_URL = _rewrite_docker_db_hostname_for_host(DATABASE_URL)


# Determine if running locally (Docker Compose) or in production (RDS)
is_local = (
    os.getenv("ENV", "local") == "local"
    or (_in_docker_fs and not _running_in_aws)
    or "@db:" in (DATABASE_URL or "")
    or "@127.0.0.1:" in (DATABASE_URL or "")
    or "@localhost:" in (DATABASE_URL or "")
)

if is_local:
    # Local: No SSL for Docker Compose Postgres
    print(f"[DB CONFIG] DATABASE_URL={_redact_database_url(DATABASE_URL)}")
    print("[DB CONFIG] Local mode: SSL disabled")
    connect_args = {}
else:
    # Production/RDS: Enforce SSL
    ssl_context = _create_ssl_context_for_database_url(DATABASE_URL)
    bundle_path = (
        os.getenv("RDS_SSL_BUNDLE_PATH") or "/app/rds-global-bundle.pem"
    ).strip()

    print(f"[DB CONFIG] DATABASE_URL={_redact_database_url(DATABASE_URL)}")
    print(
        "[DB CONFIG] SSL context bundle:",
        (
            bundle_path
            if bundle_path and pathlib.Path(bundle_path).exists()
            else "(system)"
        ),
        flush=True,
    )
    print(
        "[DB CONFIG] SSL hostname check:",
        bool(getattr(ssl_context, "check_hostname", False)),
        flush=True,
    )
    connect_args = {"ssl": ssl_context}

if IS_ALEMBIC:
    # For migrations, use a sync engine.
    engine = create_engine(DATABASE_URL, echo=False, poolclass=NullPool)
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args,
    )

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    print("[DB] get_db() called - creating AsyncSessionLocal", flush=True)
    try:
        async with AsyncSessionLocal() as session:
            print("[DB] get_db() - AsyncSessionLocal created successfully", flush=True)
            yield session
            print("[DB] get_db() - session closed", flush=True)
    except Exception as e:
        # Note: Exceptions raised by downstream dependencies/handlers (auth, validation,
        # SQL errors, etc.) propagate back through this generator. The session itself
        # may have been created successfully.
        print(
            f"[DB] get_db() - Request error ({type(e).__name__}): {e}",
            flush=True,
        )
        raise
