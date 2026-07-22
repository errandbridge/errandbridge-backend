from app.routes import analytics


def test_normalize_country_accepts_iso2_and_aliases():
    assert analytics._normalize_country("gb") == "GB"
    assert analytics._normalize_country(" GB ") == "GB"
    assert analytics._normalize_country("UK") == "GB"
    assert analytics._normalize_country("uae") == "AE"
    assert analytics._normalize_country("USA") == "US"
    assert analytics._normalize_country("Nigeria") == "NG"
    assert analytics._normalize_country("United Kingdom") == "GB"


def test_normalize_country_rejects_unknown_and_non_iso2():
    assert analytics._normalize_country(None) is None
    assert analytics._normalize_country("") is None
    assert analytics._normalize_country(" ") is None
    assert analytics._normalize_country("XX") is None
    assert analytics._normalize_country("unknown") is None
    assert analytics._normalize_country("N/A") is None
    assert analytics._normalize_country("123") is None
