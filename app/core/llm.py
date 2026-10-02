"""
LLM 런타임 - 공용 ChatOpenAI 인스턴스와 동시성 제한

조항이 많은 계약서는 LLM을 수십 번 동시에 호출할 수 있으므로
Semaphore로 동시 호출 수를 제한해 Rate Limit과 메모리 급증을 막습니다.
"""
import asyncio
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


class LLMNotConfiguredError(RuntimeError):
    pass


def llm_semaphore() -> asyncio.Semaphore:
    """이벤트 루프별 Semaphore (테스트/워커에서 루프가 바뀌어도 안전)"""
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(max(1, settings.LLM_MAX_CONCURRENCY))
        _semaphore_loop = loop
    return _semaphore


@lru_cache(maxsize=4)
def get_chat_model(temperature: float = 0.0):
    if not settings.llm_configured:
        raise LLMNotConfiguredError("OPENAI_API_KEY가 설정되지 않았습니다")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.MODEL_NAME,
        api_key=settings.OPENAI_API_KEY,
        temperature=temperature,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )


async def ainvoke_text(messages: Any, temperature: float = 0.0) -> str:
    """텍스트 응답 LLM 호출 (동시성 제한 적용)"""
    model = get_chat_model(temperature)
    async with llm_semaphore():
        response = await model.ainvoke(messages)
    return str(response.content)


async def ainvoke_structured(schema: type[T], messages: Any, temperature: float = 0.0) -> T:
    """Pydantic 스키마 구조화 출력 LLM 호출 (동시성 제한 적용)"""
    model = get_chat_model(temperature).with_structured_output(schema)
    async with llm_semaphore():
        result = await model.ainvoke(messages)
    if isinstance(result, dict):
        result = schema.model_validate(result)
    return result
