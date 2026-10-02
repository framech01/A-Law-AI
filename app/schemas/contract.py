"""
계약서 분석 관련 스키마 (REST API)
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RiskLevelLiteral = Literal["Risk", "Caution", "Safety"]
OverallRiskLevel = Literal["HIGH", "MEDIUM", "LOW"]


class ContractRequest(BaseModel):
    """계약서 분석 요청"""
    text: str = Field(..., min_length=1, max_length=100_000, description="계약서 텍스트(OCR 결과)")
    contract_id: str = Field(..., description="계약서 ID")
    include_summary: bool = Field(True, description="AI 요약 포함 여부 (/analyze 전용)")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": "제1조 (목적물) 서울특별시 강남구 역삼동 123-45 아파트 101동 1001호\n"
                            "제2조 (계약 기간) 2024년 1월 1일부터 2026년 1월 1일까지로 한다.\n"
                            "특약사항\n1. 임차인은 계약갱신요구권을 행사하지 않기로 한다.",
                    "contract_id": "CONTRACT_20240111_001",
                }
            ]
        }
    )


class Evidence(BaseModel):
    """판단 근거 문서"""
    title: str = ""
    content: str = ""
    namespace: str = ""
    score: float = 0.0


class ClauseAnalysis(BaseModel):
    """조항 분석 결과"""
    clause_index: int = Field(0, description="조항 순번 (0부터)")
    title: str = Field(..., description="조항 제목")
    content: str = Field(..., description="조항 내용")
    risk_level: RiskLevelLiteral = Field(..., description="위험도: Risk, Caution, Safety")
    risk_score: int = Field(0, ge=0, le=100, description="위험 점수 (0-100)")
    category: str = Field("", description="위험 유형")
    analysis: str = Field(..., description="위험 판단 근거 설명")
    legal_reference: Optional[str] = Field(None, description="관련 법령")
    recommendation: str = Field("", description="개선 권고안")
    source: Literal["rule", "llm", "skipped", "error"] = Field("llm", description="판정 방식")
    evidence: List[Evidence] = Field(default_factory=list, description="RAG 근거 문서")


class MissingClause(BaseModel):
    """누락된 필수 조항"""
    clause_name: str = Field(..., description="조항명")
    importance: Literal["critical", "important", "recommended"] = Field(..., description="중요도")
    description: str = Field(..., description="설명")
    legal_basis: Optional[str] = Field(None, description="법적 근거")


class ContractSummaryResult(BaseModel):
    """AI 요약"""
    title: str = Field("", description="계약서 제목/유형")
    parties: List[str] = Field(default_factory=list, description="계약 당사자")
    key_terms: List[str] = Field(default_factory=list, description="핵심 조건 (보증금, 차임 등)")
    duration: str = Field("", description="계약 기간")
    summary_text: str = Field("", description="요약 텍스트")
    important_dates: List[str] = Field(default_factory=list, description="주요 일정")


class AnalysisResult(BaseModel):
    """전체 분석 결과"""
    contract_id: str = Field(..., description="계약서 ID")
    contract_domain: str = Field("주거", description="주거 | 상가")
    total_clauses: int = Field(..., description="총 조항 수")
    risk_summary: Dict[str, int] = Field(..., description="위험도별 조항 수 {Risk, Caution, Safety}")
    clauses: List[ClauseAnalysis] = Field(default_factory=list, description="조항별 분석")
    missing_clauses: List[MissingClause] = Field(default_factory=list, description="누락 조항")
    overall_risk_score: float = Field(..., description="전체 위험도 점수 (0-100)")
    overall_risk_level: OverallRiskLevel = Field("LOW", description="HIGH | MEDIUM | LOW")
    summary: Optional[ContractSummaryResult] = Field(None, description="AI 요약")
    recommendations: List[str] = Field(default_factory=list, description="권고사항")
    processing_time_ms: int = Field(0, description="처리 시간(ms)")


class FraudDetectionResponse(BaseModel):
    """사기 위험 탐지 응답 (하위 호환)"""
    fraud_risks: List[Dict[str, Any]] = Field(default_factory=list, description="사기 위험 항목")
    missing_clauses: List[Dict[str, Any]] = Field(default_factory=list, description="누락 조항")
    illegal_clauses: List[Dict[str, Any]] = Field(default_factory=list, description="불법 조항")
    risk_score: float = Field(..., description="종합 위험도 점수 (0-100)")


class TermRequest(BaseModel):
    """법률 용어 해설 요청"""
    term: str = Field(..., min_length=1, max_length=50, description="해설할 용어", examples=["확정일자"])
    context: str = Field(default="", max_length=500, description="문맥", examples=["주택임대차보호법"])
    surrounding_text: str = Field(default="", max_length=2000, description="주변 텍스트")


class TermExplanation(BaseModel):
    """법률 용어 해설"""
    term: str = Field(..., description="용어")
    simple_explanation: str = Field(..., description="쉬운 설명")
    legal_definition: str = Field(..., description="법률적 정의")
    examples: List[str] = Field(default_factory=list, description="예시")
    legal_reference: Optional[str] = Field(None, description="관련 법령")
