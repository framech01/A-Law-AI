"""
계약서 AI 요약
"""
from loguru import logger

from app.core.config import settings
from app.core.llm import ainvoke_structured
from app.schemas.contract import ContractSummaryResult

SYSTEM_PROMPT = """당신은 한국 부동산 임대차 계약서를 임차인이 이해하기 쉽게 요약하는 도우미입니다.
계약서 원문에 있는 내용만 사용하고 추측하지 마세요. 원문에 없는 항목은 빈 값으로 두세요.
- title: 계약서 유형 (예: 주택 월세 계약서, 상가 전세 계약서)
- parties: '임대인 홍길동'처럼 역할과 이름 (개인정보 보호를 위해 주민번호·전화번호는 제외)
- key_terms: 보증금, 차임, 관리비, 계약금·잔금 등 핵심 금액 조건 (예: '보증금 1억원')
- duration: 'YYYY-MM-DD ~ YYYY-MM-DD'
- summary_text: 3~5문장 요약 (특약사항 중 주의할 점 포함)
- important_dates: 잔금일, 입주일, 계약 만료일 등"""


async def summarize_contract(text: str) -> ContractSummaryResult:
    if not settings.llm_configured:
        return ContractSummaryResult(summary_text="AI 요약을 사용할 수 없습니다 (OPENAI_API_KEY 미설정).")
    try:
        return await ainvoke_structured(ContractSummaryResult, [
            ("system", SYSTEM_PROMPT),
            ("human", text[:12000]),
        ])
    except Exception as e:
        logger.error(f"Contract summary failed: {e}")
        return ContractSummaryResult(summary_text="요약 생성 중 오류가 발생했습니다.")
