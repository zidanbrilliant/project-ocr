from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobResultResponse:
    queue_id: str
    ai_return_status: str
    ai_return_cd: str
    ai_return_confidence: float | None
    ai_return_remark: str
    result: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = field(default_factory=list)
