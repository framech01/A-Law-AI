# A-Law AI

임대차 계약서 OCR, 위험 조항 분석 및 법률 문서 기반 답변을 제공하는 FastAPI 서비스입니다.

## 주요 기능

- Upstage API 기반 계약서 OCR 및 구조화
- GPT 기반 계약서 위험·누락 조항 분석
- KURE-v1 임베딩과 Pinecone을 이용한 법률 문서 검색
- BGE CrossEncoder를 이용한 검색 결과 재정렬
- LangGraph 기반 검색·답변 생성 흐름
- RabbitMQ 기반 비동기 계약서 분석

## RAG 검색 흐름

```text
질문 임베딩(KURE-v1)
→ Pinecone 5개 namespace 병렬 검색(각 Top-10)
→ 중복 제거 및 상위 20개 후보 선별
→ BGE CrossEncoder 재정렬
→ 최종 Top-5를 GPT 컨텍스트로 전달
```

BM25는 사용하지 않습니다.

Pinecone namespace:

- `law_database`
- `law_statutes`
- `contracts`
- `special_clauses_illegal`
- `special_clauses_normal`

## 기술 스택

- Python 3.11, FastAPI, LangChain, LangGraph
- OpenAI API, Upstage OCR
- KURE-v1, BGE Reranker, Pinecone
- RabbitMQ, Redis, PostgreSQL, AWS S3

## 실행 방법

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

필수 환경변수:

```env
OPENAI_API_KEY=
MODEL_NAME=gpt-4o-mini
EMBEDDING_MODEL=nlpai-lab/KURE-v1
UPSTAGE_API_KEY=

PINECONE_API_KEY=
PINECONE_INDEX=a-law
RAG_ADMIN_TOKEN=

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=alaw
```

## RAG API

- `POST /api/rag/index`: 법률 문서 인덱싱
- `POST /api/rag/search`: 검색 및 재정렬
- `POST /api/rag/answer`: LangGraph 기반 답변 생성
- `GET /api/rag/stats`: Pinecone 통계 조회

RAG API 요청에는 `X-RAG-Admin-Token` 헤더가 필요합니다. 전체 컬렉션 삭제 API는 안전을 위해 비활성화되어 있습니다.

> 생성 결과는 법률 자문이 아닌 검토 보조 자료입니다. 실제 판단에는 원문과 최신 법령 확인 및 전문가 검토가 필요합니다.

