from app.services.risk.clause_splitter import split_clauses


def test_splits_articles_and_special_terms(sample_contract):
    clauses = split_clauses(sample_contract)
    titles = [c.title for c in clauses]
    assert titles[:4] == ["제1조 (목적)", "제2조 (존속기간)", "제3조 (용도변경 및 전대 등)", "제4조 (계약의 해지)"]
    assert titles[4:] == ["특약 1", "특약 2", "특약 3", "특약 4"]
    assert [c.index for c in clauses] == list(range(len(clauses)))
    assert clauses[4].kind == "special"


def test_signature_tail_is_excluded(sample_contract):
    clauses = split_clauses(sample_contract)
    assert all("서명 날인" not in c.content for c in clauses)


def test_circled_numbers_in_special_terms():
    text = "제1조 (목적) 임대차 목적물은 아래와 같다.\n특약사항:\n① 관리비는 임차인이 부담한다.\n② 애완동물 사육을 금지한다."
    clauses = split_clauses(text)
    assert [c.title for c in clauses] == ["제1조 (목적)", "특약 1", "특약 2"]


def test_unstructured_text_falls_back_to_paragraphs():
    text = "임차인은 월세를 매월 말일에 지급한다.\n\n임대인은 보증금을 계약 종료일에 반환한다."
    clauses = split_clauses(text)
    assert len(clauses) == 2
    assert clauses[0].kind == "paragraph"


def test_empty_text():
    assert split_clauses("") == []
    assert split_clauses("   \n ") == []
