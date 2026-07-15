from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from app.interfaces.schemas.response_schemas import HealthResponse
from app.shared.config.settings import settings
from app.shared.health_registry import all_status as _model_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    models = _model_status()
    all_ok = all(m.get("available", False) for m in models.values()) if models else True
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": settings.SERVICE_NAME,
        "cuda": __import__("torch").cuda.is_available(),
        "models": models or None,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
