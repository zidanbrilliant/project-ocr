from fastapi import Request
from fastapi.responses import JSONResponse

from app.interfaces.schemas.response_schemas import ErrorResponse


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(error={"code": "NOT_FOUND", "message": "Resource not found."}).model_dump(),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error={"code": "INTERNAL_ERROR", "message": "An internal error occurred."}).model_dump(),
    )
