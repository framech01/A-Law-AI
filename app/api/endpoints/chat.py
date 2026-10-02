"""
RAG 법률 챗봇 API
"""
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm import LLMNotConfiguredError
from app.services.chat_session import get_session_store
from app.services.chatbot import ChatbotService

router = APIRouter()

SESSION_ID_PATTERN = r"^[A-Za-z0-9_\-:.]{1,100}$"

_service: ChatbotService | None = None


async def get_chatbot() -> ChatbotService:
    global _service
    if _service is None:
        _service = ChatbotService(await get_session_store())
    return _service


class ChatRequest(BaseModel):
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN, description="세션 ID (예: user-123)")
    message: str = Field(..., min_length=1, max_length=settings.CHAT_MAX_MESSAGE_LENGTH, description="사용자 질문")
    contract_context: Optional[str] = Field(None, description="참고할 계약서 텍스트 (선택)")


class ChatSource(BaseModel):
    title: str
    content: str
    namespace: str
    score: float


class ChatCitation(BaseModel):
    law: str
    article: str
    verified: bool


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    domain: str
    out_of_scope: bool = False
    sources: List[ChatSource] = Field(default_factory=list)
    citations: List[ChatCitation] = Field(default_factory=list)


class ChatHistoryItem(BaseModel):
    role: str
    content: str
    created_at: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatHistoryItem]


@router.post("", response_model=ChatResponse, summary="RAG 기반 법률 질의응답")
async def chat(request: ChatRequest):
    service = await get_chatbot()
    try:
        reply = await service.chat(request.session_id, request.message.strip(), request.contract_context or "")
    except LLMNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"챗봇 응답 실패: {e}")

    sources = [
        ChatSource(title=d.title, content=re.sub(r"\s+", " ", d.content)[:500], namespace=d.namespace,
                   score=round(d.score, 4))
        for d in reply.sources
    ]
    return ChatResponse(
        session_id=request.session_id,
        answer=reply.answer,
        domain=reply.domain,
        out_of_scope=reply.out_of_scope,
        sources=sources,
        citations=[ChatCitation(**c) for c in reply.citations],
    )


@router.get("/{session_id}/history", response_model=ChatHistoryResponse, summary="대화 이력 조회")
async def chat_history(session_id: str = Path(..., pattern=SESSION_ID_PATTERN)):
    store = await get_session_store()
    messages = await store.history(session_id)
    return ChatHistoryResponse(
        session_id=session_id,
        messages=[ChatHistoryItem(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )


@router.delete("/{session_id}", summary="세션 삭제")
async def delete_session(session_id: str = Path(..., pattern=SESSION_ID_PATTERN)):
    store = await get_session_store()
    deleted = await store.delete(session_id)
    return {"session_id": session_id, "deleted": deleted}
