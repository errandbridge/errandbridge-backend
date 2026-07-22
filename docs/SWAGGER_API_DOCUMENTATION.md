# ErrandBridge Swagger / OpenAPI Documentation

Last updated: 2026-07-22

## Purpose

ErrandBridge exposes machine-readable REST API documentation through FastAPI/OpenAPI and interactive Swagger UI. This document explains where to find it, how frontend or external developers should use it, and what should not be shared publicly.

## Swagger URLs

### Production

- Swagger UI: `https://api.errandbridge.com/docs`
- OpenAPI JSON: `https://api.errandbridge.com/openapi.json`
- GraphQL endpoint: `https://api.errandbridge.com/graphql`
- Health check: `https://api.errandbridge.com/health`
- Readiness check: `https://api.errandbridge.com/ready`

### Local development

When the backend is running locally:

- Swagger UI: `http://localhost:8001/docs`
- OpenAPI JSON: `http://localhost:8001/openapi.json`
- GraphQL endpoint: `http://localhost:8001/graphql`
- Metrics: `http://localhost:8001/metrics`

Recommended local backend start:

```bash
cd errandbridge-backend
docker compose up --build
```

Or use the helper from the workspace root:

```bash
./scripts/dev_up.sh backend-only
```

## What Swagger contains

The OpenAPI schema is generated directly from the FastAPI app in `errandbridge-backend/main.py` and included routers. It includes REST routes for:

- Auth and user session flows
- Errand creation and attachment workflows
- Pilot delivery/profile workflows
- Tracking, incidents, support, analytics, and voice routes
- Stripe payments and checkout verification
- Promo codes
- Public routes such as health/readiness and public errand summaries

The backend also exposes GraphQL through Strawberry at `/graphql`. GraphQL is referenced from the OpenAPI external docs section, but GraphQL operations are explored directly at `/graphql`, not inside Swagger.

Swagger groups endpoints into numbered sections so the most common workflows are easier to find:

- `00 System & Health`
- `01 Auth & Account`
- `02 One-time Code Login`
- `03 Errands & Attachments`
- `04 Pilots & Delivery`
- `05 Tracking & Live Location`
- `06 Payments & Subscriptions`
- `07 Promo Codes`
- `08 Support & Incidents`
- `09 Public & Reviews`
- `10 Assistant & AI`
- `11 Analytics & Voice`
- `12 Admin`
- `13 GraphQL`

Inside each section, Swagger UI sorts operations by URL path (`operationsSorter: "alpha"`).
That keeps all actions for the same resource near each other, for example `GET`, `POST`,
`PUT`, `PATCH`, and `DELETE` variants of a related endpoint.

Public REST v1 endpoints use `/v1/...` paths. Legacy `/api/v1/...` aliases remain callable
for older deployed clients, but they are hidden from Swagger so external developers see the
clean canonical API surface.

## Authentication

Most business endpoints require a JWT bearer token. In Swagger UI, use **Authorize** instead
of manually typing an `authorization` header into each endpoint:

```text
Authorization: Bearer <token>
```

Swagger includes a `BearerAuth` security scheme. In Swagger UI:

1. Open `/docs`.
2. Click **Authorize**.
3. Paste the token value using the `Bearer <token>` format if the UI does not add it automatically.
4. Run authenticated requests from the relevant endpoint panels.

Do not share admin or production user tokens with external developers. Create a test user or service identity for controlled integration work.

### User UUIDs

Every user has a stable public UUID exposed as `user_uuid` in REST responses and `userUuid`
in GraphQL/camel-case payloads. Use this UUID when an integration needs to map records to a
specific user instead of exposing internal numeric database IDs.

Important: `user_uuid` is an identifier, not an authentication secret. Protected endpoints
must still use a Bearer access token so one user cannot access another user's data just by
knowing their UUID.

### Refresh tokens

REST login/signup responses now include both:

- `access_token`: short/session token used in `Authorization: Bearer <token>`.
- `refresh_token`: longer-lived token used only to request a new session.

Use the refresh token endpoint when the access token expires:

```text
POST /auth/refresh
```

Request body:

```json
{
  "refresh_token": "<refresh-token>"
}
```

Successful response shape matches login and includes a fresh token pair:

```json
{
  "access_token": "<new-access-token>",
  "refresh_token": "<new-refresh-token>",
  "token_type": "bearer",
  "user_id": 448,
  "user_uuid": "2b84d1fd-3ed3-44b0-9470-f8f1f9ad9356",
  "email": "testuser@example.com",
  "first_name": "Test",
  "last_name": "User",
  "phone": null,
  "is_email_verified": true,
  "is_admin": false
}
```

Security notes:

- Do not send `refresh_token` as a Bearer token to business endpoints.
- Store refresh tokens more carefully than access tokens; for mobile, prefer the platform secure store/keychain.
- The refresh token lifetime defaults to 30 days and can be adjusted with `JWT_REFRESH_EXPIRES_DAYS`.

