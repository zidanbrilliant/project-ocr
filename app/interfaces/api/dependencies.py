import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.database.session import async_session_factory
from app.shared.config.settings import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Depends(_api_key_header)) -> None:
    if settings.API_AUTH_MODE == "none":
        return
    invalid_key = (
        not settings.INTERNAL_API_KEY or not api_key or not secrets.compare_digest(api_key, settings.INTERNAL_API_KEY)
    )
    if settings.API_AUTH_MODE == "api_key" and invalid_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_job_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AIJobPostgresRepository:
    return AIJobPostgresRepository(session)


async def get_result_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResultPostgresRepository:
    return ResultPostgresRepository(session)
