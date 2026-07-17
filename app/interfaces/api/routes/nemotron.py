from base64 import b64decode

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.infrastructure.ocr.nemotron_parse_adapter import NemotronParseAdapter

router = APIRouter(prefix="/api/v1/nemotron", tags=["nemotron"])
_adapter = NemotronParseAdapter()


class NemotronRunRequest(BaseModel):
    image_b64: str
    extension: str = ".png"


@router.on_event("startup")
async def warmup_nemotron() -> None:
    await _adapter.warmup()


@router.get("/health")
async def health() -> dict[str, str]:
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    return {"status": "healthy", "model": "nemotron-parse-v1.2"}


@router.post("/run")
async def run(payload: NemotronRunRequest) -> dict:
    try:
        image_bytes = b64decode(payload.image_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_image_b64") from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="empty_image")
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    return await _adapter.run(image_bytes, extension=payload.extension)