## One-time code login endpoints

ErrandBridge exposes a two-step one-time-code flow for tokenized sign-in links.
These endpoints are documented in Swagger under `02 One-time Code Login`. Both
`/tso/*` and `/login/*` paths are exposed so integrators can use the naming style
that fits their client.

### Request a code

```text
POST /tso/request-code
POST /login/request-code
```

Request body:

```json
{
  "token": "<signed-login-link-token>"
}
```

The `token` must be a short-lived backend-signed JWT with audience
`login-link`. It should identify the user through `sub`, `email`, `identifier`,
or `phone` claims.

Successful response shape:

```json
{
  "status": "SUCCESS",
  "code": 0,
  "message": "Code sent",
  "data": {
    "deliveryChannel": "email",
    "maskedDestination": "cl***@example.com",
    "expiresInSeconds": 600
  },
  "timestamp": "2026-07-20T19:42:59.464Z",
  "error": null,
  "path": "/tso/request-code"
}
```

### Verify a code

```text
POST /tso/verify
POST /login/verify
```

Request body:

```json
{
  "token": "<signed-login-link-token>",
  "code": "483921"
}
```

Successful response shape:

```json
{
  "status": "SUCCESS",
  "code": 0,
  "message": "Code verified",
  "data": {
    "sessionToken": "<time-limited-session-token>",
    "refreshToken": "<refresh-token>",
    "userUuid": "2b84d1fd-3ed3-44b0-9470-f8f1f9ad9356",
    "expiresInSeconds": 3600,
    "tokenType": "bearer"
  },
  "timestamp": "2026-07-20T19:41:41.640Z",
  "error": null,
  "path": "/tso/verify"
}
```

The returned `sessionToken` is a time-limited JWT. Its lifetime defaults to 60
minutes and can be adjusted with `LOGIN_CODE_SESSION_MINUTES`.

## Public/no-auth endpoints

These endpoints are safe starting points for smoke checks:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /public/errands/{reference_number}`
- `POST /pilot-employment/applications`
- `POST /prompt/suggest`

Some AI, payment, or admin behavior may still depend on environment variables and service configuration.

## Customer errands endpoints

Authenticated customer errands are documented under `03 Errands & Attachments`:

- `GET /errands` — list errands owned by the authenticated user.
- `GET /errands/{errand_id}` — get one errand owned by the authenticated user.
- `POST /errands` — create a new errand.
- `GET /errands/{errand_id}/attachments` — list attachments for one owned errand.
- `POST /errands/{errand_id}/attachments` — upload an attachment for one owned errand.

Use `/admin/errands` only for admin/operator dashboards. Customer integrations should use
`GET /errands` with a Bearer access token.

## Payment endpoints

Stripe payment routes are documented under the `payments` tag in Swagger. Key endpoints include:

- `GET /payments/health`
- `POST /payments/quote`
- `POST /payments/checkout-session`
- `POST /payments/verify-session`
- `GET /payments/subscription/me`
- `POST /payments/webhook`
- `POST /webhooks/stripe`

Important rule: Stripe secret keys, webhook secrets, and live tokens must never be placed in frontend code or shared in screenshots of Swagger requests.

## Frontend integration base URLs

The frontend should call the backend as a separate service:

- Production API base: `https://api.errandbridge.com`
- Production GraphQL: `https://api.errandbridge.com/graphql`
- Local API base: `http://localhost:8001`
- Local GraphQL: `http://localhost:8001/graphql`

The frontend source should be configured through environment variables, not by copying backend source files into the frontend package.

## Exporting the OpenAPI schema

For an external developer or API client generator, export the schema from the running backend:

```bash
curl -sS https://api.errandbridge.com/openapi.json -o errandbridge-openapi.json
```

For local development:

```bash
curl -sS http://localhost:8001/openapi.json -o errandbridge-openapi.local.json
```

The exported JSON can be imported into Postman, Insomnia, Swagger Editor, or OpenAPI client generators.

## What to give an external frontend developer

Give them:

1. The frontend-only handoff bundle generated by `scripts/export_frontend_handoff.sh`.
2. This Swagger/OpenAPI document.
3. A test API base URL and test login credentials, if needed.
4. The exact feature scope they are allowed to work on.

Do not give them:

- The full backend directory unless they are explicitly hired for backend work.
- `.env` files with secrets.
- Production admin credentials.
- AWS, Stripe, Apple, Google Play, SMTP, OAuth, or database secrets.

## Source of truth

- FastAPI app: `errandbridge-backend/main.py`
- Payment routes: `errandbridge-backend/app/routes/payments.py`
- GraphQL schema: `errandbridge-backend/schema.py`
- Frontend API resolver: `errandbridge-frontend/src/lib/apiBaseUrl.js`
