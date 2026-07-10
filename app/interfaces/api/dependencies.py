from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.audit_log_postgres_repository import AuditLogPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.database.session import async_session_factory
from app.shared.config.settings import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Depends(_api_key_header)) -> None:
    if settings.API_AUTH_MODE == "none":
        return
    if settings.API_AUTH_MODE == "api_key":
        if not api_key or api_key != settings.INTERNAL_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_job_repo(session: AsyncSession = Depends(get_session)) -> AIJobPostgresRepository:
    return AIJobPostgresRepository(session)


async def get_result_repo(session: AsyncSession = Depends(get_session)) -> ResultPostgresRepository:
    return ResultPostgresRepository(session)


async def get_audit_repo(session: AsyncSession = Depends(get_session)) -> AuditLogPostgresRepository:
    return AuditLogPostgresRepository(session)
