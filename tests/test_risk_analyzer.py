from app.schemas.contract import ClauseAnalysis, MissingClause
from app.services.risk import analyzer as risk_module
from app.services.risk.analyzer import LLMClauseAssessment, RiskAnalyzer, aggregate_score, build_recommendations


async def test_rule_only_analysis(sample_contract):
    report = await RiskAnalyzer(rag=None, use_llm=False).analyze(sample_contract)
    by_title = {c.title: c for c in report.clauses}
    assert by_title["제4조 (계약의 해지)"].source == "rule"
    assert by_title["특약 1"].risk_level == "Risk"
    assert by_title["특약 2"].risk_score == 90
    assert by_title["특약 4"].risk_level == "Safety"
    assert by_title["특약 3"].source == "skipped"
    assert report.overall_risk_level == "HIGH"
    assert report.counts["Risk"] == 3


async def test_llm_assessment_with_citation_check(monkeypatch, fake_rag):
    async def fake_structured(schema, messages, temperature=0.0):
        assert schema is LLMClauseAssessment
        return LLMClauseAssessment(
            risk_level="Safety", risk_score=45, category="생활 제한",
            reason="반려동물 금지는 일반적인 약정입니다.",
            legal_reference="주택임대차보호법 제6조의3, 민법 제999조",
            recommendation="허용 범위를 협의하세요.",
        )

    monkeypatch.setattr(risk_module, "ainvoke_structured", fake_structured)
    report = await RiskAnalyzer(rag=fake_rag, use_llm=True).analyze("특약사항\n1. 반려동물은 키우지 않는다.")
    clause = report.clauses[0]
    assert clause.source == "llm"
    assert clause.risk_level == "Caution"  # 점수 기준으로 등급 보정
    assert "민법 제999조 (미검증)" in clause.legal_reference
    assert "제6조의3 (미검증)" not in clause.legal_reference
    assert clause.evidence and clause.evidence[0].namespace == "law_statutes"
    assert fake_rag.calls[0]["namespaces"][0] == "special_clauses_illegal"


async def test_llm_failure_marks_clause_for_review(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(risk_module, "ainvoke_structured", boom)
    report = await RiskAnalyzer(rag=None, use_llm=True).analyze("특약사항\n1. 반려동물은 키우지 않는다.")
    assert report.clauses[0].source == "error"
    assert report.clauses[0].risk_level == "Caution"


def test_aggregate_score():
    def clause(score):
        return ClauseAnalysis(title="t", content="c", risk_level="Safety", risk_score=score, analysis="a")

    assert aggregate_score([], []) == 0
    assert aggregate_score([clause(90), clause(10), clause(20)], []) == 0.6 * 90 + 0.4 * 40
    missing = [MissingClause(clause_name="x", importance="critical", description="d")] * 5
    assert aggregate_score([clause(0)], missing) == 15


async def test_recommendations(sample_contract):
    report = await RiskAnalyzer(rag=None, use_llm=False).analyze(sample_contract)
    recs = build_recommendations(report)
    assert recs[0].startswith("[특약 2]")
    assert any("132" in r for r in recs)
