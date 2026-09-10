"""
RAG 관리 API 엔드포인트
- app/rag/ 모듈 기반으로 재구현 예정
"""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Optional
from functools import lru_cache
from pathlib import Path
import secrets

from app.core.config import settings
from app.rag.pipeline import LegalRAG
from app.rag.graph import build_retrieval_graph

router = APIRouter()

@lru_cache(maxsize=1)
def get_rag() -> LegalRAG:
    return LegalRAG()

def require_admin(token: str | None):
    if not settings.RAG_ADMIN_TOKEN:
        raise HTTPException(503, "RAG_ADMIN_TOKEN이 설정되지 않았습니다")
    if not token or not secrets.compare_digest(token, settings.RAG_ADMIN_TOKEN):
        raise HTTPException(401, "관리자 토큰이 올바르지 않습니다")


# ============================================
# Request/Response 스키마
# ============================================

class IndexRequest(BaseModel):
    directory: Optional[str] = Field(None, description="특정 디렉토리만 인덱싱")
    document_type: Optional[str] = Field(None, description="특정 문서 타입만 인덱싱")
    limit: Optional[int] = Field(None, description="최대 문서 개수 (테스트용)", gt=0, le=10000)
    force_recreate: bool = Field(False, description="기존 컬렉션 삭제 후 재생성")


class IndexResponse(BaseModel):
    success: bool
    message: str
    documents_loaded: int
    documents_indexed: int
    collection_info: dict


class SearchRequest(BaseModel):
    query: str = Field(..., description="검색 쿼리")
    k: int = Field(4, description="반환할 문서 수", gt=0, le=20)
    document_type: Optional[str] = Field(None, description="문서 타입 필터")


class SearchResult(BaseModel):
    content: str
    metadata: dict
    score: float


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int

class AnswerResponse(BaseModel):
    query: str
    answer: str
    sources: List[SearchResult]


class StatsResponse(BaseModel):
    collection_name: str
    total_documents: int
    total_vectors: int
    document_types: dict
    status: str


# ============================================
# API 엔드포인트
# ============================================

@router.post("/index", response_model=IndexResponse, summary="법률 문서 인덱싱")
async def index_documents(request: IndexRequest, x_rag_admin_token: str | None = Header(None)):
    """
    **[미구현]** app/rag/ 모듈 기반으로 재구현 예정.
    현재 노트북(rag.ipynb)에서 인덱싱 테스트 가능합니다.
    """
    require_admin(x_rag_admin_token)
    if request.force_recreate:
        raise HTTPException(400, "안전을 위해 force_recreate는 지원하지 않습니다")
    root = Path(settings.LEGAL_DOCS_PATH).resolve()
    target = (root / request.directory).resolve() if request.directory else root
    if target != root and root not in target.parents:
        raise HTTPException(400, "허용된 법률 문서 경로 밖입니다")
    if not target.exists():
        raise HTTPException(404, "문서 경로가 없습니다")
    files = list(target.rglob("*.txt"))
    if request.limit: files = files[:request.limit]
    namespace = request.document_type or "law_database"
    docs = [(p.read_text(encoding="utf-8"), {"source": p.name, "document_type": namespace}) for p in files]
    indexed = get_rag().index_documents(docs, namespace)
    return IndexResponse(success=True, message="인덱싱 완료", documents_loaded=len(files),
                         documents_indexed=indexed, collection_info={"namespace": namespace})


@router.post("/search", response_model=SearchResponse, summary="법률 문서 검색")
async def search_documents(request: SearchRequest, x_rag_admin_token: str | None = Header(None)):
    """
    **[미구현]** app/rag/retriever/multi_retriever.py 기반으로 재구현 예정.
    """
    require_admin(x_rag_admin_token)
    docs = await get_rag().search(request.query, final_k=request.k)
    results = [SearchResult(content=d.content, metadata=d.metadata, score=d.score) for d in docs]
    return SearchResponse(query=request.query, results=results, total_results=len(results))

@router.post("/answer", response_model=AnswerResponse, summary="LangGraph 기반 RAG 답변")
async def answer_question(request: SearchRequest, x_rag_admin_token: str | None = Header(None)):
    require_admin(x_rag_admin_token)
    result = await build_retrieval_graph(get_rag()).ainvoke({"query": request.query, "attempts": 0})
    docs = result.get("documents", [])
    sources = [SearchResult(content=d.content, metadata=d.metadata, score=d.score) for d in docs]
    return AnswerResponse(query=request.query, answer=result.get("answer", "관련 근거를 찾지 못했습니다."), sources=sources)


@router.get("/stats", summary="RAG 통계 조회")
async def get_stats(x_rag_admin_token: str | None = Header(None)):
    """**[미구현]** 인덱싱된 문서 통계를 반환합니다."""
    require_admin(x_rag_admin_token)
    return get_rag().stats()


@router.delete("/collection", summary="전체 컬렉션 삭제 비활성화")
async def delete_collection():
    """**[미구현]** 모든 인덱싱된 문서가 삭제됩니다."""
    raise HTTPException(status_code=403, detail="API를 통한 전체 삭제는 비활성화되어 있습니다")
