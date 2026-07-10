from datetime import datetime, timezone

from fastapi import APIRouter

from app.interfaces.schemas.response_schemas import HealthResponse
from app.shared.config.settings import settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
