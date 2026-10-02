import pytest

from app.rag.domain import Domain
from app.services.risk.prefilter import classify_contract_domain, level_from_score, prefilter_clause


@pytest.mark.parametrize(
    "text, category, score",
    [
        ("임차인은 계약갱신요구권을 행사하지 않기로 한다.", "계약갱신요구권 포기 강요", 88),
        ("보증금은 새로운 임차인이 입주한 후에 반환한다.", "보증금 반환 거부/지연", 90),
        ("임대인은 언제든지 계약을 해지할 수 있다.", "임대인 일방 해지/즉시 퇴거", 85),
        ("임차인은 전입신고를 하지 않는다.", "우선변제권/임차권등기 포기", 85),
        ("차임 연체 시 보증금 전액을 몰수한다.", "보증금 전액 몰수", 87),
        ("모든 수리비용은 임차인이 부담한다.", "수선비 전액 임차인 부담", 62),
        ("자연 마모에 대해서도 임차인이 원상복구한다.", "통상 마모까지 원상복구 의무", 58),
        ("월세는 매년 10% 인상한다.", "차임 증액 상한 초과", 80),
        ("임차인은 어떠한 이의도 제기할 수 없다.", "임차인 권리 포기/이의 금지", 75),
    ],
)
def test_risk_patterns(text, category, score):
    result = prefilter_clause(text)
    assert result is not None
    assert result.category == category
    assert result.risk_score == score
    assert result.legal_reference


@pytest.mark.parametrize(
    "text",
    [
        "보증금은 계약 종료와 동시에 반환한다.",
        "임대인은 임차인의 전입신고 및 확정일자에 협조한다.",
        "본 계약에 정하지 않은 사항은 민법 및 주택임대차보호법에 따른다.",
    ],
)
def test_safe_patterns(text):
    result = prefilter_clause(text)
    assert result is not None
    assert result.risk_level == "Safety"


def test_neutral_clause_goes_to_llm():
    assert prefilter_clause("반려동물은 키우지 않는다.") is None
    assert prefilter_clause("월세는 매년 3% 인상할 수 있다.") is None


def test_commercial_contract_uses_commercial_law():
    result = prefilter_clause("임차인은 계약갱신요구권을 포기한다.", Domain.COMMERCIAL)
    assert "상가건물 임대차보호법" in result.legal_reference


def test_contract_domain():
    assert classify_contract_domain("상가 점포 임대차 계약서 권리금") == Domain.COMMERCIAL
    assert classify_contract_domain("아파트 월세 계약서") == Domain.RESIDENTIAL


def test_level_from_score():
    assert level_from_score(90) == "Risk"
    assert level_from_score(55) == "Caution"
    assert level_from_score(10) == "Safety"
