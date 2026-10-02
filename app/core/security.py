"""
내부 API 인증 및 입력 검증 유틸리티
"""
import hmac
from urllib.parse import urlparse

from fastapi import Header, HTTPException, status

from app.core.config import settings


def is_valid_token(provided: str | None, expected: str) -> bool:
    return bool(expected) and bool(provided) and hmac.compare_digest(provided, expected)


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """
    Spring Boot → FastAPI 내부 호출 인증.

    API_INTERNAL_TOKEN이 설정되지 않은 경우(로컬 개발) 검사를 생략합니다.
    운영 환경에서는 반드시 설정하세요.
    """
    expected = settings.API_INTERNAL_TOKEN
    if not expected:
        return
    if not is_valid_token(x_internal_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


def require_admin_token(x_rag_admin_token: str | None = Header(default=None)) -> None:
    """RAG 관리 API 인증 (인덱싱/검색 디버깅용)"""
    if not settings.RAG_ADMIN_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RAG_ADMIN_TOKEN이 설정되지 않았습니다")
    if not is_valid_token(x_rag_admin_token, settings.RAG_ADMIN_TOKEN):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "관리자 토큰이 올바르지 않습니다")


def is_allowed_s3_key(key: str, allowed_prefix: str) -> bool:
    """S3 키가 허용된 prefix 안에 있고 경로 조작이 없는지 확인"""
    if not key or key.startswith("/") or ".." in key.split("/"):
        return False
    return not allowed_prefix or key.startswith(allowed_prefix)


def is_allowed_callback_url(url: str, allowed_hosts: list[str]) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.lower() in {host.lower() for host in allowed_hosts}
        and parsed.username is None
        and parsed.password is None
    )
