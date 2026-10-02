"""
RAG 법률 챗봇 서비스 - 세션 이력 + LangGraph 파이프라인
"""
from dataclasses import dataclass, field

from app.core.config import settings
from app.rag.graph import build_chat_graph
from app.rag.models import RankedDocument
from app.rag.pipeline import try_get_rag
from app.services.chat_session import ChatSessionStore


@dataclass
class ChatReply:
    answer: str
    domain: str
    sources: list[RankedDocument] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    out_of_scope: bool = False


class ChatbotService:
    def __init__(self, store: ChatSessionStore, rag=None):
        self.store = store
        self.rag = rag if rag is not None else try_get_rag()
        self.graph = build_chat_graph(self.rag)

    async def chat(self, session_id: str, message: str, contract_context: str = "") -> ChatReply:
        history = await self.store.history(session_id, last_n=settings.CHAT_HISTORY_MAX_TURNS * 2)
        state = await self.graph.ainvoke({
            "query": message,
            "history": [{"role": m.role, "content": m.content} for m in history],
            "contract_context": contract_context or "",
        })
        answer = state.get("answer") or "답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."

        await self.store.append(session_id, "user", message)
        await self.store.append(session_id, "assistant", answer)

        citations = [{"law": c.law, "article": c.article, "verified": c.verified} for c in state.get("citations", [])]
        domain = state.get("domain")
        return ChatReply(
            answer=answer,
            domain=getattr(domain, "value", str(domain or "일반")),
            sources=state.get("documents", []),
            citations=citations,
            out_of_scope=bool(state.get("out_of_scope")),
        )
