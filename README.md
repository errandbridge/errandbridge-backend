# ErrandBridge Backend

FastAPI backend for ErrandBridge with Strawberry GraphQL, PostgreSQL, Prometheus metrics, and optional integrations for Stripe, OAuth, SMTP, Twilio, Microsoft Graph, and OpenAI.

## Quick start

This backend-only repository uses the repository root as the backend app directory.

```bash
cp .env.example .env
./scripts/dev_stack.sh start
```

If you need to rebuild images after dependency or Dockerfile changes, run:

```bash
docker compose up --build -d db api ml prometheus grafana
./scripts/dev_stack.sh status
```

Primary local URLs:

- API root: <http://localhost:8001/>
- OpenAPI docs: <http://localhost:8001/docs>
- OpenAPI schema JSON: <http://localhost:8001/openapi.json>
- GraphQL: <http://localhost:8001/graphql>
- Metrics: <http://localhost:8001/metrics>

Full Swagger/API usage notes live in
`docs/SWAGGER_API_DOCUMENTATION.md`.

One-time-code login endpoints are available at:

- `POST /tso/request-code` and `POST /login/request-code`
- `POST /tso/verify` and `POST /login/verify`

They are visible in Swagger and accept the token/code payload shape documented
in `docs/SWAGGER_API_DOCUMENTATION.md`.

## Partner / open API status

Yes — ErrandBridge already exposes an integration-ready API surface for other systems:

- **REST/OpenAPI** via FastAPI:
  - Interactive docs: `/docs`
  - Machine-readable schema: `/openapi.json`
- **GraphQL** via Strawberry:
  - Endpoint: `/graphql`

For frontend-only contractors, share the Swagger/OpenAPI documentation and the
separate frontend-only repo instead of this full backend package.

Current integration notes:

- The backend exposes a broad application API today (local spec currently publishes many routes, including auth, errands, tracking, support, payments, and admin operations).
- Most business operations require **Bearer token** authentication.
- Public/no-auth examples already available include:
  - `GET /health`
  - `GET /ready`
  - `GET /public/errands/{reference_number}`
  - `POST /pilot-employment/applications`
  - `POST /prompt/suggest`
  - `POST /prompt/ai-suggest`
- Webhook-style integration already exists for Stripe:
  - `POST /payments/webhook`
  - `POST /webhooks/stripe`

For another company to integrate with EB today, the safest path is:

1. Start from `/docs` or `/openapi.json` for REST discovery.
2. Use `/graphql` only when the partner specifically wants GraphQL.
3. Issue a dedicated EB account/service identity for the partner instead of sharing a human admin login.
4. Limit the partner to the subset of endpoints they actually need.

Important caveat:

- The current API is **openly documented**, but it is not yet a fully curated, versioned **partner-only namespace** (for example `/api/partner/v1/...`).
- If EB wants a cleaner B2B product surface later, the next step would be a dedicated partner API with scoped credentials, rate limits, and endpoint allow-listing.

## Local stack extras

- ML health: <http://localhost:8011/health>
- ML metrics: <http://localhost:8011/metrics>
- Prometheus: <http://localhost:9090>
- Grafana: <http://localhost:3001>
- Mailpit: <http://localhost:8025>
- Postgres host port: `localhost:5433`

Grafana local notes:

- Grafana is intentionally exposed on host port `3001` while the container still listens on internal port `3000`.
- Grafana is exposed on all host interfaces via `3001:3000`, so you can reach it with `localhost`, your Mac's LAN IP, or any other IP assigned to this machine.
- If Grafana is not opening, first run `./scripts/dev_stack.sh status` or `./scripts/dev_stack.sh start`; the most common cause is that the local compose stack is simply not running.
- Generated Grafana redirects are no longer pinned to `localhost`, so opening `http://<your-ip>:3001` will stay on that host/IP instead of bouncing back to `localhost`.
- On Docker Desktop for macOS, this same Mac may still fail when curling its own LAN IP; use `localhost` on this machine and `http://<lan-ip>:3001` from other devices on the network.
- If you have an older persisted Grafana volume, the admin password may remain whatever was set on first boot; if `admin/admin` no longer works, reset the `grafana_data` volume.

Grafana defaults:

- Username: `admin`
- Password: `admin`

For local development, `./scripts/dev_stack.sh start` and `./scripts/dev_stack.sh restart`
re-assert the Grafana admin password so persisted old credentials do not keep
breaking the documented login.

You can override those defaults in `.env` with:

```bash
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

`GRAFANA_ADMIN_PASSWORD` is re-applied on every local start/restart. If you
change `GRAFANA_ADMIN_USER`, that new username applies immediately for a fresh
Grafana volume; existing local `grafana_data` volumes keep the current admin
login until you recreate the volume.

To recreate only Grafana's local data volume and make a new admin username take
effect without touching Postgres, run:

```bash
./scripts/dev_stack.sh reset-grafana-volume
```

That resets Grafana-local users/settings/session state, but it does **not**
remove your backend database data.

Postgres defaults:

- User: `postgres`
- Password: `postgres`
- Database: `errandbridge`

## Environment setup

```bash
cp .env.example .env
```

Keep secrets in `.env` or your secret manager, not in tracked source files.

## Local stack helper

The repo includes a helper script for the day-to-day backend stack:

```bash
./scripts/dev_stack.sh start
./scripts/dev_stack.sh status
./scripts/dev_stack.sh logs
./scripts/dev_stack.sh reset-grafana-admin
./scripts/dev_stack.sh reset-grafana-volume
./scripts/dev_stack.sh stop
```

`start` waits for the API, ML service, Prometheus, and Grafana to respond before returning, which makes `http://localhost:3001` much more predictable during local development.

