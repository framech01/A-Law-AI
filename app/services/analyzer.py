"""
계약서 분석 서비스 (요약 + 독소조항 위험 분석 + 용어 해설)
REST API와 RabbitMQ consumer가 공통으로 사용합니다.
"""
import asyncio
import time

from loguru import logger

from app.core.config import settings
from app.core.llm import ainvoke_structured
from app.rag.citations import annotate_unverified_citations
from app.rag.pipeline import format_context, try_get_rag
from app.schemas.contract import AnalysisResult, ContractSummaryResult, TermExplanation
from app.services.risk.analyzer import RiskAnalyzer, RiskReport, build_recommendations
from app.services.summarizer import summarize_contract

TERM_SYSTEM_PROMPT = """당신은 부동산 임대차 법률 용어를 일반인에게 쉽게 설명하는 도우미입니다.
[근거]를 우선 사용하고 근거에 없는 조문 번호는 지어내지 마세요.
- simple_explanation: 중학생도 이해할 수 있는 1~2문장
- legal_definition: 법률적 정의 1~2문장
- examples: 실제 임대차 상황 예시 2~3개
- legal_reference: 관련 법령 (예: 주택임대차보호법 제3조의2). 확실하지 않으면 빈 문자열"""


class ContractAnalysisService:
    def __init__(self, rag=None):
        self.rag = rag if rag is not None else try_get_rag()
        self.risk_analyzer = RiskAnalyzer(self.rag)

    async def analyze_risk(self, text: str) -> RiskReport:
        return await asyncio.wait_for(self.risk_analyzer.analyze(text), timeout=settings.ANALYSIS_TIMEOUT)

    async def analyze_contract(self, text: str, contract_id: str, include_summary: bool = True) -> AnalysisResult:
        """요약과 위험 분석을 병렬로 수행"""
        started = time.perf_counter()
        if include_summary:
            report, summary = await asyncio.gather(self.analyze_risk(text), summarize_contract(text))
        else:
            report, summary = await self.analyze_risk(text), None
        return to_analysis_result(contract_id, report, summary, int((time.perf_counter() - started) * 1000))

    async def explain_term(self, term: str, context: str = "", surrounding_text: str = "") -> TermExplanation:
        docs = []
        if self.rag is not None:
            try:
                docs = await self.rag.search(f"{term} 의미 {context}".strip(), final_k=3,
                                             namespaces=["law_statutes", "law_database"])
            except Exception as e:
                logger.warning(f"Term RAG search failed: {e}")
        prompt = f"[근거]\n{format_context(docs, 3000) or '(검색된 근거 없음)'}\n\n[용어]\n{term}"
        if context:
            prompt += f"\n\n[문맥]\n{context}"
        if surrounding_text:
            prompt += f"\n\n[주변 문장]\n{surrounding_text}"
        result = await ainvoke_structured(TermExplanation, [("system", TERM_SYSTEM_PROMPT), ("human", prompt)])
        result.term = term
        if result.legal_reference:
            result.legal_reference, _ = annotate_unverified_citations(result.legal_reference, docs)
        return result


def to_analysis_result(contract_id: str, report: RiskReport, summary: ContractSummaryResult | None,
                       processing_time_ms: int = 0) -> AnalysisResult:
    return AnalysisResult(
        contract_id=contract_id,
        contract_domain=report.contract_domain,
        total_clauses=len(report.clauses),
        risk_summary=report.counts,
        clauses=report.clauses,
        missing_clauses=report.missing_clauses,
        overall_risk_score=report.overall_risk_score,
        overall_risk_level=report.overall_risk_level,
        summary=summary,
        recommendations=build_recommendations(report),
        processing_time_ms=processing_time_ms,
    )


_service: ContractAnalysisService | None = None


def get_analysis_service() -> ContractAnalysisService:
    global _service
    if _service is None:
        _service = ContractAnalysisService()
    return _service
