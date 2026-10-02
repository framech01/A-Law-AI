"""
계약서 분석 API 엔드포인트 (동기 REST)
비동기 분석은 RabbitMQ consumer(app/services/rabbitmq_consumer.py)가 담당합니다.
"""
import asyncio

from fastapi import APIRouter, Body, HTTPException
from loguru import logger

from app.core.llm import LLMNotConfiguredError
from app.schemas.contract import (
    AnalysisResult,
    ContractRequest,
    FraudDetectionResponse,
    TermExplanation,
    TermRequest,
)
from app.services.analyzer import get_analysis_service, to_analysis_result

router = APIRouter()

RISKY_CONTRACT_EXAMPLE = {
    "summary": "위험 조항이 포함된 계약서",
    "value": {
        "text": "제1조 (목적물) 서울시 마포구 OO동 123-45\n제2조 (계약기간) 2024.1.1 ~ 2025.12.31\n"
                "제3조 (보증금) 보증금 5천만원, 월세 50만원\n"
                "제4조 (해지) 임대인은 언제든지 계약을 해지할 수 있으며 임차인은 이의를 제기할 수 없다.\n"
                "특약사항\n1. 월세는 매년 10% 인상한다.\n2. 보증금은 새로운 임차인이 입주한 후에 반환한다.",
        "contract_id": "CONTRACT_002",
    },
}


@router.post("/analyze", response_model=AnalysisResult, summary="계약서 전체 분석 (요약 + 위험 탐지)")
async def analyze_contract(request: ContractRequest = Body(..., openapi_examples={"위험 조항 포함": RISKY_CONTRACT_EXAMPLE})):
    """
    조항 분리 → 정규식 선필터 → RAG + GPT 조항별 분석 → 위험 점수/등급, 누락 조항, 권고안.
    include_summary=true(기본)이면 AI 요약을 병렬로 함께 생성합니다.
    """
    try:
        return await get_analysis_service().analyze_contract(request.text, request.contract_id, request.include_summary)
    except asyncio.TimeoutError:
        raise HTTPException(504, "분석 시간이 초과되었습니다")
    except Exception as e:
        logger.exception("Contract analysis failed")
        raise HTTPException(500, f"분석 실패: {e}")


@router.post("/detect-risk", response_model=AnalysisResult, summary="독소조항 위험 탐지")
async def detect_risk(request: ContractRequest = Body(..., openapi_examples={"위험 조항 포함": RISKY_CONTRACT_EXAMPLE})):
    """요약 없이 조항별 위험 분석만 수행합니다."""
    try:
        report = await get_analysis_service().analyze_risk(request.text)
    except asyncio.TimeoutError:
        raise HTTPException(504, "분석 시간이 초과되었습니다")
    except Exception as e:
        logger.exception("Risk detection failed")
        raise HTTPException(500, f"위험 탐지 실패: {e}")
    return to_analysis_result(request.contract_id, report, None)


@router.post("/explain/term", response_model=TermExplanation, summary="법률 용어 쉬운말 해설 (RAG)")
async def explain_term(request: TermRequest):
    try:
        return await get_analysis_service().explain_term(request.term, request.context, request.surrounding_text)
    except LLMNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"용어 해설 실패: {e}")


@router.post(
    "/analyze/fraud-detection",
    response_model=FraudDetectionResponse,
    summary="사기 위험 탐지 (하위 호환)",
    description="기존 응답 형식(fraud_risks / missing_clauses / illegal_clauses)을 유지합니다. "
                "내부적으로 /detect-risk 와 동일한 분석을 사용합니다.",
)
async def analyze_fraud_detection(request: ContractRequest):
    try:
        report = await get_analysis_service().analyze_risk(request.text)
    except asyncio.TimeoutError:
        raise HTTPException(504, "분석 시간이 초과되었습니다")
    except Exception as e:
        raise HTTPException(500, f"사기 탐지 실패: {e}")

    fraud_risks, illegal_clauses = [], []
    for c in report.clauses:
        if c.risk_level == "Safety":
            continue
        severity = "high" if c.risk_level == "Risk" else "medium"
        fraud_risks.append({"pattern": c.category or c.title, "severity": severity,
                            "description": c.analysis, "location": c.title})
        if c.risk_level == "Risk" and c.legal_reference:
            illegal_clauses.append({"clause_text": c.content, "violation": c.category or c.analysis,
                                    "legal_reference": c.legal_reference, "recommendation": c.recommendation})
    return FraudDetectionResponse(
        fraud_risks=fraud_risks,
        missing_clauses=[m.model_dump() for m in report.missing_clauses],
        illegal_clauses=illegal_clauses,
        risk_score=report.overall_risk_score,
    )
