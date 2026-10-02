"""
API 라우터 등록
"""
from fastapi import APIRouter, Depends

from app.api.endpoints import chat, contract, ocr, rag
from app.core.security import require_internal_token

api_router = APIRouter(dependencies=[Depends(require_internal_token)])

# 계약서 분석 (요약 + 독소조항 위험 탐지 + 용어 해설)
api_router.include_router(contract.router, prefix="/contracts", tags=["계약서 분석"])

# 계약서 OCR
api_router.include_router(ocr.router, prefix="/contracts", tags=["계약서 OCR"])

# RAG 법률 챗봇
api_router.include_router(chat.router, prefix="/chat", tags=["법률 챗봇"])

# RAG 관리 (관리자 토큰 필요)
api_router.include_router(rag.router, prefix="/rag", tags=["RAG 관리"])
