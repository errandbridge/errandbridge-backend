#!/bin/sh
set -eu

ENV_NAME="${ENV:-${BACKEND_ENVIRONMENT:-}}"
ENV_NAME_LOWER="$(printf "%s" "$ENV_NAME" | tr '[:upper:]' '[:lower:]')"
RUNNING_IN_AWS="${AWS_EXECUTION_ENV:-}"

# Only run migrations for non-local environments (especially in AWS/ECS).
# In local dev we use docker-compose and typically manage migrations manually.
if [ "$ENV_NAME_LOWER" = "local" ] && [ -z "$RUNNING_IN_AWS" ]; then
  echo "[prestart] ENV=local and not running in AWS; skipping alembic upgrade"
  exit 0
fi

if [ "${RUN_ALEMBIC_UPGRADE_ON_STARTUP:-1}" != "1" ]; then
  echo "[prestart] RUN_ALEMBIC_UPGRADE_ON_STARTUP!=1; skipping alembic upgrade"
  exit 0
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[prestart] DATABASE_URL is not set; cannot run migrations" >&2
  exit 1
fi

echo "[prestart] Running alembic upgrade head (ENV=${ENV_NAME_LOWER:-unset})"

# Alembic env.py resolves ECS placeholders (e.g. ${DB_PASSWORD}) and normalizes drivers.
alembic upgrade head

echo "[prestart] Alembic migrations complete"
