"""
RAG 관리 API (X-RAG-Admin-Token 필요)
- 인덱싱, 검색/재정렬 디버깅, 단발 답변, 통계
"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import require_admin_token
from app.rag.graph import build_chat_graph
from app.rag.pipeline import RAGNotConfiguredError, get_rag

router = APIRouter(dependencies=[Depends(require_admin_token)])


def rag_or_503():
    try:
        return get_rag()
    except RAGNotConfiguredError as e:
        raise HTTPException(503, str(e))


class IndexRequest(BaseModel):
    directory: Optional[str] = Field(None, description="LEGAL_DOCS_PATH 하위 디렉토리만 인덱싱")
    document_type: Optional[str] = Field(None, description="대상 namespace (기본: law_database)")
    limit: Optional[int] = Field(None, description="최대 문서 개수 (테스트용)", gt=0, le=10000)


class IndexResponse(BaseModel):
    success: bool
    message: str
    documents_loaded: int
    documents_indexed: int
    collection_info: dict


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="검색 쿼리")
    k: int = Field(5, description="반환할 문서 수", gt=0, le=20)
    namespaces: Optional[List[str]] = Field(None, description="검색할 namespace (기본: 전체)")


class SearchResult(BaseModel):
    content: str
    metadata: dict
    score: float


class SearchResponse(BaseModel):
    query: str
    domain: str
    results: List[SearchResult]
    total_results: int


class AnswerResponse(BaseModel):
    query: str
    answer: str
    sources: List[SearchResult]


@router.post("/index", response_model=IndexResponse, summary="법률 문서 인덱싱")
async def index_documents(request: IndexRequest):
    rag = rag_or_503()
    root = Path(settings.LEGAL_DOCS_PATH).resolve()
    target = (root / request.directory).resolve() if request.directory else root
    if target != root and root not in target.parents:
        raise HTTPException(400, "허용된 법률 문서 경로 밖입니다")
    if not target.exists():
        raise HTTPException(404, "문서 경로가 없습니다")
    namespace = request.document_type or "law_database"
    if namespace not in settings.namespaces:
        raise HTTPException(400, f"지원하지 않는 namespace: {namespace}")

    files = sorted(target.rglob("*.txt"))
    if request.limit:
        files = files[:request.limit]
    docs = [(p.read_text(encoding="utf-8"), {"source": p.name, "document_type": namespace}) for p in files]
    indexed = await run_in_threadpool(rag.index_documents, docs, namespace)
    return IndexResponse(success=True, message="인덱싱 완료", documents_loaded=len(files),
                         documents_indexed=indexed, collection_info={"namespace": namespace})


@router.post("/search", response_model=SearchResponse, summary="법률 문서 검색 + 재정렬")
async def search_documents(request: SearchRequest):
    from app.rag.domain import classify_query

    rag = rag_or_503()
    domain = classify_query(request.query)
    docs = await rag.search(request.query, final_k=request.k, namespaces=request.namespaces, domain=domain)
    results = [SearchResult(content=d.content, metadata=d.metadata, score=d.score) for d in docs]
    return SearchResponse(query=request.query, domain=domain.value, results=results, total_results=len(results))


@router.post("/answer", response_model=AnswerResponse, summary="LangGraph 기반 RAG 단발 답변")
async def answer_question(request: SearchRequest):
    result = await build_chat_graph(rag_or_503()).ainvoke({"query": request.query, "history": []})
    docs = result.get("documents", [])
    sources = [SearchResult(content=d.content, metadata=d.metadata, score=d.score) for d in docs]
    return AnswerResponse(query=request.query, answer=result.get("answer", "관련 근거를 찾지 못했습니다."), sources=sources)


@router.get("/stats", summary="Pinecone 통계 조회")
async def get_stats():
    return await run_in_threadpool(rag_or_503().stats)
