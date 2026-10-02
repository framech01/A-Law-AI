# A-Law AI

임대차 계약서 OCR, 독소조항 위험 탐지, RAG 기반 법률 챗봇을 제공하는 FastAPI 서버입니다.
Spring Boot 메인 서버와 REST(동기) 및 RabbitMQ(비동기)로 연동됩니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| 계약서 OCR | Upstage Document Parse/OCR로 텍스트 + 단어별 좌표(%) 추출, GPT 구조화 |
| 독소조항 위험 탐지 | 조항 분리 → 정규식 선필터 → Pinecone RAG + GPT 조항별 판정 → 위험 점수·등급·근거 법령·권고안 |
| 누락 조항 점검 | 보증금 반환, 임대차 기간, 확정일자, 수선 의무 등 필수 조항 누락 확인 |
| AI 요약 | 계약 유형, 당사자, 핵심 조건, 기간, 주요 일정 요약 (위험 분석과 병렬 실행) |
| RAG 법률 챗봇 | 도메인 분류(주거/상가/세금) → 5개 namespace 검색 → 재정렬 → 답변 → 인용 조문 검증, Redis 세션 |
| 법률 용어 해설 | RAG 근거 기반 쉬운말 설명 |
| 비동기 분석 | RabbitMQ로 분석 요청 수신 → 요약 + 위험 분석 → 결과 발행 (재시도 + DLQ) |

## 아키텍처

```text
Spring Boot ──REST (X-Internal-Token)──▶ /api/contracts/*, /api/chat/*
            ──RabbitMQ contract.analysis.queue──▶ RabbitMQConsumer
                                                   │ contractText (없으면 s3Key OCR)
                                                   ▼
                                     ContractAnalysisService
                                     ├─ summarize_contract (GPT)
                                     └─ RiskAnalyzer
                                        ├─ clause_splitter
                                        ├─ prefilter (정규식, LLM 호출 없음)
                                        └─ LegalRAG + GPT (조항별)
            ◀──RabbitMQ contract.analysis.result / ai.result──
```

```text
app/
├── api/endpoints/      contract.py, chat.py, ocr.py, rag.py
├── core/               config.py, llm.py(동시성 제한), security.py(내부 토큰)
├── rag/                pipeline.py(검색·재정렬), graph.py(LangGraph 챗봇),
│                       domain.py(도메인 분류), citations.py(인용 검증)
├── services/
│   ├── risk/           clause_splitter.py, prefilter.py, missing.py, analyzer.py
│   ├── analyzer.py     요약 + 위험 분석 + 용어 해설
│   ├── chatbot.py      챗봇 서비스
│   ├── chat_session.py Redis 세션 (실패 시 메모리)
│   ├── summarizer.py
│   ├── rabbitmq_consumer.py
│   └── ocr/ocr_service.py
├── ocr/upstage_ocr.py  Upstage 파이프라인
└── schemas/
```

## 독소조항 위험 탐지

1. **조항 분리**: `제N조 (제목)` 조문과 `특약사항` 아래 `1.`, `①`, `-` 항목을 각각 조항으로 분리합니다. 서명·중개사 정보 영역은 제외합니다.
2. **정규식 선필터**: 명확한 패턴은 LLM 없이 즉시 판정합니다. 상가 계약서는 상가건물 임대차보호법 조문으로 근거를 바꿉니다.

   | 위험 패턴 | 점수 |
   |------|------|
   | 보증금 반환 거부/지연 (새 임차인 입주 후 반환 등) | 90 |
   | 계약갱신요구권 포기 강요 | 88 |
   | 보증금 전액 몰수 | 87 |
   | 임대인 일방 해지/즉시 퇴거 | 85 |
   | 우선변제권·전입신고·임차권등기 포기 | 85 |
   | 차임 증액 상한(5%) 초과 | 80 |
   | 임차인 권리 포기/이의 금지 | 75 |
   | 수선비 전액 임차인 부담 | 62 |
   | 통상 마모까지 원상복구 | 58 |

   안전 패턴(보증금 동시 반환 명시, 전입신고·확정일자 협조, 법령 준용)은 Safety로 즉시 처리합니다.
3. **RAG + GPT**: 나머지 조항은 `special_clauses_illegal`, `special_clauses_normal`, `law_statutes`, `law_database`에서 근거를 찾고 GPT 구조화 출력으로 위험 등급·점수·근거·권고안을 생성합니다. 동시 LLM 호출은 `LLM_MAX_CONCURRENCY`로 제한합니다.
4. **인용 검증**: GPT가 제시한 법령 조문이 근거 문서에 없으면 `(미검증)`을 붙입니다.
5. **집계**: 전체 점수 = 0.6 × 최고 조항 점수 + 0.4 × 상위 3개 평균 + 필수 조항 누락 가산(최대 15). 70 이상 HIGH, 40 이상 MEDIUM.

