from fastapi.testclient import TestClient
from types import SimpleNamespace

from main import app


def test_checkout_success_url_uses_request_origin_when_allowed(monkeypatch):
    # Explicit URLs unset => derive from allowed origin.
    monkeypatch.delenv("STRIPE_SUCCESS_URL", raising=False)
    monkeypatch.delenv("STRIPE_CANCEL_URL", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")

    # Import after env setup so helper functions read current env values.
    from app.routes import payments as payments_module

    # Build a minimal request stub.
    class _Req:
        headers = {"origin": "http://localhost:3000"}

    origin = payments_module._resolve_frontend_origin(_Req())
    assert origin == "http://localhost:3000"

    assert payments_module._build_success_url(origin) == (
        "http://localhost:3000/payment/success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert (
        payments_module._build_cancel_url(origin)
        == "http://localhost:3000/payment/cancel"
    )


def test_checkout_success_url_allows_cra_fallback_ports_by_default(monkeypatch):
    """CRA will prompt to use 3001+ if 3000 is occupied.

    Stripe return URLs must still resolve back to the current localhost origin.
    """

    monkeypatch.delenv("PAYMENTS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("OAUTH_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("STRIPE_SUCCESS_URL", raising=False)
    monkeypatch.delenv("STRIPE_CANCEL_URL", raising=False)
    monkeypatch.setenv("ENV", "local")
    # Simulate a minimal local env that doesn't enumerate all possible CRA ports.
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")

    from app.routes import payments as payments_module

    class _Req:
        headers = {"origin": "http://localhost:3002"}

    origin = payments_module._resolve_frontend_origin(_Req())
    assert origin == "http://localhost:3002"
    assert payments_module._build_success_url(origin) == (
        "http://localhost:3002/payment/success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert (
        payments_module._build_cancel_url(origin)
        == "http://localhost:3002/payment/cancel"
    )


def test_checkout_success_url_does_not_use_unallowed_origin(monkeypatch):
    monkeypatch.delenv("STRIPE_SUCCESS_URL", raising=False)
    monkeypatch.delenv("STRIPE_CANCEL_URL", raising=False)
    # Allowed origins do not include evil.example
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://www.errandbridge.com")

    from app.routes import payments as payments_module

    class _Req:
        headers = {"origin": "https://evil.example"}

    origin = payments_module._resolve_frontend_origin(_Req())
    assert origin is None

    # Falls back to hard default when no explicit env is set.
    assert payments_module._build_success_url(origin) == (
        "https://www.errandbridge.com/payment/success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert (
        payments_module._build_cancel_url(origin)
        == "https://www.errandbridge.com/payment/cancel"
    )


def test_payments_allowed_origins_override_is_authoritative(monkeypatch):
    monkeypatch.delenv("STRIPE_SUCCESS_URL", raising=False)
    monkeypatch.delenv("STRIPE_CANCEL_URL", raising=False)
    # Even though localhost is in built-in defaults, an explicit payments override
    # should restrict Stripe return URLs.
    monkeypatch.setenv("PAYMENTS_ALLOWED_ORIGINS", "https://www.errandbridge.com")

    from app.routes import payments as payments_module

    class _Req:
        headers = {"origin": "http://localhost:3000"}

    origin = payments_module._resolve_frontend_origin(_Req())
    assert origin is None


def test_stripe_webhook_accepts_payload_without_metadata():
    client = TestClient(app)
    payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {}}},
    }

    response = client.post("/webhooks/stripe", json=payload)
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_payments_webhook_alias_accepts_payload():
    client = TestClient(app)
    payload = {
        "id": "evt_test_456",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {}}},
    }

    response = client.post("/payments/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_payments_health_reports_not_configured_when_missing_env(monkeypatch):
    # Ensure the environment is clean for this test.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PLUS_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_SUBSCRIPTION_PRICE_ID", raising=False)

    client = TestClient(app)
    response = client.get("/payments/health")
    assert response.status_code == 200

    data = response.json()
    assert data["provider"] == "stripe"
    assert data["configured"] is False
    assert data["subscription_configured"] is False


def test_quote_checkout_uses_country_routing_for_nigeria():
    client = TestClient(app)

    response = client.post(
        "/payments/quote",
        json={
            "ui_amount_cents": 1200000,
            "currency": "usd",
            "country_code": "NG",
            "kind": "payment",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "stripe"
    assert data["country_code"] == "NG"
    assert data["currency"] == "ngn"
    assert data["final_amount_cents"] == 1200000


def test_checkout_session_country_routing_overrides_client_currency(monkeypatch):
    from app.routes import payments as payments_module

    created = {}

    class _CheckoutSessionApi:
        @staticmethod
        def create(**kwargs):
            created.update(kwargs)
            line_item = kwargs["line_items"][0]
            price_data = line_item["price_data"]
            return SimpleNamespace(
                id="cs_test_country_route",
                url="https://checkout.stripe.test/cs_test_country_route",
                mode=kwargs.get("mode", "payment"),
                currency=price_data["currency"],
                amount_total=price_data["unit_amount"],
                customer=None,
                subscription=None,
            )

    dummy_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=_CheckoutSessionApi),
    )

    monkeypatch.setenv("STRIPE_SECRET_KEY", "stripe-test-placeholder")
    monkeypatch.setattr(payments_module, "stripe", dummy_stripe)

    client = TestClient(app)
    response = client.post(
        "/payments/checkout-session",
        json={
            "amount_cents": 1200000,
            "currency": "usd",
            "country_code": "NG",
            "country": "Nigeria",
            "description": "ErrandBridge payment",
            "reference_id": "payment-country-route",
            "metadata": {
                "kind": "payment",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "cs_test_country_route"

    line_item = created["line_items"][0]
    assert line_item["price_data"]["currency"] == "ngn"

    metadata = created["metadata"]
    assert metadata["payment_provider"] == "stripe"
    assert metadata["payment_country_code"] == "NG"
    assert metadata["payment_country_label"] == "Nigeria"
    assert metadata["payment_method_family"] == "stripe_cards"
    assert metadata["client_requested_currency"] == "usd"

    payment_intent_metadata = created["payment_intent_data"]["metadata"]
    assert payment_intent_metadata["payment_country_code"] == "NG"
    assert payment_intent_metadata["payment_currency"] == "ngn"
