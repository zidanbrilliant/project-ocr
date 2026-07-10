import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AIAuditLog


class AuditLogPostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        job_id: uuid.UUID | None,
        queue_id: str | None,
        actor: str,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        model = AIAuditLog(
            job_id=job_id,
            queue_id=queue_id,
            actor=actor,
            action=action,
            before_json=before,
            after_json=after,
            metadata_json=metadata,
        )
        self._session.add(model)