`OPENAI_API_KEY`가 없으면 규칙 기반 탐지만 수행하고, `PINECONE_API_KEY`가 없으면 근거 검색 없이 GPT만 사용합니다.

## RAG 챗봇 흐름

```text
classify (주거/상가/세금/일반, 범위 밖 질문 거절)
→ retrieve: KURE-v1 임베딩 → Pinecone 5개 namespace 병렬 검색(각 Top-10)
            → 중복 제거 → 상위 20개 BGE CrossEncoder 재정렬(도메인 프리픽스)
            → 조문번호 일치 가산 / 주거·상가 불일치 페널티 → Top-5
            (근거가 없으면 이전 대화로 질의를 확장해 1회 재검색)
→ generate: 근거 + 계약서 + 최근 대화 10턴으로 GPT 답변
→ verify: '법령명 제X조' 인용 검증, 면책 문구 추가
```

## API

모든 `/api/*` 요청은 `API_INTERNAL_TOKEN`이 설정된 경우 `X-Internal-Token` 헤더가 필요합니다.

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/contracts/analyze` | 요약 + 위험 탐지 전체 분석 |
| POST | `/api/contracts/detect-risk` | 독소조항 위험 탐지 |
| POST | `/api/contracts/explain/term` | 법률 용어 해설 |
| POST | `/api/contracts/analyze/fraud-detection` | 기존 응답 형식 유지 (하위 호환) |
| POST | `/api/contracts/ocr` | S3 키로 OCR |
| POST | `/api/contracts/ocr/full` | 이미지 직접 업로드 OCR |
| POST | `/api/chat` | RAG 법률 질의응답 |
| GET | `/api/chat/{session_id}/history` | 대화 이력 |
| DELETE | `/api/chat/{session_id}` | 세션 삭제 |
| POST | `/api/rag/index` · `/search` · `/answer`, GET `/api/rag/stats` | RAG 관리 (`X-RAG-Admin-Token`) |
| GET | `/health` | 서버 및 구성 요소 상태 |

```json
POST /api/chat
{ "session_id": "user-123", "message": "계약갱신요구권을 거절할 수 있는 경우는?", "contract_context": "(선택) 계약서 텍스트" }
```

## Spring Boot RabbitMQ 계약

**요청** (Spring → FastAPI, queue `contract.analysis.queue`)

```json
{ "taskId": "uuid", "s3Key": "contracts/123.jpg", "userId": 456, "contractText": "OCR 텍스트 (비어 있으면 s3Key로 OCR)" }
```

**결과** (FastAPI → Spring, exchange `contract.analysis.result`, routing key `ai.result`, queue `ai.result.queue`)

```json
{
  "taskId": "uuid",
  "status": "COMPLETED",
  "summary": { "title": "", "parties": [], "keyTerms": [], "duration": "", "summaryText": "", "importantDates": [] },
  "riskAnalysis": {
    "totalClauses": 8, "riskCount": 3, "cautionCount": 0, "safetyCount": 5, "riskPercentage": 37.5,
    "clauseResults": [
      { "clauseTitle": "특약 1", "clauseContent": "...", "riskLevel": "Risk", "legalReference": "...",
        "recommendation": "...", "reasoningSummary": "...", "riskScore": 88, "category": "계약갱신요구권 포기 강요" }
    ],
    "overallRiskScore": 89.1, "overallRiskLevel": "HIGH",
    "missingClauses": [{ "clauseName": "수선 의무", "importance": "important", "description": "...", "legalBasis": "민법 제623조" }],
    "recommendations": ["..."]
  },
  "processingTimeMs": 18500,
  "completedAt": "2026-10-02T10:30:00"
}
```

- `riskScore`, `category`, `overallRiskScore`, `overallRiskLevel`, `missingClauses`, `recommendations`는 추가 필드입니다. 기존 필드는 그대로 유지됩니다.
- 실패 시 `status: "FAILED"`, `errorMessage`를 발행합니다.
- 일시적 오류는 `x-retry-count` 헤더로 최대 3회 재시도하고, 이후 또는 잘못된 메시지는 `contract.analysis.dlq`로 이동합니다.

## 실행

```bash
cp .env.example .env               # 키 입력
docker compose -f docker-compose.dev.yml up -d   # RabbitMQ + Redis
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
pytest
```

환경변수 전체 목록은 `.env.example`과 `app/core/config.py`를 참고하세요.

> 생성 결과는 법률 자문이 아닌 검토 보조 자료입니다. 실제 판단에는 원문과 최신 법령 확인 및 전문가 검토가 필요합니다.
