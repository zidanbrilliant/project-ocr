from typing import Any

from fastapi import APIRouter, HTTPException

from app.infrastructure.reasoning.qwen_reasoning_adapter import QwenReasoningAdapter

router = APIRouter(prefix="/api/v1/reasoning", tags=["reasoning"])
_adapter = QwenReasoningAdapter()


@router.on_event("startup")
async def warmup_reasoning() -> None:
    await _adapter.warmup()


@router.get("/health")
async def health() -> dict[str, Any]:
    if not _adapter.is_available:
        raise HTTPException(status_code=503, detail=_adapter.load_error or "reasoning_not_ready")
    return {"ready": _adapter.is_available, "engine": "qwen3.5-9b", "error": _adapter.load_error}


@router.post("/select")
async def select(request: dict[str, Any]) -> dict[str, Any]:
    return await _adapter.select(request)


@router.post("/summarize")
async def summarize(request: dict[str, Any]) -> dict[str, Any]:
    return await _adapter.summarize(request)
