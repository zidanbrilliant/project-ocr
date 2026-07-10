import uuid
from typing import Any, Protocol


class AuditLogRepository(Protocol):
    async def log(
        self,
        job_id: uuid.UUID | None,
        queue_id: str | None,
        actor: str,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
