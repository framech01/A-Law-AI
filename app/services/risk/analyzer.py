"""
조항별 독소조항 위험 분석

1. 조항 분리
2. 정규식 선필터 → 명확한 위험/안전 조항은 즉시 판정
3. 나머지 조항: Pinecone(독소조항 사례·정상 조항·법령) 검색 + GPT 구조화 판정
4. 근거 법령 인용 검증 → 근거 문서에 없는 조문은 '(미검증)' 표시
5. 조항 점수 집계 → 전체 위험 점수/등급, 누락 조항
"""
import asyncio
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm import ainvoke_structured
from app.rag.citations import annotate_unverified_citations
from app.rag.domain import Domain
from app.rag.models import RankedDocument
from app.rag.pipeline import LegalRAG, format_context
from app.schemas.contract import ClauseAnalysis, Evidence, MissingClause
from app.services.risk.clause_splitter import Clause, split_clauses
from app.services.risk.missing import find_missing_clauses
from app.services.risk.prefilter import classify_contract_domain, level_from_score, prefilter_clause

RISK_NAMESPACES = ["special_clauses_illegal", "special_clauses_normal", "law_statutes", "law_database"]

SYSTEM_PROMPT = """당신은 한국 부동산 임대차 계약서의 독소조항을 판별하는 법률 분석가입니다.
임차인 입장에서 조항 하나의 위험도를 평가하세요.

평가 기준
- Risk(70~100): 강행규정 위반으로 무효이거나 임차인에게 중대한 재산상 손해를 줄 수 있는 조항
- Caution(40~69): 일방적으로 불리하거나 해석에 따라 분쟁 소지가 있어 수정이 권장되는 조항
- Safety(0~39): 표준적이거나 임차인에게 불리하지 않은 조항, 단순 사실 기재(목적물·당사자·금액 등)

규칙
- [근거]에 있는 법령·사례를 우선 활용하고, 근거에 없는 조문 번호는 지어내지 마세요. 확실하지 않으면 legal_reference를 비워 두세요.
- 계약 유형: {domain} 임대차 ({law})
- reason은 2~3문장, recommendation은 임차인이 요구할 수 있는 구체적인 수정 문구로 작성하세요."""


class LLMClauseAssessment(BaseModel):
    risk_level: Literal["Risk", "Caution", "Safety"] = Field(..., description="위험 등급")
    risk_score: int = Field(..., ge=0, le=100, description="위험 점수 0-100")
    category: str = Field("", description="위험 유형 (예: 보증금 반환, 원상복구, 위약금). 위험 없으면 빈 문자열")
    reason: str = Field(..., description="판단 근거 설명")
    legal_reference: str = Field("", description="관련 법령 (예: 주택임대차보호법 제10조). 없으면 빈 문자열")
    recommendation: str = Field("", description="수정 권고안. 위험 없으면 빈 문자열")


class RiskReport(BaseModel):
    contract_domain: str
    clauses: list[ClauseAnalysis]
    missing_clauses: list[MissingClause]
    overall_risk_score: float
    overall_risk_level: Literal["HIGH", "MEDIUM", "LOW"]

    @property
    def counts(self) -> dict[str, int]:
        counts = {"Risk": 0, "Caution": 0, "Safety": 0}
        for c in self.clauses:
            counts[c.risk_level] += 1
        return counts


def overall_level(score: float) -> Literal["HIGH", "MEDIUM", "LOW"]:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def aggregate_score(clauses: list[ClauseAnalysis], missing: list[MissingClause]) -> float:
    """
    전체 위험 점수 = 0.6 × 최고 조항 점수 + 0.4 × 상위 3개 평균 + 필수 조항 누락 가산(최대 15)
    가장 위험한 조항 하나가 전체 위험을 좌우하되, 위험 조항이 여러 개면 더 높아지도록 설계
    """
    scores = sorted((c.risk_score for c in clauses if c.source != "skipped"), reverse=True)
    base = 0.0
    if scores:
        top3 = scores[:3]
        base = 0.6 * scores[0] + 0.4 * (sum(top3) / len(top3))
    penalty = min(15, sum(5 for m in missing if m.importance == "critical"))
    return round(min(100.0, base + penalty), 1)


def _to_evidence(docs: list[RankedDocument]) -> list[Evidence]:
    return [Evidence(title=d.title, content=d.content[:300], namespace=d.namespace, score=round(d.score, 4))
            for d in docs]


