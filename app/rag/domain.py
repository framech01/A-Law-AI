"""
규칙 기반 질의 도메인 분류 (LLM 호출 없음)

주거/상가 임대차는 적용 법령과 세부 조항이 달라 검색 결과가 섞이면 오답으로 이어집니다.
질의 도메인을 먼저 분류해 재정렬 단계에서 도메인 프리픽스와 불일치 페널티에 사용합니다.
"""
from enum import Enum


class Domain(str, Enum):
    RESIDENTIAL = "주거"
    COMMERCIAL = "상가"
    TAX = "세금"
    GENERAL = "일반"


COMMERCIAL_KEYWORDS = (
    "상가", "점포", "권리금", "영업", "상가건물", "사업자", "환산보증금", "임대차보호법 시행령 제2조",
    "가게", "매장", "사무실", "식당", "카페",
)
TAX_KEYWORDS = (
    "세금", "세액", "양도세", "양도소득세", "취득세", "재산세", "종부세", "종합부동산세",
    "부가가치세", "부가세", "소득공제", "세액공제", "임대소득", "과세", "비과세", "연말정산",
)
RESIDENTIAL_KEYWORDS = (
    "주택", "아파트", "빌라", "원룸", "투룸", "오피스텔", "다가구", "다세대", "전세", "반전세",
    "전입", "전입신고", "확정일자", "주택임대차", "전세사기", "깡통전세", "집주인", "거주",
)

# 문서 쪽 도메인 판별용 (법령명 기반)
COMMERCIAL_DOC_MARKERS = ("상가건물 임대차보호법", "상가건물임대차보호법", "상가임대차", "권리금")
RESIDENTIAL_DOC_MARKERS = ("주택임대차보호법", "주택 임대차", "주거용")


def _count(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for k in keywords if k in text)


def classify_query(query: str) -> Domain:
    text = query or ""
    scores = {
        Domain.COMMERCIAL: _count(text, COMMERCIAL_KEYWORDS),
        Domain.TAX: _count(text, TAX_KEYWORDS),
        Domain.RESIDENTIAL: _count(text, RESIDENTIAL_KEYWORDS),
    }
    best = max(scores, key=lambda d: scores[d])
    if scores[best] == 0:
        return Domain.GENERAL
    # 주거 vs 상가 동점이면 명시적 법령명이 우선
    if scores[Domain.COMMERCIAL] == scores[Domain.RESIDENTIAL] and best in (Domain.COMMERCIAL, Domain.RESIDENTIAL):
        if "상가" in text:
            return Domain.COMMERCIAL
        return Domain.RESIDENTIAL
    return best


def classify_document(content: str, metadata: dict | None = None) -> Domain:
    """검색된 문서의 도메인 추정 (본문 + 법령명 메타데이터)"""
    metadata = metadata or {}
    haystack = " ".join(
        [content or ""] + [str(metadata.get(k, "")) for k in ("law_name", "law_type", "title", "category", "source")]
    )
    if any(m in haystack for m in COMMERCIAL_DOC_MARKERS):
        return Domain.COMMERCIAL
    if any(m in haystack for m in RESIDENTIAL_DOC_MARKERS):
        return Domain.RESIDENTIAL
    return Domain.GENERAL


def rerank_prefix(domain: Domain) -> str:
    if domain == Domain.RESIDENTIAL:
        return "주거용: "
    if domain == Domain.COMMERCIAL:
        return "상가용: "
    return ""


def is_domain_mismatch(query_domain: Domain, doc_domain: Domain) -> bool:
    pair = {query_domain, doc_domain}
    return pair == {Domain.RESIDENTIAL, Domain.COMMERCIAL}
