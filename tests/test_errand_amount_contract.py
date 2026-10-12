from main import ErrandCreateRequest, ErrandResponse


def test_create_request_accepts_camel_case_minor_amount():
    payload = ErrandCreateRequest.model_validate(
        {
            "title": "Document delivery",
            "paymentAmount": 963,
            "paymentCurrency": "gbp",
        }
    )

    assert payload.payment_amount == 963
    assert payload.payment_currency == "gbp"


def test_errand_response_exposes_both_amount_naming_conventions():
    response = ErrandResponse.model_validate(
        {
            "id": "errand-1",
            "title": "Document delivery",
            "status": "submitted",
            "payment_amount": 963,
            "payment_currency": "GBP",
        }
    )

    assert response.payment_amount == 963
    assert response.paymentAmount == 963
    assert response.payment_currency == "GBP"
    assert response.paymentCurrency == "GBP"
