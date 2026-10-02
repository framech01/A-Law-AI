from app.rag.domain import Domain, classify_document, classify_query, is_domain_mismatch, rerank_prefix


def test_classify_query():
    assert classify_query("상가 권리금 회수 기회 보호") == Domain.COMMERCIAL
    assert classify_query("전세 보증금 확정일자 받는 법") == Domain.RESIDENTIAL
    assert classify_query("월세 세액공제 받을 수 있나요") == Domain.TAX
    assert classify_query("계약서 작성 시 주의할 점") == Domain.GENERAL


def test_document_domain_and_mismatch():
    doc = classify_document("상가건물 임대차보호법 제10조의4 권리금 회수기회 보호")
    assert doc == Domain.COMMERCIAL
    assert is_domain_mismatch(Domain.RESIDENTIAL, doc)
    assert not is_domain_mismatch(Domain.GENERAL, doc)
    assert rerank_prefix(Domain.RESIDENTIAL) == "주거용: "
