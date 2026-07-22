from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
import os

# Ensure Alembic runs in "sync" mode when importing database.py.
# This also normalizes postgres URL schemes and resolves ECS-style placeholders
# like ${DB_PASSWORD} using injected secret env vars.
os.environ.setdefault("ALEMBIC", "1")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base, DATABASE_URL as RESOLVED_DATABASE_URL  # noqa: E402

# Ensure models are imported so SQLAlchemy registers them on Base.metadata
import models  # noqa: F401

config = context.config
# Our alembic.ini is intentionally minimal, so only set up logging if present.
if config.config_file_name and config.get_section("formatters") is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    # Prefer the resolved URL when available (handles ${DB_PASSWORD} placeholders).
    if RESOLVED_DATABASE_URL:
        url = RESOLVED_DATABASE_URL
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    section = config.get_section(config.config_ini_section) or {}

    # Use the resolved URL from database.py when available.
    # This supports ECS-style placeholders like ${DB_PASSWORD} and normalizes
    # postgres schemes to a sync driver for migrations.
    if RESOLVED_DATABASE_URL:
        section["sqlalchemy.url"] = RESOLVED_DATABASE_URL

    # Prefer keeping the configured driver. In Docker/local dev we ship asyncpg,
    # while psycopg2 may not be installed.
    # Alembic can run with asyncpg as long as we use the synchronous engine API.

    connectable = engine_from_config(
        section,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
