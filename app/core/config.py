import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정 - 모든 값은 환경변수 또는 .env 파일에서 로드"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # LLM / Embedding
    # ------------------------------------------------------------------
    OPENAI_API_KEY: str = ""
    MODEL_NAME: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "nlpai-lab/KURE-v1"
    LLM_TIMEOUT: int = 30  # 단일 LLM 호출 타임아웃 (초)
    LLM_MAX_CONCURRENCY: int = 3  # 동시 LLM 호출 상한
    LLM_MAX_RETRIES: int = 2

    # Upstage API (OCR용)
    UPSTAGE_API_KEY: str = ""

    # ------------------------------------------------------------------
    # Pinecone dense RAG
    # ------------------------------------------------------------------
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "a-law"
    RAG_NAMESPACES: str = "law_database,law_statutes,contracts,special_clauses_illegal,special_clauses_normal"
    RETRIEVAL_K_PER_NAMESPACE: int = 10
    RERANK_CANDIDATES: int = 20
    FINAL_CONTEXT_K: int = 5
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_ENABLED: bool = True
    RAG_ADMIN_TOKEN: str = ""

    # 인덱싱 설정
    CHUNK_SIZE: int = 700
    CHUNK_OVERLAP: int = 100
    LEGAL_DOCS_PATH: str = "data"

    # ------------------------------------------------------------------
    # 챗봇
    # ------------------------------------------------------------------
    CHAT_SESSION_TTL: int = 3600  # Redis 세션 TTL (초)
    CHAT_HISTORY_MAX_TURNS: int = 10  # 프롬프트에 포함할 최근 대화 턴 수
    CHAT_MAX_MESSAGE_LENGTH: int = 2000
    CHAT_MAX_CONTRACT_CONTEXT_LENGTH: int = 8000

    # ------------------------------------------------------------------
    # 계약서 위험 분석
    # ------------------------------------------------------------------
    RISK_MAX_CLAUSES: int = 40  # 한 계약서에서 LLM으로 분석할 최대 조항 수
    RISK_RAG_K: int = 3  # 조항당 근거 문서 수
    ANALYSIS_TIMEOUT: int = 120  # 계약서 1건 전체 분석 타임아웃 (초)

    # ------------------------------------------------------------------
    # 내부 API 인증 / 보안
    # ------------------------------------------------------------------
    # 설정 시 모든 /api 요청에 X-Internal-Token 헤더가 필요합니다. (권장: 32자 이상)
    API_INTERNAL_TOKEN: str = ""
    CORS_ORIGINS: str = "*"  # 콤마 구분 또는 JSON 배열
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    S3_ALLOWED_PREFIX: str = ""  # 비어 있으면 prefix 검사 생략

    # ------------------------------------------------------------------
    # RabbitMQ (Spring Boot 연동)
    # ------------------------------------------------------------------
    RABBITMQ_ENABLED: bool = True
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    ANALYSIS_QUEUE: str = "contract.analysis.queue"
    RESULT_EXCHANGE: str = "contract.analysis.result"
    RESULT_QUEUE: str = "ai.result.queue"
    RESULT_ROUTING_KEY: str = "ai.result"
    ANALYSIS_DLQ: str = "contract.analysis.dlq"
    ANALYSIS_MAX_RETRIES: int = 3
    CONSUMER_PREFETCH: int = 2

    # ------------------------------------------------------------------
    # Redis (챗봇 세션)
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # ------------------------------------------------------------------
    # AWS S3 (Spring Boot와 공유)
    # ------------------------------------------------------------------
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-northeast-2"
    AWS_S3_BUCKET: str = "alaw-contracts"

    @property
    def cors_origins(self) -> list[str]:
        """JSON 배열 또는 콤마 구분 문자열 모두 허용"""
        value = self.CORS_ORIGINS.strip()
        if value.startswith("["):
            return [str(v) for v in json.loads(value)]
        return [v.strip() for v in value.split(",") if v.strip()]

    @property
    def namespaces(self) -> list[str]:
        return [n.strip() for n in self.RAG_NAMESPACES.split(",") if n.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def rag_configured(self) -> bool:
        return bool(self.PINECONE_API_KEY)


settings = Settings()
