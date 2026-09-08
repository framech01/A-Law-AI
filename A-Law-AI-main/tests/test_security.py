from app.core.security import (
    is_allowed_callback_url,
    is_allowed_s3_key,
    is_valid_internal_token,
)


def test_internal_token_requires_a_long_exact_match() -> None:
    expected = "a" * 32
    assert is_valid_internal_token(expected, expected)
    assert not is_valid_internal_token("wrong", expected)
    assert not is_valid_internal_token("short", "short")


def test_callback_url_requires_an_allowed_host() -> None:
    assert is_allowed_callback_url("https://api.example.com/callback", ["api.example.com"])
    assert not is_allowed_callback_url("https://attacker.example/callback", ["api.example.com"])


def test_callback_url_rejects_credentials_and_unsafe_schemes() -> None:
    allowed = ["api.example.com"]
    assert not is_allowed_callback_url("file:///etc/passwd", allowed)
    assert not is_allowed_callback_url("https://user:pass@api.example.com/callback", allowed)


def test_s3_key_stays_inside_configured_prefix() -> None:
    assert is_allowed_s3_key("contracts/2026/lease.png", "contracts/")
    assert not is_allowed_s3_key("private/lease.png", "contracts/")
    assert not is_allowed_s3_key("contracts/../private/lease.png", "contracts/")
