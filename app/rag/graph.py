"""
LangGraph 기반 법률 챗봇 흐름

classify ─┬─(범위 밖)──────────────────────────────→ reject → END
          └─→ retrieve ─┬─(근거 없음 & 재시도 가능)→ retrieve(확장 질의)
                        └─→ generate → verify(인용 검증) → END
"""
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from loguru import logger

from app.core.config import settings
from app.core.llm import ainvoke_text
from app.rag.citations import annotate_unverified_citations
from app.rag.domain import Domain, classify_query
from app.rag.pipeline import LegalRAG, format_context

MAX_RETRIEVAL_ATTEMPTS = 2

DISCLAIMER = "※ 본 답변은 법률 자문이 아닌 일반적인 정보 제공이며, 구체적인 사안은 변호사 등 전문가와 상담하세요."

OUT_OF_SCOPE_ANSWER = (
    "A-Law 챗봇은 부동산 임대차(전세·월세·상가 임대차)와 관련된 법률 질문에 답변합니다. "
    "임대차 계약, 보증금, 계약 갱신, 특약 조항 등에 대해 질문해 주세요."
)

SCOPE_KEYWORDS = (
    "임대", "임차", "전세", "월세", "반전세", "보증금", "차임", "계약", "갱신", "해지", "해제", "집주인", "세입자",
    "임대인", "임차인", "부동산", "주택", "아파트", "빌라", "원룸", "오피스텔", "상가", "권리금", "등기", "확정일자",
    "전입", "대항력", "우선변제", "경매", "공인중개", "중개", "특약", "조항", "원상복구", "수선", "수리", "관리비",
    "법", "판례", "소송", "내용증명", "지급명령", "임차권", "근저당", "깡통", "사기", "이사", "퇴거", "명도", "세금",
)

SYSTEM_PROMPT = """당신은 한국 부동산 임대차 법률 정보를 안내하는 A-Law AI 상담사입니다.

규칙:
1. 제공된 [근거]와 [계약서 내용]을 우선 사용해 한국어로 정확하고 이해하기 쉽게 답하세요.
2. 법령을 인용할 때는 '법령명 제X조' 형식으로 쓰고, 근거에 없는 조문 번호는 지어내지 마세요.
3. 근거가 부족하면 확실하지 않은 부분을 분명히 밝히고 확인 방법(관할 주민센터, 대한법률구조공단 132 등)을 안내하세요.
4. 주거용(주택임대차보호법)과 상가용(상가건물 임대차보호법)을 혼동하지 마세요. 질문 도메인: {domain}
5. 결론 → 근거 → 실천 방법 순서로 간결하게 답하세요."""


class ChatState(TypedDict, total=False):
    query: str
    history: list[dict[str, str]]
    contract_context: str
    domain: Domain
    out_of_scope: bool
    search_query: str
    documents: list
    attempts: int
    answer: str
    citations: list


def is_out_of_scope(query: str, has_history: bool, has_contract: bool) -> bool:
    if has_history or has_contract:
        return False  # 후속 질문("그럼 그건요?")은 맥락상 범위 안으로 간주
    return not any(k in (query or "") for k in SCOPE_KEYWORDS)


def _history_text(history: list[dict[str, str]]) -> str:
    lines = []
    for m in history[-settings.CHAT_HISTORY_MAX_TURNS * 2:]:
        speaker = "사용자" if m.get("role") == "user" else "상담사"
        lines.append(f"{speaker}: {m.get('content', '')}")
    return "\n".join(lines)


def build_chat_graph(rag: LegalRAG | None):
    async def classify(state: ChatState) -> dict[str, Any]:
        query = state["query"]
        return {
            "domain": classify_query(query),
            "out_of_scope": is_out_of_scope(query, bool(state.get("history")), bool(state.get("contract_context"))),
            "search_query": query,
            "attempts": 0,
            "documents": [],
        }

    async def retrieve(state: ChatState) -> dict[str, Any]:
        attempts = state.get("attempts", 0) + 1
        search_query = state.get("search_query") or state["query"]
        if attempts > 1:
            # 재시도: 직전 사용자 발화 + 계약서 일부를 붙여 질의를 확장
            prev = [m["content"] for m in state.get("history", []) if m.get("role") == "user"][-1:]
            extra = (state.get("contract_context") or "")[:300]
            search_query = " ".join(prev + [state["query"], extra]).strip()
        documents = []
        if rag is not None:
            try:
                documents = await rag.search(search_query, domain=state.get("domain"))
            except Exception as e:
                logger.warning(f"RAG search failed: {e}")
        return {"documents": documents, "attempts": attempts, "search_query": search_query}

    def route_after_classify(state: ChatState) -> str:
        return "reject" if state.get("out_of_scope") else "retrieve"

    def route_after_retrieve(state: ChatState) -> str:
        if state.get("documents") or rag is None or state.get("attempts", 0) >= MAX_RETRIEVAL_ATTEMPTS:
            return "generate"
        return "retry"

    async def generate(state: ChatState) -> dict[str, Any]:
        domain = state.get("domain", Domain.GENERAL)
        context = format_context(state.get("documents", [])) or "(검색된 근거 없음)"
        contract = (state.get("contract_context") or "")[:settings.CHAT_MAX_CONTRACT_CONTEXT_LENGTH]
        history = _history_text(state.get("history", []))

        user_prompt = f"[근거]\n{context}\n\n"
        if contract:
            user_prompt += f"[계약서 내용]\n{contract}\n\n"
        if history:
            user_prompt += f"[이전 대화]\n{history}\n\n"
        user_prompt += f"[질문]\n{state['query']}"

        answer = await ainvoke_text([
            ("system", SYSTEM_PROMPT.format(domain=domain.value)),
            ("human", user_prompt),
        ])
        return {"answer": answer}

    async def verify(state: ChatState) -> dict[str, Any]:
        answer, citations = annotate_unverified_citations(state.get("answer", ""), state.get("documents", []))
        if DISCLAIMER not in answer:
            answer = f"{answer.rstrip()}\n\n{DISCLAIMER}"
        return {"answer": answer, "citations": citations}

    async def reject(state: ChatState) -> dict[str, Any]:
        return {"answer": OUT_OF_SCOPE_ANSWER, "documents": [], "citations": []}

    graph = StateGraph(ChatState)
    graph.add_node("classify", classify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)
    graph.add_node("reject", reject)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route_after_classify, {"reject": "reject", "retrieve": "retrieve"})
    graph.add_conditional_edges("retrieve", route_after_retrieve, {"retry": "retrieve", "generate": "generate"})
    graph.add_edge("generate", "verify")
    graph.add_edge("verify", END)
    graph.add_edge("reject", END)
    return graph.compile()


def build_retrieval_graph(rag: LegalRAG | None):
    """하위 호환: /api/rag/answer 에서 사용"""
    return build_chat_graph(rag)
