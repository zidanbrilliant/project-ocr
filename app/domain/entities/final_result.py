import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FinalResult:
    job_id: uuid.UUID
    queue_id: str
    overall_result: str
    processing_status: str
    ai_confidence: float | None
    ai_confidence_level: str | None
    ai_note: str | None
    ai_return_status: str
    ai_return_cd: str
    ai_return_remark: str
    ai_return_confidence: int | None
    internal_result_json: dict[str, Any] | None = None
    rabbitmq_result_payload: dict[str, Any] | None = None
    processing_time_ms: int | None = None
    published_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
