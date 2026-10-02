import json

from app.schemas.contract import AnalysisResult, ClauseAnalysis, ContractSummaryResult
from app.services import rabbitmq_consumer as consumer_module
from app.services.rabbitmq_consumer import RETRY_HEADER, RabbitMQConsumer, build_result_message


def make_analysis() -> AnalysisResult:
    return AnalysisResult(
        contract_id="task-1",
        total_clauses=2,
        risk_summary={"Risk": 1, "Caution": 0, "Safety": 1},
        clauses=[
            ClauseAnalysis(title="특약 1", content="갱신요구권 포기", risk_level="Risk", risk_score=88,
                           category="계약갱신요구권 포기 강요", analysis="무효", legal_reference="주택임대차보호법 제10조",
                           recommendation="삭제", source="rule"),
            ClauseAnalysis(title="제1조", content="목적물", risk_level="Safety", risk_score=0, analysis="일반"),
        ],
        overall_risk_score=88.0,
        overall_risk_level="HIGH",
        summary=ContractSummaryResult(title="월세 계약서", summary_text="요약"),
        recommendations=["[특약 1] 삭제"],
    )


def test_build_result_message_is_camel_case():
    message = build_result_message("task-1", make_analysis(), 1234).to_rabbitmq_message()
    assert message["taskId"] == "task-1"
    assert message["status"] == "COMPLETED"
    assert message["processingTimeMs"] == 1234
    assert message["summary"]["summaryText"] == "요약"
    risk = message["riskAnalysis"]
    assert risk["totalClauses"] == 2 and risk["riskCount"] == 1 and risk["riskPercentage"] == 50.0
    assert risk["clauseResults"][0]["clauseTitle"] == "특약 1"
    assert risk["clauseResults"][0]["riskScore"] == 88
    assert risk["overallRiskLevel"] == "HIGH"
    assert isinstance(message["completedAt"], str)
    json.dumps(message)  # 직렬화 가능


class FakeMessage:
    def __init__(self, body: dict | bytes, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}
        self.content_type = "application/json"
        self.acked = False

    async def ack(self):
        self.acked = True


class FakeExchange:
    def __init__(self):
        self.published = []

    async def publish(self, message, routing_key):
        self.published.append((routing_key, json.loads(message.body) if message.body[:1] == b"{" else message.body,
                               dict(message.headers or {})))


class FakeChannel:
    def __init__(self):
        self.default_exchange = FakeExchange()


class FakeService:
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = []

    async def analyze_contract(self, text, contract_id, include_summary=True):
        self.calls.append(text)
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("openai down")
        return make_analysis()


def make_consumer(service, ocr=None):
    c = RabbitMQConsumer(analysis_service=service, ocr_text_extractor=ocr)
    c.result_exchange = FakeExchange()
    c.channel = FakeChannel()
    return c


async def test_success_publishes_result_and_acks():
    service = FakeService()
    c = make_consumer(service)
    msg = FakeMessage({"taskId": "t1", "s3Key": "contracts/a.png", "userId": 1, "contractText": "제1조 목적"})
    await c.handle_message(msg)
    assert msg.acked
    routing_key, body, _ = c.result_exchange.published[0]
    assert routing_key == "ai.result"
    assert body["status"] == "COMPLETED" and body["taskId"] == "t1"
    assert service.calls == ["제1조 목적"]


async def test_empty_text_uses_ocr():
    async def fake_ocr(s3_key):
        return f"OCR:{s3_key}"

    service = FakeService()
    c = make_consumer(service, ocr=fake_ocr)
    await c.handle_message(FakeMessage({"taskId": "t2", "s3Key": "contracts/b.png", "userId": 1, "contractText": ""}))
    assert service.calls == ["OCR:contracts/b.png"]


async def test_invalid_message_goes_to_dlq():
    c = make_consumer(FakeService())
    msg = FakeMessage(b"not-json")
    await c.handle_message(msg)
    assert msg.acked
    routing_key, _, headers = c.channel.default_exchange.published[0]
    assert routing_key == "contract.analysis.dlq" and "x-error" in headers
    assert c.result_exchange.published[0][1]["status"] == "FAILED"


async def test_transient_failure_is_republished_with_retry_header(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(consumer_module.asyncio, "sleep", no_sleep)
    c = make_consumer(FakeService(fail_times=1))
    msg = FakeMessage({"taskId": "t3", "contractText": "본문"})
    await c.handle_message(msg)
    routing_key, _, headers = c.channel.default_exchange.published[0]
    assert routing_key == "contract.analysis.queue"
    assert headers[RETRY_HEADER] == 1
    assert c.result_exchange.published == []
    assert msg.acked


async def test_retry_exhausted_goes_to_dlq(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(consumer_module.asyncio, "sleep", no_sleep)
    c = make_consumer(FakeService(fail_times=1))
    msg = FakeMessage({"taskId": "t4", "contractText": "본문"}, headers={RETRY_HEADER: 3})
    await c.handle_message(msg)
    assert c.channel.default_exchange.published[0][0] == "contract.analysis.dlq"
    assert c.result_exchange.published[0][1]["status"] == "FAILED"
