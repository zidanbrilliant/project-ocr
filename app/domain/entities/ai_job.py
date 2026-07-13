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
    # new fields
    message_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    source_system: str | None = None
    business_entity_type: str | None = None
    business_entity_id: str | None = None
    request_schema_version: str | None = None
    response_schema_version: str | None = "1.1"
    processing_result: str | None = None
    document_count: int = 0
    processed_document_count: int = 0
    failed_document_count: int = 0
    page_count: int = 0
    processed_page_count: int = 0
    failed_page_count: int = 0
    max_retry: int = 5
    business_context: dict[str, Any] | None = None
    processing_options: dict[str, Any] | None = None
    accepted_at: datetime | None = None
    row_version: int = 1
