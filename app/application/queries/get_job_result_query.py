from dataclasses import dataclass
from typing import Any


@dataclass
class JobResultResponse:
    queue_id: str
    ai_return_status: str
    ai_return_cd: str
    ai_return_confidence: int | None
    ai_return_remark: str
    result: dict[str, Any] | None = None
