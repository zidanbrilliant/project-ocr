import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class JobStatusResult:
    queue_id: str
    job_id: str
    status: str
    doc_no: str
    doc_type: str
    retry_count: int
    created_at: datetime | None
    completed_at: datetime | None
