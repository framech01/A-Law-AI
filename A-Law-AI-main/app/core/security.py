import hmac
from urllib.parse import urlparse

from fastapi import Header, HTTPException, status


def require_internal_token(x_internal_token: str = Header(default="")) -> None:
    from app.core.config import settings

    expected = settings.API_INTERNAL_TOKEN
    if len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API authentication is not configured",
        )
    if not is_valid_internal_token(x_internal_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )


def is_valid_internal_token(provided: str, expected: str) -> bool:
    return len(expected) >= 32 and hmac.compare_digest(provided, expected)


def is_allowed_callback_url(url: str, allowed_hosts: list[str]) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.lower() in {host.lower() for host in allowed_hosts}
        and parsed.username is None
        and parsed.password is None
    )


def is_allowed_s3_key(key: str, allowed_prefix: str) -> bool:
    return bool(
        allowed_prefix
        and key.startswith(allowed_prefix)
        and ".." not in key.split("/")
        and not key.startswith("/")
    )
