"""
계약서 분석 메시지 DTO
- Spring Boot와 RabbitMQ로 통신하기 위한 메시지 스키마 (camelCase)
- 기존 필드는 유지하고, 신규 필드는 추가만 했습니다(하위 호환).
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AnalysisStatus(str, Enum):
    """분석 상태"""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RiskLevel(str, Enum):
    """위험도 레벨"""
    RISK = "Risk"
    CAUTION = "Caution"
    SAFETY = "Safety"


_CAMEL = ConfigDict(populate_by_name=True)


# ========================
# RabbitMQ 수신 메시지 (Spring Boot → FastAPI)
# ========================

class ContractAnalysisRequest(BaseModel):
    """
    Spring Boot에서 발행하는 분석 요청 메시지
    Queue: contract.analysis.queue

    contractText가 비어 있으면 s3Key의 이미지를 OCR한 텍스트로 분석합니다.
    """
    model_config = _CAMEL

    task_id: str = Field(..., alias="taskId", description="작업 ID (UUID)")
    s3_key: str = Field(default="", alias="s3Key", description="S3에 저장된 계약서 파일 키")
    user_id: Optional[int] = Field(default=None, alias="userId", description="요청 사용자 ID")
    contract_text: str = Field(default="", alias="contractText", description="OCR 추출 텍스트")
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")


# ========================
# RabbitMQ 발행 메시지 (FastAPI → Spring Boot)
# ========================

class ClauseRiskResult(BaseModel):
    """개별 조항 위험도 분석 결과"""
    model_config = _CAMEL

    clause_title: str = Field(..., alias="clauseTitle")
    clause_content: str = Field(..., alias="clauseContent")
    risk_level: str = Field(..., alias="riskLevel")
    legal_reference: str = Field(default="", alias="legalReference")
    recommendation: str = Field(default="")
    reasoning_summary: str = Field(default="", alias="reasoningSummary")
    # 신규 (추가 필드)
    risk_score: int = Field(default=0, alias="riskScore")
    category: str = Field(default="")


class MissingClauseResult(BaseModel):
    model_config = _CAMEL

    clause_name: str = Field(..., alias="clauseName")
    importance: str
    description: str
    legal_basis: Optional[str] = Field(default=None, alias="legalBasis")


class RiskAnalysisResult(BaseModel):
    """Risk 분석 전체 결과"""
    model_config = _CAMEL

    total_clauses: int = Field(..., alias="totalClauses")
    risk_count: int = Field(default=0, alias="riskCount")
    caution_count: int = Field(default=0, alias="cautionCount")
    safety_count: int = Field(default=0, alias="safetyCount")
    risk_percentage: float = Field(default=0.0, alias="riskPercentage")
    clause_results: List[ClauseRiskResult] = Field(default_factory=list, alias="clauseResults")
    # 신규 (추가 필드)
    overall_risk_score: float = Field(default=0.0, alias="overallRiskScore")
    overall_risk_level: str = Field(default="LOW", alias="overallRiskLevel")
    missing_clauses: List[MissingClauseResult] = Field(default_factory=list, alias="missingClauses")
    recommendations: List[str] = Field(default_factory=list)


class ContractSummary(BaseModel):
    """AI 요약 결과"""
    model_config = _CAMEL

    title: str = Field(default="", description="계약서 제목/유형")
    parties: List[str] = Field(default_factory=list, description="계약 당사자")
    key_terms: List[str] = Field(default_factory=list, alias="keyTerms", description="핵심 조건")
    duration: str = Field(default="", description="계약 기간")
    summary_text: str = Field(..., alias="summaryText", description="요약 텍스트")
    important_dates: List[str] = Field(default_factory=list, alias="importantDates")


class ContractAnalysisResult(BaseModel):
    """
    FastAPI에서 발행하는 분석 결과 메시지
    Exchange: contract.analysis.result / routing key: ai.result
    """
    model_config = _CAMEL

    task_id: str = Field(..., alias="taskId")
    status: AnalysisStatus = Field(default=AnalysisStatus.COMPLETED)

    summary: Optional[ContractSummary] = Field(default=None)
    risk_analysis: Optional[RiskAnalysisResult] = Field(default=None, alias="riskAnalysis")

    processing_time_ms: int = Field(default=0, alias="processingTimeMs")
    completed_at: datetime = Field(default_factory=datetime.now, alias="completedAt")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")

    def to_rabbitmq_message(self) -> Dict[str, Any]:
        """RabbitMQ 발행용 JSON 변환 (camelCase)"""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")
