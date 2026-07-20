from typing import Any

from pydantic import BaseModel, Field


class JobStatusResponse(BaseModel):
    queue_id: str
    job_id: str
    status: str
    doc_no: str
    doc_type: str
    retry_count: int
    created_at: str | None = None
    completed_at: str | None = None


class JobResultResponse(BaseModel):
    queue_id: str
    ai_return_status: str
    ai_return_cd: str
    ai_return_confidence: float | None
    ai_return_remark: str
    result: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list, description="Per-page OCR, detections, barcode")


class ReprocessResponse(BaseModel):
    queue_id: str
    status: str = "REPROCESS_QUEUED"
    message: str = "Job reprocess has been queued."