class RiskAnalyzer:
    def __init__(self, rag: LegalRAG | None = None, use_llm: bool | None = None):
        self.rag = rag
        self.use_llm = settings.llm_configured if use_llm is None else use_llm

    async def analyze(self, text: str) -> RiskReport:
        domain = classify_contract_domain(text)
        clauses = split_clauses(text)

        llm_budget = settings.RISK_MAX_CLAUSES
        tasks = []
        for clause in clauses:
            pre = prefilter_clause(clause.text, domain)
            if pre is not None:
                tasks.append(self._from_prefilter(clause, pre))
            elif llm_budget > 0:
                llm_budget -= 1
                tasks.append(self._assess_with_llm(clause, domain))
            else:
                tasks.append(self._skipped(clause, "조항 수 상한을 초과해 상세 분석을 생략했습니다."))

        results = list(await asyncio.gather(*tasks)) if tasks else []
        missing = find_missing_clauses(text, domain)
        score = aggregate_score(results, missing)
        return RiskReport(
            contract_domain=domain.value,
            clauses=results,
            missing_clauses=missing,
            overall_risk_score=score,
            overall_risk_level=overall_level(score),
        )

    # ------------------------------------------------------------------
    async def _from_prefilter(self, clause: Clause, pre) -> ClauseAnalysis:
        return ClauseAnalysis(
            clause_index=clause.index, title=clause.title, content=clause.content,
            risk_level=pre.risk_level, risk_score=pre.risk_score, category=pre.category,
            analysis=pre.reason, legal_reference=pre.legal_reference or None,
            recommendation=pre.recommendation, source="rule",
        )

    async def _skipped(self, clause: Clause, reason: str) -> ClauseAnalysis:
        return ClauseAnalysis(
            clause_index=clause.index, title=clause.title, content=clause.content,
            risk_level="Safety", risk_score=0, analysis=reason, source="skipped",
        )

    async def _retrieve(self, clause: Clause, domain: Domain) -> list[RankedDocument]:
        if self.rag is None:
            return []
        try:
            return await self.rag.search(clause.text[:500], final_k=settings.RISK_RAG_K,
                                         namespaces=RISK_NAMESPACES, domain=domain)
        except Exception as e:
            logger.warning(f"Risk RAG search failed (clause={clause.index}): {e}")
            return []

    async def _assess_with_llm(self, clause: Clause, domain: Domain) -> ClauseAnalysis:
        if not self.use_llm:
            return await self._skipped(clause, "AI 분석이 비활성화되어 규칙 기반 탐지만 수행했습니다.")

        docs = await self._retrieve(clause, domain)
        law = "상가건물 임대차보호법" if domain == Domain.COMMERCIAL else "주택임대차보호법"
        context = format_context(docs, max_chars=2500) or "(검색된 근거 없음)"
        try:
            result = await ainvoke_structured(LLMClauseAssessment, [
                ("system", SYSTEM_PROMPT.format(domain=domain.value, law=law)),
                ("human", f"[근거]\n{context}\n\n[조항]\n{clause.title}\n{clause.content}"),
            ])
        except Exception as e:
            logger.error(f"LLM clause assessment failed (clause={clause.index}): {e}")
            return ClauseAnalysis(
                clause_index=clause.index, title=clause.title, content=clause.content,
                risk_level="Caution", risk_score=40, analysis="자동 분석에 실패했습니다. 이 조항은 직접 확인이 필요합니다.",
                source="error", evidence=_to_evidence(docs),
            )

        legal_reference = result.legal_reference.strip()
        if legal_reference:
            legal_reference, _ = annotate_unverified_citations(legal_reference, docs)
        score = int(result.risk_score)
        return ClauseAnalysis(
            clause_index=clause.index, title=clause.title, content=clause.content,
            risk_level=level_from_score(score), risk_score=score, category=result.category,
            analysis=result.reason, legal_reference=legal_reference or None,
            recommendation=result.recommendation, source="llm", evidence=_to_evidence(docs),
        )


def build_recommendations(report: RiskReport, limit: int = 5) -> list[str]:
    recs = []
    for c in sorted(report.clauses, key=lambda c: c.risk_score, reverse=True):
        if c.risk_level == "Safety" or not c.recommendation:
            continue
        recs.append(f"[{c.title}] {c.recommendation}")
        if len(recs) >= limit:
            break
    for m in report.missing_clauses:
        if m.importance == "critical" and len(recs) < limit + 2:
            recs.append(f"[누락] {m.description}")
    if report.overall_risk_level == "HIGH":
        recs.append("위험 조항이 포함되어 있습니다. 서명 전 대한법률구조공단(132) 또는 변호사 상담을 권장합니다.")
    return recs
