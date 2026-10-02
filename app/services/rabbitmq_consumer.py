"""
RabbitMQ Consumer - Spring Boot 비동기 분석 연동 (aio-pika)

Spring Boot  ──(contract.analysis.queue)──▶  FastAPI
  1. 메시지 파싱 (taskId, s3Key, userId, contractText)
  2. contractText가 비어 있으면 S3 이미지 OCR
  3. AI 요약 + 독소조항 위험 분석 병렬 수행 (asyncio.gather)
  4. 결과 발행 ──(contract.analysis.result / ai.result)──▶ Spring Boot

실패 처리
- 일시적 오류: x-retry-count 헤더를 올려 같은 큐로 재발행 (최대 ANALYSIS_MAX_RETRIES회)
- 재시도 초과 또는 재시도 무의미한 오류(JSON/검증 오류): DLQ로 이동 + FAILED 결과 발행
"""
import asyncio
import json
import time
from typing import Optional

import aio_pika
from aio_pika import ExchangeType, Message
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import is_allowed_s3_key
from app.schemas.contract import AnalysisResult
from app.schemas.contract_analysis_dto import (
    AnalysisStatus,
    ClauseRiskResult,
    ContractAnalysisRequest,
    ContractAnalysisResult,
    ContractSummary,
    MissingClauseResult,
    RiskAnalysisResult,
)

RETRY_HEADER = "x-retry-count"
RETRY_BASE_DELAY = 2.0  # 초 (2, 4, 8 ...)


class NonRetryableError(Exception):
    """재시도해도 결과가 같은 오류 (입력 오류 등)"""


def build_result_message(task_id: str, analysis: AnalysisResult, processing_time_ms: int) -> ContractAnalysisResult:
    """AnalysisResult(REST 스키마) → Spring Boot 결과 메시지"""
    counts = analysis.risk_summary
    total = analysis.total_clauses
    risk = RiskAnalysisResult(
        total_clauses=total,
        risk_count=counts.get("Risk", 0),
        caution_count=counts.get("Caution", 0),
        safety_count=counts.get("Safety", 0),
        risk_percentage=round(counts.get("Risk", 0) / total * 100, 1) if total else 0.0,
        clause_results=[
            ClauseRiskResult(
                clause_title=c.title,
                clause_content=c.content,
                risk_level=c.risk_level,
                legal_reference=c.legal_reference or "",
                recommendation=c.recommendation,
                reasoning_summary=c.analysis,
                risk_score=c.risk_score,
                category=c.category,
            )
            for c in analysis.clauses
        ],
        overall_risk_score=analysis.overall_risk_score,
        overall_risk_level=analysis.overall_risk_level,
        missing_clauses=[
            MissingClauseResult(clause_name=m.clause_name, importance=m.importance,
                                description=m.description, legal_basis=m.legal_basis)
            for m in analysis.missing_clauses
        ],
        recommendations=analysis.recommendations,
    )
    summary = None
    if analysis.summary is not None:
        s = analysis.summary
        summary = ContractSummary(title=s.title, parties=s.parties, key_terms=s.key_terms, duration=s.duration,
                                  summary_text=s.summary_text, important_dates=s.important_dates)
    return ContractAnalysisResult(
        task_id=task_id,
        status=AnalysisStatus.COMPLETED,
        summary=summary,
        risk_analysis=risk,
        processing_time_ms=processing_time_ms,
    )


