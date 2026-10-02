from app.rag.citations import UNVERIFIED_MARK, annotate_unverified_citations, extract_citations
from app.rag.models import RankedDocument

SOURCES = [
    RankedDocument("제6조의3(계약갱신 요구 등) 임대인은 임차인이 계약갱신을 요구할 경우 정당한 사유 없이 거절하지 못한다.",
                   {"law_name": "주택임대차보호법"}),
    RankedDocument("민법 제623조(임대인의 의무) 임대인은 목적물을 임차인에게 인도하고 계약존속 중 그 사용, 수익에 필요한 상태를 유지하게 할 의무를 부담한다."),
]


def test_extract_citations_normalizes_articles():
    cites = extract_citations("주택임대차보호법 제 6 조 의 3 및 민법 제623조를 보세요. 같은법 제3조")
    assert [(c.law, c.article) for c in cites] == [("주택임대차보호법", "제6조의3"), ("민법", "제623조")]


def test_verified_citations_are_not_annotated():
    answer = "주택임대차보호법 제6조의3에 따라 갱신을 요구할 수 있고, 민법 제623조에 따라 수선 의무는 임대인에게 있습니다."
    annotated, cites = annotate_unverified_citations(answer, SOURCES)
    assert annotated == answer
    assert all(c.verified for c in cites)


def test_unverified_citation_is_annotated_once():
    answer = "주택임대차보호법 제6조의4에 따르면 가능합니다."
    annotated, cites = annotate_unverified_citations(answer, SOURCES)
    assert annotated == f"주택임대차보호법 제6조의4 {UNVERIFIED_MARK}에 따르면 가능합니다."
    assert not cites[0].verified
    again, _ = annotate_unverified_citations(annotated, SOURCES)
    assert again.count(UNVERIFIED_MARK) == 1


def test_article_number_must_match_law():
    # 제623조는 민법 문서에만 있으므로 주택임대차보호법 제623조는 미검증
    annotated, cites = annotate_unverified_citations("주택임대차보호법 제623조", SOURCES)
    assert UNVERIFIED_MARK in annotated
