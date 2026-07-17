from base64 import b64decode

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.infrastructure.ocr.paddleocr_vl_adapter import PaddleOCRVLAdapter

router = APIRouter(prefix="/api/v1/paddle", tags=["paddle"])
_adapter = PaddleOCRVLAdapter()


class PaddleRunRequest(BaseModel):
    image_b64: str
    extension: str = ".png"


@router.on_event("startup")
async def warmup_paddle() -> None:
    await _adapter.warmup()


@router.get("/health")
async def health() -> dict[str, str]:
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    return {"status": "healthy", "model": "paddleocr-vl"}


@router.post("/run")
async def run(payload: PaddleRunRequest) -> dict:
    if not _adapter.is_available:
        await _adapter.warmup()
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    try:
        image_bytes = b64decode(payload.image_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_image_b64") from exc
    return await _adapter.run(image_bytes, extension=payload.extension)
