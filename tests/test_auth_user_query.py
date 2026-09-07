from auth_user_query import auth_safe_user_by_email_query


def test_auth_safe_user_query_omits_non_auth_profile_columns():
    stmt = auth_safe_user_by_email_query("MixedCase@Example.com")
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "lower(users.email) = 'mixedcase@example.com'" in compiled
    assert "users.user_uuid" in compiled
    assert "users.email_otp_hash" in compiled
    assert "users.address_line1" in compiled
    assert "users.profile_image_url" not in compiled
    assert "users.vehicle_make" not in compiled
    assert "users.insurance_provider" not in compiled
