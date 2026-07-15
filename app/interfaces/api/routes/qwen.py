from base64 import b64decode

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.infrastructure.ocr.qwen_vl_adapter import QwenVLAdapter

router = APIRouter(prefix="/api/v1/qwen", tags=["qwen"])
_adapter = QwenVLAdapter()


class QwenRunRequest(BaseModel):
    image_b64: str
    prompt_instruction: str | None = None
    engine_name: str = "qwen2.5-vl"


@router.on_event("startup")
async def warmup_qwen() -> None:
    await _adapter.warmup()


@router.get("/health")
async def health() -> dict[str, bool | str]:
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    return {"status": "healthy", "model": "qwen2.5-vl"}


@router.post("/run")
async def run(payload: QwenRunRequest) -> dict:
    if not _adapter.is_available:
        await _adapter.warmup()
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "model_not_loaded")
    try:
        image_bytes = b64decode(payload.image_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_image_b64") from exc
    return await _adapter._run_qwen(
        image_bytes,
        prompt_instruction=payload.prompt_instruction,
        engine_name=payload.engine_name,
    )
