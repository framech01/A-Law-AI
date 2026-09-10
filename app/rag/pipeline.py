import asyncio
import hashlib
from functools import lru_cache
from typing import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import settings
from app.rag.models import RankedDocument

@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.EMBEDDING_MODEL)

@lru_cache(maxsize=1)
def reranker_model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.RERANKER_MODEL)

class LegalRAG:
    def __init__(self):
        from pinecone import Pinecone
        if not settings.PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY is required")
        self.index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX)
        self.namespaces = [n.strip() for n in settings.RAG_NAMESPACES.split(",") if n.strip()]

    def _embed(self, texts: list[str]):
        return embedding_model().encode(texts, normalize_embeddings=True).tolist()

    def index_documents(self, docs: Iterable[tuple[str, dict]], namespace: str) -> int:
        if namespace not in self.namespaces:
            raise ValueError(f"Unsupported namespace: {namespace}")
        splitter = RecursiveCharacterTextSplitter(chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP, separators=["\n제", "\n\n", "\n", ". ", " "])
        chunks = [(chunk, metadata) for text, metadata in docs for chunk in splitter.split_text(text)]
        for start in range(0, len(chunks), 64):
            batch = chunks[start:start + 64]
            vectors = []
            for (text, metadata), values in zip(batch, self._embed([x[0] for x in batch])):
                vector_id = hashlib.sha256((namespace + text).encode("utf-8")).hexdigest()
                vectors.append({"id": vector_id, "values": values, "metadata": {**metadata, "text": text}})
            self.index.upsert(vectors=vectors, namespace=namespace)
        return len(chunks)

    async def _search_namespace(self, vector, namespace):
        response = await asyncio.to_thread(self.index.query, vector=vector,
            top_k=settings.RETRIEVAL_K_PER_NAMESPACE, namespace=namespace, include_metadata=True)
        return [RankedDocument(m.metadata.get("text", ""), dict(m.metadata), float(m.score), m.id)
                for m in response.matches]

    async def search(self, query: str, final_k: int | None = None):
        vector = (await asyncio.to_thread(self._embed, [query]))[0]
        groups = await asyncio.gather(*(self._search_namespace(vector, n) for n in self.namespaces))
        unique = {}
        for group in groups:
            for doc in group:
                key = doc.id or doc.content[:100]
                if key not in unique or doc.score > unique[key].score: unique[key] = doc
        candidates = sorted(unique.values(), key=lambda d: d.score, reverse=True)[:settings.RERANK_CANDIDATES]
        if candidates:
            scores = await asyncio.to_thread(reranker_model().predict, [[query, d.content] for d in candidates])
            for doc, score in zip(candidates, scores): doc.score = float(score)
            candidates.sort(key=lambda d: d.score, reverse=True)
        return candidates[:(final_k or settings.FINAL_CONTEXT_K)]

    def stats(self): return self.index.describe_index_stats()

    def delete_all(self):
        for namespace in self.namespaces: self.index.delete(delete_all=True, namespace=namespace)
