import importlib

import database


def test_select_db_password_prefers_pgpwd_when_set(monkeypatch):
	# Ensure all other candidate keys are unset.
	for key in (
		"DB_PASSWORD",
		"DATABASE_PASSWORD",
		"RDS_PASSWORD",
		"POSTGRES_PASSWORD",
		"DB_PASS",
	):
		monkeypatch.delenv(key, raising=False)

	monkeypatch.setenv("PGPASSWORD", "pg-secret")
	assert database._select_db_password() == "pg-secret"


def test_select_db_user_supports_pguser(monkeypatch):
	for key in (
		"DB_USER",
		"DATABASE_USER",
		"DB_USERNAME",
		"DATABASE_USERNAME",
		"RDS_USERNAME",
		"POSTGRES_USER",
	):
		monkeypatch.delenv(key, raising=False)

	monkeypatch.setenv("PGUSER", "pg-user")
	assert database._select_db_user() == "pg-user"


def test_selectors_support_rds_secret_json(monkeypatch):
	# Clear explicit DB env vars so we fall back to the JSON payload.
	for key in (
		"DB_USER",
		"DB_PASSWORD",
		"DATABASE_USER",
		"DATABASE_PASSWORD",
		"RDS_USERNAME",
		"RDS_PASSWORD",
		"POSTGRES_PASSWORD",
		"POSTGRES_USER",
		"POSTGRES_HOST",
		"POSTGRES_PORT",
		"POSTGRES_DB",
		"PGUSER",
		"PGPASSWORD",
		"PGHOST",
		"PGPORT",
		"PGDATABASE",
		"DB_HOST",
		"DB_PORT",
		"DB_NAME",
	):
		monkeypatch.delenv(key, raising=False)

	monkeypatch.setenv(
		"RDS_SECRET_JSON",
		'{"username":"postgres","password":"p@ss:word","host":"db.example","port":5432,"dbname":"errandbridge"}',
	)
	assert database._select_db_user() == "postgres"
	assert database._select_db_password() == "p@ss:word"
	assert database._select_db_host() == "db.example"
	assert database._select_db_port() == 5432
	assert database._select_db_name() == "errandbridge"


def test_builds_database_url_from_rds_secret_json_when_missing(monkeypatch):
	# This test reloads the module because DATABASE_URL is constructed at import time.
	monkeypatch.delenv("DATABASE_URL", raising=False)
	# Clear POSTGRES_* so the module doesn't synthesize DATABASE_URL from them.
	for key in (
		"POSTGRES_USER",
		"POSTGRES_PASSWORD",
		"POSTGRES_HOST",
		"POSTGRES_PORT",
		"POSTGRES_DB",
	):
		monkeypatch.delenv(key, raising=False)
	# Keep local mode so we don't require /app/rds-global-bundle.pem in tests.
	monkeypatch.setenv("ENV", "local")
	# Prevent load_dotenv() from pulling DATABASE_URL from a local .env during reload.
	monkeypatch.setenv("AWS_EXECUTION_ENV", "test")
	monkeypatch.setenv(
		"RDS_SECRET_JSON",
		'{"username":"postgres","password":"p@ss:word","host":"db.example","port":5432,"dbname":"errandbridge"}',
	)

	importlib.reload(database)
	assert database.DATABASE_URL
	assert database.DATABASE_URL.startswith("postgresql+")
	# Password must be URL-encoded when inserted into the URL.
	assert "p%40ss%3Aword" in database.DATABASE_URL
