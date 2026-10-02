"""
테스트 공통 설정
- 외부 서비스(OpenAI, Pinecone, RabbitMQ, Redis)를 호출하지 않도록 키를 비웁니다.
"""
import os

os.environ["OPENAI_API_KEY"] = ""
os.environ["PINECONE_API_KEY"] = ""
os.environ["UPSTAGE_API_KEY"] = ""
os.environ["RABBITMQ_ENABLED"] = "false"
os.environ["API_INTERNAL_TOKEN"] = ""
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # 연결 실패 → 메모리 세션 사용

import pytest  # noqa: E402

from app.rag.models import RankedDocument  # noqa: E402

SAMPLE_CONTRACT = """부동산(아파트) 월세 계약서
제1조 (목적) 위 부동산의 임대차에 한하여 임대인과 임차인은 합의에 의하여 보증금 및 차임을 아래와 같이 지불하기로 한다. 보증금 금 일억원정, 차임 금 오십만원정
제2조 (존속기간) 임대인은 2024년 1월 1일까지 임차인에게 인도하며, 임대차 기간은 인도일로부터 2026년 1월 1일까지로 한다.
제3조 (용도변경 및 전대 등) 임차인은 임대인의 동의없이 위 부동산의 용도나 구조를 변경하거나 전대할 수 없다.
제4조 (계약의 해지) 임대인은 언제든지 계약을 해지할 수 있으며 임차인은 즉시 퇴거한다.
특약사항
1. 임차인은 계약갱신요구권을 행사하지 않기로 한다.
2. 보증금은 새로운 임차인이 입주한 후에 반환한다.
3. 반려동물은 키우지 않는다.
4. 본 계약에 정하지 않은 사항은 민법 및 주택임대차보호법에 따른다.
본 계약을 증명하기 위하여 계약 당사자가 이의 없음을 확인하고 각각 서명 날인한다.
"""


@pytest.fixture
def sample_contract() -> str:
    return SAMPLE_CONTRACT


class FakeRAG:
    """LegalRAG 대체 - 고정 문서를 반환"""

    def __init__(self, docs: list[RankedDocument] | None = None):
        self.docs = docs if docs is not None else [
            RankedDocument(
                "주택임대차보호법 제6조의3(계약갱신 요구 등) 임차인이 계약갱신을 요구할 경우 임대인은 정당한 사유 없이 거절하지 못한다.",
                {"law_name": "주택임대차보호법", "article": "제6조의3", "namespace": "law_statutes"},
                0.91,
                "doc-1",
            )
        ]
        self.calls: list[dict] = []

    async def search(self, query, final_k=None, namespaces=None, domain=None):
        self.calls.append({"query": query, "final_k": final_k, "namespaces": namespaces, "domain": domain})
        return list(self.docs)


@pytest.fixture
def fake_rag() -> FakeRAG:
    return FakeRAG()