It also prints your detected LAN IP when available so you can open Grafana from another device using `http://<lan-ip>:3001`.

If Grafana says `Invalid username or password`, run `./scripts/dev_stack.sh reset-grafana-admin` and then sign in with `admin` / `admin`.

If you customized `GRAFANA_ADMIN_PASSWORD`, sign in with the password from your
`.env` file instead.

If you changed `GRAFANA_ADMIN_USER`, run `./scripts/dev_stack.sh reset-grafana-volume`
once so Grafana boots with the new username on a fresh local Grafana volume.

## Backend tests

Run backend tests from the project virtualenv so FastAPI/Stawberry dependencies are available:

```bash
source .venv/bin/activate
python -m pytest -q
```

## Payments

Stripe endpoints:

- `POST /payments/checkout-session`
- `POST /payments/verify-session`
- `POST /payments/webhook`
- `POST /webhooks/stripe`

Important Stripe variables:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PLUS_PRICE_ID`
- `STRIPE_SUCCESS_URL`
- `STRIPE_CANCEL_URL`

## OAuth

Google:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_IDS`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`

Apple:

- `APPLE_CLIENT_ID`
- `APPLE_REDIRECT_URI`
- `APPLE_TEAM_ID`
- `APPLE_KEY_ID`
- `APPLE_PRIVATE_KEY`

Optional pilot overrides are also supported for both providers.

## Smoke tests

Standard smoke test:

```bash
/Users/admin/Desktop/ErrandBridge/.venv/bin/python scripts/smoke_test.py
```

No-OTP smoke test:

```bash
ERRANDBRIDGE_BASE_URL=http://localhost:8001 /Users/admin/Desktop/ErrandBridge/.venv/bin/python scripts/smoke_no_otp.py
```

Or inside Docker Compose:

```bash
docker compose exec -T api /usr/local/bin/python scripts/smoke_no_otp.py
```

## Android internal-testing users

```bash
source .venv/bin/activate
python scripts/ensure_android_tester_users.py --reset-existing
```

That command ensures these shared QA accounts exist and can sign in immediately:

- `customer_test_001@example.com`
- `pilot_test_001@example.com`

Default password:

- `Password123!`

## Production deployment best practice

Always build the production backend image for `linux/amd64`.

Recommended flow:

```bash
python3 scripts/build_push_prod_image.py \
   --repo 389068786915.dkr.ecr.us-east-1.amazonaws.com/errandbridge-prod-api \
   --tag authsafe-$(date +%Y%m%d-%H%M%S)

python3 scripts/deploy_prod_image.py \
   --cluster errandbridge-prod-cluster \
   --service errandbridge-prod-api \
   --container api \
   --image 389068786915.dkr.ecr.us-east-1.amazonaws.com/errandbridge-prod-api:<tag> \
   --wait-stable
```

Notes:

- `scripts/build_push_prod_image.py` uses `docker buildx build --platform linux/amd64 --push`.
- `scripts/deploy_prod_image.py` makes the ECS task definition explicit about `LINUX` + `X86_64`.

After deployment, verify:

- `GET https://api.errandbridge.com/health`
- `POST https://api.errandbridge.com/auth/signup`

## Production troubleshooting

### `/health` reports `unhealthy` with DB auth errors

If <https://api.errandbridge.com/health> returns values such as:

- `"database":"disconnected"`
- `"error_code":"db_auth_failed"`

then the container can reach Postgres but is using the wrong password.

Common production pattern:

- `DATABASE_URL=postgresql+asyncpg://postgres:${DB_PASSWORD}@<rds-endpoint>:5432/errandbridge`
- `DB_PASSWORD` injected from AWS Secrets Manager into ECS

More robust pattern:

- `DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@<rds-endpoint>:5432/errandbridge`
- `DB_USER` from the RDS-managed secret username field
- `DB_PASSWORD` from the RDS-managed secret password field

Fix checklist:

1. Confirm which secret ECS injects for `DB_PASSWORD`.
2. Confirm the RDS master user and that the secret matches it.
3. Make the DB password and secret agree.
4. Force a new ECS deployment.
5. Re-run `GET https://api.errandbridge.com/health`.

### `/health` returns HTTP 200 even when unhealthy

If `/health` returns an unhealthy JSON body with HTTP 200, you are probably hitting an older deployed build. Redeploy the backend so the endpoint reports the proper failure status.

## Project structure

- `main.py` - FastAPI app entrypoint
- `schema.py` - Strawberry GraphQL schema
- `database.py` - DB connection
- `docker-compose.yml` - Multi-service orchestration
- `Dockerfile` - API container
- `.env.example` - Example environment variables

## Security note

Do not commit real secrets to version-controlled files. Rotate any secret that has been exposed outside secure storage.
