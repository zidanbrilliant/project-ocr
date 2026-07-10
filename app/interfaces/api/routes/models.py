from fastapi import APIRouter, Depends

from app.interfaces.api.dependencies import verify_api_key
from app.interfaces.schemas.response_schemas import ModelVersionResponse

router = APIRouter(prefix="/api/v1/models", tags=["models"], dependencies=[Depends(verify_api_key)])


@router.get("/version", response_model=ModelVersionResponse)
async def model_version() -> ModelVersionResponse:
    return ModelVersionResponse()
