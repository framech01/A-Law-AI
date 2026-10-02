from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app import __version__
from app.api.routers import api_router
from app.core.config import settings
from app.services.rabbitmq_consumer import consumer, start_consumer, stop_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.API_INTERNAL_TOKEN:
        logger.warning("API_INTERNAL_TOKEN is not set - /api endpoints are NOT authenticated (dev mode)")
    if not settings.llm_configured:
        logger.warning("OPENAI_API_KEY is not set - LLM features are disabled (rule-based risk detection only)")
    if not settings.rag_configured:
        logger.warning("PINECONE_API_KEY is not set - RAG retrieval is disabled")

    if settings.RABBITMQ_ENABLED:
        try:
            await start_consumer()
        except Exception as e:
            logger.warning(f"RabbitMQ consumer failed to start: {e} (REST API remains available)")

    yield

    if settings.RABBITMQ_ENABLED:
        await stop_consumer()


app = FastAPI(
    title="A-LAW Contract Analysis AI",
    description="임대차 계약서 OCR · 독소조항 위험 탐지 · RAG 법률 챗봇",
    version=__version__,
    lifespan=lifespan,
)

origins = settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,  # 와일드카드 + credentials 조합은 브라우저가 거부
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["시스템"])
async def health_check():
    """서버 + 의존성 상태"""
    return {
        "status": "healthy",
        "service": "A-LAW FastAPI",
        "version": __version__,
        "components": {
            "rabbitmq": "connected" if consumer.is_connected else ("disabled" if not settings.RABBITMQ_ENABLED else "disconnected"),
            "llm": "configured" if settings.llm_configured else "not_configured",
            "rag": "configured" if settings.rag_configured else "not_configured",
            "ocr": "configured" if settings.UPSTAGE_API_KEY else "not_configured",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
