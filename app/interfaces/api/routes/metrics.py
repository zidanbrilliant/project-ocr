from fastapi import APIRouter, Depends
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.interfaces.api.dependencies import verify_api_key

router = APIRouter(tags=["metrics"])


@router.get("/metrics", dependencies=[Depends(verify_api_key)])
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
