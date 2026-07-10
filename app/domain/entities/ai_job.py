import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AIJob:
    job_id: uuid.UUID
    queue_id: str
    idempotency_key: str
    doc_no: str
    doc_type: str
    doc_seq: int
    trans_type_cd: str
    file_nm: str
    ai_scan_app: str
    path_file: str
    processing_status: str = "Pending"
    retry_count: int = 0
    overall_result: str | None = None
    pv_no: str | None = None
    pv_year: str | None = None
    original_payload: dict[str, Any] | None = None
    request_datetime: datetime | None = None
    start_datetime: datetime | None = None
    finish_datetime: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
