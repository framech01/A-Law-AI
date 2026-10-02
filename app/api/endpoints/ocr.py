"""
OCR API 엔드포인트
Spring Boot에서 S3 키를 받아 OCR 처리 후 텍스트 + 단어 좌표(오버레이) 반환
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import is_allowed_s3_key
from app.schemas.ocr_response import ContractOCRResponse
from app.services.ocr.ocr_service import OCRService
from app.util.s3_client import S3Client

router = APIRouter()


class OCRRequest(BaseModel):
    s3_key: str = Field(..., description="S3 객체 키")


def get_s3_client() -> S3Client:
    return S3Client()


def get_ocr_service() -> OCRService:
    return OCRService()


@router.post("/ocr", response_model=ContractOCRResponse, summary="S3 이미지 OCR")
async def run_ocr_from_s3(
    request: OCRRequest,
    include_overlay: bool = Query(True, description="오버레이(단어 좌표) 포함 여부"),
    structurize: bool = Query(False, description="GPT 구조화 여부"),
    s3_client: S3Client = Depends(get_s3_client),
    service: OCRService = Depends(get_ocr_service),
):
    """S3에서 이미지를 가져와 OCR 처리. words 좌표 포함."""
    if not is_allowed_s3_key(request.s3_key, settings.S3_ALLOWED_PREFIX):
        raise HTTPException(400, "허용되지 않은 S3 키입니다")
    try:
        image_bytes = await run_in_threadpool(s3_client.get_image, request.s3_key)
        return await run_in_threadpool(service.process_and_map, image_bytes, structurize, include_overlay)
    except FileNotFoundError:
        raise HTTPException(404, f"파일을 찾을 수 없습니다: {request.s3_key}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"OCR 처리 중 오류 발생: {e}")
        raise HTTPException(500, f"OCR 처리 실패: {e}")


@router.post("/ocr/full", response_model=ContractOCRResponse, summary="이미지 직접 업로드 OCR")
async def run_ocr_full(
    file: UploadFile = File(...),
    structurize: bool = Query(True, description="구조화 여부"),
    include_overlay: bool = Query(True, description="오버레이(단어 좌표) 포함 여부"),
    service: OCRService = Depends(get_ocr_service),
):
    """이미지 파일을 직접 업로드하여 OCR 처리 (전체 결과)."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "이미지 파일만 가능합니다")

    image_bytes = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(image_bytes) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"파일 크기는 {settings.MAX_UPLOAD_BYTES // (1024 * 1024)}MB 이하여야 합니다")
    if not image_bytes:
        raise HTTPException(400, "빈 파일입니다")

    try:
        return await run_in_threadpool(service.process_and_map, image_bytes, structurize, include_overlay)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"OCR 처리 중 오류: {e}")
        raise HTTPException(500, f"OCR 처리 실패: {e}")