def extract_task_id(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
        return str(data.get("taskId") or data.get("task_id") or "unknown")
    except Exception:
        return "unknown"


class RabbitMQConsumer:
    def __init__(self, analysis_service=None, ocr_text_extractor=None):
        self.connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self.channel: Optional[aio_pika.abc.AbstractChannel] = None
        self.result_exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self.analysis_queue: Optional[aio_pika.abc.AbstractQueue] = None
        self._consumer_tag: Optional[str] = None
        self._analysis_service = analysis_service
        self._ocr_text_extractor = ocr_text_extractor
        self._inflight: set[asyncio.Task] = set()

    @property
    def is_connected(self) -> bool:
        return bool(self.connection and not self.connection.is_closed and self._consumer_tag)

    # ------------------------------------------------------------------
    # 연결
    # ------------------------------------------------------------------
    async def connect(self):
        self.connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=max(1, settings.CONSUMER_PREFETCH))

        self.result_exchange = await self.channel.declare_exchange(
            settings.RESULT_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        result_queue = await self.channel.declare_queue(settings.RESULT_QUEUE, durable=True)
        await result_queue.bind(self.result_exchange, routing_key=settings.RESULT_ROUTING_KEY)
        await self.channel.declare_queue(settings.ANALYSIS_DLQ, durable=True)
        self.analysis_queue = await self.channel.declare_queue(settings.ANALYSIS_QUEUE, durable=True)
        logger.info("RabbitMQ connected")

    async def start(self):
        if self.channel is None:
            await self.connect()
        self._consumer_tag = await self.analysis_queue.consume(self.on_message)
        logger.info(f"[Consumer] consuming from {settings.ANALYSIS_QUEUE}")

    async def stop(self):
        if self.analysis_queue is not None and self._consumer_tag:
            try:
                await self.analysis_queue.cancel(self._consumer_tag)
            except Exception as e:
                logger.warning(f"[Consumer] cancel failed: {e}")
        self._consumer_tag = None
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=30)
        if self.connection is not None:
            await self.connection.close()
            logger.info("[Consumer] disconnected")

    # ------------------------------------------------------------------
    # 메시지 처리
    # ------------------------------------------------------------------
    async def on_message(self, message: aio_pika.abc.AbstractIncomingMessage):
        task = asyncio.current_task()
        if task is not None:
            self._inflight.add(task)
        try:
            await self.handle_message(message)
        finally:
            if task is not None:
                self._inflight.discard(task)

    async def handle_message(self, message):
        task_id = extract_task_id(message.body)
        retries = int((message.headers or {}).get(RETRY_HEADER, 0) or 0)
        logger.info(f"[Consumer] received task_id={task_id} retry={retries}")
        try:
            result = await self.process(message.body)
            await self.publish_result(result)
            await message.ack()
            logger.info(f"[Consumer] completed task_id={task_id} ({result.processing_time_ms}ms)")
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, NonRetryableError) as e:
            logger.error(f"[Consumer] invalid message task_id={task_id}: {e}")
            await self.dead_letter(message, f"invalid message: {e}")
            await self.publish_error(task_id, f"잘못된 요청 메시지: {e}")
            await message.ack()
        except Exception as e:
            if retries < settings.ANALYSIS_MAX_RETRIES:
                logger.warning(f"[Consumer] task_id={task_id} failed, retry {retries + 1}: {e}")
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** retries))
                await self.republish(message, retries + 1)
            else:
                logger.error(f"[Consumer] task_id={task_id} failed after {retries} retries: {e}")
                await self.dead_letter(message, str(e))
                await self.publish_error(task_id, f"분석 실패: {e}")
            await message.ack()

    async def process(self, body: bytes) -> ContractAnalysisResult:
        started = time.perf_counter()
        request = ContractAnalysisRequest.model_validate(json.loads(body.decode("utf-8")))

        text = request.contract_text.strip()
        if not text:
            text = await self._ocr_text(request.s3_key)
        if not text.strip():
            raise RuntimeError("분석할 계약서 텍스트가 없습니다")

        service = self._get_analysis_service()
        analysis = await service.analyze_contract(text, request.task_id, include_summary=True)
        return build_result_message(request.task_id, analysis, int((time.perf_counter() - started) * 1000))

    async def _ocr_text(self, s3_key: str) -> str:
        if not s3_key:
            raise NonRetryableError("contractText가 비어 있고 s3Key도 없습니다")
        if not is_allowed_s3_key(s3_key, settings.S3_ALLOWED_PREFIX):
            raise NonRetryableError(f"허용되지 않은 S3 키: {s3_key}")
        if self._ocr_text_extractor is not None:
            return await self._ocr_text_extractor(s3_key)

        from app.services.ocr.ocr_service import OCRService
        from app.util.s3_client import S3Client

        try:
            image_bytes = await run_in_threadpool(S3Client().get_image, s3_key)
        except FileNotFoundError as e:
            raise NonRetryableError(str(e))
        text = await run_in_threadpool(OCRService().extract_text_only, image_bytes)
        if not (text or "").strip():
            raise RuntimeError("OCR 결과가 비어 있습니다")  # 일시적 OCR 장애일 수 있으므로 재시도 대상
        return text

    def _get_analysis_service(self):
        if self._analysis_service is None:
            from app.services.analyzer import get_analysis_service
            self._analysis_service = get_analysis_service()
        return self._analysis_service

    # ------------------------------------------------------------------
    # 발행
    # ------------------------------------------------------------------
    async def publish_result(self, result: ContractAnalysisResult):
        if self.result_exchange is None:
            raise RuntimeError("Result exchange not initialized")
        message = Message(
            body=json.dumps(result.to_rabbitmq_message(), ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self.result_exchange.publish(message, routing_key=settings.RESULT_ROUTING_KEY)

    async def publish_error(self, task_id: str, error_message: str):
        try:
            await self.publish_result(ContractAnalysisResult(
                task_id=task_id, status=AnalysisStatus.FAILED, error_message=error_message[:1000]
            ))
        except Exception as e:
            logger.error(f"[Consumer] failed to publish error result task_id={task_id}: {e}")

    async def republish(self, message, retry_count: int):
        headers = dict(message.headers or {})
        headers[RETRY_HEADER] = retry_count
        await self.channel.default_exchange.publish(
            Message(body=message.body, headers=headers, content_type=message.content_type or "application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=settings.ANALYSIS_QUEUE,
        )

    async def dead_letter(self, message, reason: str):
        try:
            headers = dict(message.headers or {})
            headers["x-error"] = reason[:500]
            await self.channel.default_exchange.publish(
                Message(body=message.body, headers=headers, content_type=message.content_type or "application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=settings.ANALYSIS_DLQ,
            )
        except Exception as e:
            logger.error(f"[Consumer] failed to dead-letter message: {e}")


# 전역 Consumer 인스턴스
consumer = RabbitMQConsumer()


async def start_consumer():
    """FastAPI lifespan startup에서 호출"""
    await consumer.start()


async def stop_consumer():
    """FastAPI lifespan shutdown에서 호출"""
    await consumer.stop()
