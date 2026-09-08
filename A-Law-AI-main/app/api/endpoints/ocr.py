"""
OCR API 엔드포인트
Spring Boot에서 S3 키를 받아 OCR 처리 후 텍스트 + 오버레이 반환
"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import is_allowed_s3_key
from app.schemas.ocr_response import ContractOCRResponse
from app.services.ocr.ocr_service import OCRService
from app.util.s3_client import S3Client

router = APIRouter()


# ===========================================
# Request 스키마
# ===========================================

class OCRRequest(BaseModel):
    s3_key: str = Field(..., description="S3 객체 키")


# ===========================================
# 의존성
# ===========================================

def get_s3_client() -> S3Client:
    return S3Client()


def get_ocr_service() -> OCRService:
    return OCRService()


# ===========================================
# API 엔드포인트
# ===========================================

@router.post("/ocr", response_model=ContractOCRResponse, summary="S3 이미지 OCR")
async def run_ocr_from_s3(
    request: OCRRequest,
    s3_client: Annotated[S3Client, Depends(get_s3_client)],
    service: Annotated[OCRService, Depends(get_ocr_service)],
    include_overlay: Annotated[bool, Query(description="오버레이(단어 좌표) 포함 여부")] = True,
):
    """S3에서 이미지를 가져와 OCR 처리. words 좌표 포함."""
    if not is_allowed_s3_key(request.s3_key, settings.S3_ALLOWED_PREFIX):
        raise HTTPException(400, "허용되지 않은 S3 객체 키입니다.")
    try:
        image_bytes = s3_client.get_image(request.s3_key)

        result = service.process_and_map(
            image_bytes=image_bytes,
            structurize=False,
            include_overlay=include_overlay,
        )

        return result

    except FileNotFoundError as e:
        logger.error(f"S3 파일을 찾을 수 없음: {e}")
        raise HTTPException(404, "파일을 찾을 수 없습니다.") from e
    except Exception as e:
        logger.error(f"OCR 처리 중 오류 발생: {e}")
        raise HTTPException(500, "OCR 처리 중 오류가 발생했습니다.") from e


@router.post("/ocr/full", response_model=ContractOCRResponse, summary="이미지 직접 업로드 OCR")
async def run_ocr_full(
    file: Annotated[UploadFile, File()],
    service: Annotated[OCRService, Depends(get_ocr_service)],
    structurize: Annotated[bool, Query(description="구조화 여부")] = True,
    include_overlay: Annotated[bool, Query(description="오버레이(단어 좌표) 포함 여부")] = True,
):
    """이미지 파일을 직접 업로드하여 OCR 처리 (전체 결과)."""
    try:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(400, "이미지 파일만 가능합니다")

        image_bytes = await file.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(image_bytes) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "업로드 허용 크기를 초과했습니다.")

        result = service.process_and_map(
            image_bytes=image_bytes,
            structurize=structurize,
            include_overlay=include_overlay,
        )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"이미지 처리 오류: {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"OCR 처리 중 오류: {e}")
        raise HTTPException(500, "OCR 처리 중 오류가 발생했습니다.") from e
