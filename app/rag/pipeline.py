"""
Dense 법률 RAG 파이프라인

질의 임베딩(KURE-v1)
→ Pinecone namespace 병렬 검색(각 Top-K)
→ 중복 제거 후 상위 후보 선별
→ BGE CrossEncoder 재정렬 (도메인 프리픽스 주입)
→ 조문번호 정확 매칭 가산점 / 주거·상가 도메인 불일치 페널티
→ 최종 Top-N
"""
import asyncio
import hashlib
import re
import threading
from functools import lru_cache
from typing import Iterable

from loguru import logger

from app.core.config import settings
from app.rag.citations import ARTICLE_PATTERN, article_key
from app.rag.domain import Domain, classify_document, classify_query, is_domain_mismatch, rerank_prefix
from app.rag.models import RankedDocument

# 재정렬 점수(0~1) 기준 보정값
ARTICLE_MATCH_BONUS = 0.15
DOMAIN_MISMATCH_PENALTY = 0.2

# KURE-v1(SentenceTransformer)은 동시 호출 시 안전하지 않으므로 직렬화
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()


class RAGNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def reranker_model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.RERANKER_MODEL)


def query_articles(query: str) -> set[str]:
    return {article_key(a, s or None) for a, s in ARTICLE_PATTERN.findall(query or "")}


def apply_score_adjustments(docs: list[RankedDocument], query: str, domain: Domain) -> list[RankedDocument]:
    """조문번호 일치 가산점과 도메인 불일치 페널티 적용 후 재정렬"""
    articles = query_articles(query)
    for doc in docs:
        if articles:
            haystack = re.sub(r"\s+", "", f"{doc.metadata.get('article', '')} {doc.content}")
            if any(a in haystack for a in articles):
                doc.score += ARTICLE_MATCH_BONUS
        if is_domain_mismatch(domain, classify_document(doc.content, doc.metadata)):
            doc.score -= DOMAIN_MISMATCH_PENALTY
    docs.sort(key=lambda d: d.score, reverse=True)
    return docs


class LegalRAG:
    def __init__(self, index=None):
        if index is None:
            if not settings.rag_configured:
                raise RAGNotConfiguredError("PINECONE_API_KEY가 설정되지 않았습니다")
            from pinecone import Pinecone
            index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX)
        self.index = index
        self.namespaces = settings.namespaces

    # ------------------------------------------------------------------
    # Embedding / Rerank
    # ------------------------------------------------------------------
    def _embed(self, texts: list[str]) -> list[list[float]]:
        with _embed_lock:
            return embedding_model().encode(texts, normalize_embeddings=True).tolist()

    def _rerank(self, pairs: list[list[str]]) -> list[float]:
        with _rerank_lock:
            return [float(s) for s in reranker_model().predict(pairs)]

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def index_documents(self, docs: Iterable[tuple[str, dict]], namespace: str) -> int:
        if namespace not in self.namespaces:
            raise ValueError(f"Unsupported namespace: {namespace}")
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n제", "\n\n", "\n", ". ", " "],
        )
        chunks = [(chunk, metadata) for text, metadata in docs for chunk in splitter.split_text(text)]
        for start in range(0, len(chunks), 64):
            batch = chunks[start:start + 64]
            vectors = []
            for (text, metadata), values in zip(batch, self._embed([x[0] for x in batch])):
                vector_id = hashlib.sha256((namespace + text).encode("utf-8")).hexdigest()
                vectors.append({"id": vector_id, "values": values, "metadata": {**metadata, "text": text}})
            self.index.upsert(vectors=vectors, namespace=namespace)
        return len(chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def _search_namespace(self, vector, namespace: str, top_k: int) -> list[RankedDocument]:
        try:
            response = await asyncio.to_thread(
                self.index.query, vector=vector, top_k=top_k, namespace=namespace, include_metadata=True
            )
        except Exception as e:  # 한 namespace 장애가 전체 검색을 막지 않도록
            logger.warning(f"Pinecone query failed (namespace={namespace}): {e}")
            return []
        docs = []
        for m in response.matches:
            metadata = dict(m.metadata or {})
            metadata.setdefault("namespace", namespace)
            docs.append(RankedDocument(metadata.get("text", ""), metadata, float(m.score), m.id))
        return docs

    async def search(
        self,
        query: str,
        final_k: int | None = None,
        namespaces: list[str] | None = None,
        domain: Domain | None = None,
    ) -> list[RankedDocument]:
        targets = [n for n in (namespaces or self.namespaces) if n in self.namespaces]
        if not targets or not query.strip():
            return []
        domain = domain or classify_query(query)

        vector = (await asyncio.to_thread(self._embed, [query]))[0]
        groups = await asyncio.gather(
            *(self._search_namespace(vector, n, settings.RETRIEVAL_K_PER_NAMESPACE) for n in targets)
        )

        unique: dict[str, RankedDocument] = {}
        for group in groups:
            for doc in group:
                if not doc.content:
                    continue
                key = doc.id or doc.content[:100]
                if key not in unique or doc.score > unique[key].score:
                    unique[key] = doc
        # 서로 다른 namespace에 같은 본문이 있는 경우(첫 100자 기준) 중복 제거
        by_prefix: dict[str, RankedDocument] = {}
        for doc in unique.values():
            prefix = doc.content[:100]
            if prefix not in by_prefix or doc.score > by_prefix[prefix].score:
                by_prefix[prefix] = doc

        candidates = sorted(by_prefix.values(), key=lambda d: d.score, reverse=True)[:settings.RERANK_CANDIDATES]
        if candidates and settings.RERANKER_ENABLED:
            rerank_query = rerank_prefix(domain) + query
            try:
                scores = await asyncio.to_thread(self._rerank, [[rerank_query, d.content] for d in candidates])
                for doc, score in zip(candidates, scores):
                    doc.metadata["dense_score"] = doc.score
                    doc.score = score
            except Exception as e:
                logger.warning(f"Rerank failed, falling back to dense scores: {e}")

        candidates = apply_score_adjustments(candidates, query, domain)
        return candidates[:(final_k or settings.FINAL_CONTEXT_K)]

    def stats(self):
        stats = self.index.describe_index_stats()
        return stats.to_dict() if hasattr(stats, "to_dict") else stats


_rag_instance: LegalRAG | None = None
_rag_lock = threading.Lock()


def get_rag() -> LegalRAG:
    """LegalRAG 싱글톤. Pinecone 미설정 시 RAGNotConfiguredError"""
    global _rag_instance
    if _rag_instance is None:
        with _rag_lock:
            if _rag_instance is None:
                _rag_instance = LegalRAG()
    return _rag_instance


def try_get_rag() -> LegalRAG | None:
    """RAG를 사용할 수 없으면 None (분석 기능이 RAG 없이도 동작하도록)"""
    try:
        return get_rag()
    except Exception as e:
        logger.warning(f"RAG unavailable: {e}")
        return None


def format_context(docs: list[RankedDocument], max_chars: int = 6000) -> str:
    """LLM 프롬프트용 근거 컨텍스트 구성"""
    parts, used = [], 0
    for i, doc in enumerate(docs, 1):
        header = f"[근거 {i}]" + (f" {doc.title}" if doc.title else "")
        body = doc.content.strip()
        remaining = max_chars - used - len(header) - 1
        if remaining <= 100:
            break
        if len(body) > remaining:
            body = body[:remaining - 3] + "..."
        parts.append(f"{header}\n{body}")
        used += len(header) + len(body) + 2
    return "\n\n".join(parts)
