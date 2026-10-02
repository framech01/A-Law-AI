import pytest
from fastapi.testclient import TestClient

from app.api.endpoints import chat as chat_endpoint
from app.core.config import settings
from app.main import app
from app.services import analyzer as analyzer_module
from app.services.analyzer import ContractAnalysisService
from app.services.chat_session import ChatSessionStore, InMemorySessionBackend, set_session_store
from app.services.chatbot import ChatbotService


@pytest.fixture
def client(monkeypatch, fake_rag):
    monkeypatch.setattr(analyzer_module, "_service", ContractAnalysisService(rag=fake_rag))
    store = ChatSessionStore(InMemorySessionBackend())
    set_session_store(store)
    monkeypatch.setattr(chat_endpoint, "_service", None)
    with TestClient(app) as c:
        yield c
    set_session_store(None)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["components"]["rabbitmq"] == "disabled"


def test_detect_risk_rule_based(client, sample_contract):
    res = client.post("/api/contracts/detect-risk", json={"text": sample_contract, "contract_id": "C1"})
    assert res.status_code == 200
    body = res.json()
    assert body["contract_id"] == "C1"
    assert body["overall_risk_level"] == "HIGH"
    assert body["risk_summary"]["Risk"] == 3


def test_fraud_detection_compat(client, sample_contract):
    res = client.post("/api/contracts/analyze/fraud-detection", json={"text": sample_contract, "contract_id": "C1"})
    assert res.status_code == 200
    body = res.json()
    assert body["risk_score"] > 0 and body["fraud_risks"]


def test_internal_token(client, monkeypatch, sample_contract):
    monkeypatch.setattr(settings, "API_INTERNAL_TOKEN", "x" * 32)
    payload = {"text": sample_contract, "contract_id": "C1"}
    assert client.post("/api/contracts/detect-risk", json=payload).status_code == 401
    ok = client.post("/api/contracts/detect-risk", json=payload, headers={"X-Internal-Token": "x" * 32})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200  # 헬스체크는 인증 없음


def test_chat_flow(client, monkeypatch, fake_rag):
    from app.rag import graph as graph_module

    async def fake_llm(messages, temperature=0.0):
        return "갱신요구권은 주택임대차보호법 제6조의3에 규정되어 있습니다."

    monkeypatch.setattr(graph_module, "ainvoke_text", fake_llm)

    async def service_factory():
        from app.services.chat_session import get_session_store
        return ChatbotService(await get_session_store(), rag=fake_rag)

    monkeypatch.setattr(chat_endpoint, "get_chatbot", service_factory)

    res = client.post("/api/chat", json={"session_id": "user-1", "message": "전세 계약 갱신 요구할 수 있나요?"})
    assert res.status_code == 200
    body = res.json()
    assert "(미검증)" not in body["answer"]
    assert body["citations"] == [{"law": "주택임대차보호법", "article": "제6조의3", "verified": True}]
    assert body["domain"] == "주거"

    history = client.get("/api/chat/user-1/history").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]

    out = client.post("/api/chat", json={"session_id": "user-2", "message": "오늘 저녁 메뉴 추천해줘"}).json()
    assert out["out_of_scope"] is True

    assert client.delete("/api/chat/user-1").json()["deleted"] is True


def test_chat_rejects_bad_session_id(client):
    res = client.post("/api/chat", json={"session_id": "bad id!", "message": "전세"})
    assert res.status_code == 422
