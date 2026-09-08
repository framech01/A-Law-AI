# A-LAW AI

대한민국 부동산 임대차 계약서를 OCR로 추출하고, LLM으로 위험 조항·누락 조항·사기 징후를 분석하는 내부 AI 서비스입니다. Spring Boot 애플리케이션과 RabbitMQ, Redis, PostgreSQL, S3를 통해 연동하는 구조를 전제로 합니다.

> 이 프로젝트의 출력은 법률 자문이 아닌 검토 보조 자료입니다. 실제 계약 판단은 원문과 최신 법령을 확인하고 법률 전문가의 검토를 받아야 합니다.

## 주요 기능

- 이미지 직접 업로드 또는 S3 객체 기반 계약서 OCR
- 계약서 요약, 위험 요소, 누락·불공정 조항 분석
- Celery/RabbitMQ 기반 비동기 분석과 Redis 상태 캐시
- PostgreSQL 분석 작업 상태 저장 및 Spring Boot 결과 메시지 발행
- Qdrant 기반 법률 문서 RAG를 위한 API 경계(현재 일부 엔드포인트 미구현)

## 기술 스택

- **API**: Python 3.11, FastAPI, Uvicorn, Pydantic Settings
- **LLM/RAG**: OpenAI API, LangChain, LangGraph, Qdrant Client
- **OCR/Image**: Upstage Document OCR, OpenCV Headless, PyMuPDF, Pillow, NumPy
- **Async jobs**: Celery, RabbitMQ, Kombu, aio-pika
- **Storage**: PostgreSQL/psycopg2, Redis, AWS S3/boto3
- **Quality**: Pytest, pytest-asyncio, Docker, Docker Compose

## 저장소 구조

```text
.
├─ README.md
├─ .gitignore
└─ A-Law-AI-main/
   ├─ app/
   │  ├─ api/endpoints/   # 계약 분석, OCR, 비동기 작업, RAG API
   │  ├─ core/            # 설정, Celery, 공통 보안 검증
   │  ├─ ocr/             # Upstage OCR 및 계약서 후처리
   │  ├─ schemas/         # 요청·응답 도메인 모델
   │  ├─ services/        # 분석, OCR, RabbitMQ 소비자
   │  ├─ util/            # S3 어댑터
   │  └─ worker/          # Celery 분석 워커
   ├─ tests/
   ├─ .env.example
   ├─ Dockerfile
   ├─ docker-compose.dev.yml
   └─ requirements.txt
```

## 로컬 실행

```powershell
cd A-Law-AI-main
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Qdrant 개발 인스턴스는 `docker compose -f docker-compose.dev.yml up -d`로 실행합니다.

- 상태 확인: `GET http://127.0.0.1:8001/health`
- OpenAPI 문서: `http://127.0.0.1:8001/docs`
- `/api/*` 요청에는 `X-Internal-Token` 헤더가 필요합니다.

Celery 워커:

```powershell
celery -A app.core.celery_config worker --loglevel=info --queues=contract.analysis.queue
```

## 보안 기본값

- 모든 업무 API는 내부 토큰으로 보호되며 health endpoint만 공개됩니다.
- CORS는 `CORS_ORIGINS`에 명시된 출처만 허용합니다.
- 콜백 URL은 `CALLBACK_ALLOWED_HOSTS`의 호스트만 허용해 SSRF를 차단합니다.
- 직접 업로드는 `MAX_UPLOAD_BYTES`로 크기를 제한합니다.
- S3 객체 키는 `S3_ALLOWED_PREFIX` 하위만 허용합니다.
- `.env`와 로컬 캐시·로그는 Git에서 제외됩니다.

## 개인정보 및 외부 전송

- 직접 업로드한 계약서 이미지는 OCR 처리를 위해 **Upstage API**로 전송됩니다.
- OCR 텍스트와 계약 내용은 분석을 위해 **OpenAI API**로 전송됩니다.
- 분석 결과와 작업 상태는 설정에 따라 Redis, PostgreSQL, RabbitMQ 및 허용된 callback 서버에 저장·전송됩니다.
- AWS S3를 사용하는 경우 계약서 원본은 설정된 버킷에서 읽거나 저장됩니다.

실제 개인정보를 처리하기 전에 각 공급자의 데이터 처리·보존 정책, 이용자 동의, 국외 이전 고지, 삭제 절차를 확인해야 합니다. 개발·테스트에는 비식별화된 샘플만 사용하세요.

운영에서는 토큰과 클라우드 키를 secret manager에 저장하고 HTTPS, 요청 속도 제한, 감사 로그, 개인정보 보존·삭제 정책을 추가하세요. 계약서 원문이나 OCR 텍스트를 애플리케이션 로그에 남기지 마세요.

## 현재 제한 사항

- `/api/rag/*`는 인터페이스만 정의되어 있고 `501`을 반환합니다.
- 일부 법률 용어 및 사기 탐지는 프로토타입 규칙 기반 구현입니다.
- LLM 응답은 최신 법령과 판례를 보장하지 않으므로 사람의 검토가 필수입니다.
- 공개 배포 전 라이선스 파일과 사용 데이터의 저작권·재배포 조건을 확인해야 합니다.

GitHub 저장소 설명 제안:

> Korean lease-contract OCR and AI risk analysis service built with FastAPI, OpenAI, Upstage OCR, Celery, Redis, PostgreSQL, S3, and Qdrant.
