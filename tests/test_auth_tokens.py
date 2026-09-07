from auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)


def test_refresh_token_is_not_accepted_as_access_token():
    refresh_token = create_refresh_token(user_id=123, expires_days=1)

    assert decode_refresh_token(refresh_token) == 123
    assert decode_access_token(refresh_token) is None


def test_access_token_is_not_accepted_as_refresh_token():
    access_token = create_access_token(user_id=123, expires_minutes=5)

    assert decode_access_token(access_token) == 123
    assert decode_refresh_token(access_token) is None
