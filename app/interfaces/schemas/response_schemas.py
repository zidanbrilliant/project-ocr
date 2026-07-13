from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="healthy")
    service: str = Field(default="ai-invoice-verification-agent")
    timestamp: str = Field(default="")


class ReadinessCheck(BaseModel):
    database: str = Field(default="unknown")
    rabbitmq: str = Field(default="unknown")
    ocr_model: str = Field(default="unknown")
    yolo_model: str = Field(default="unknown")


class ReadinessResponse(BaseModel):
    status: str = Field(default="ready")
    checks: ReadinessCheck = Field(default_factory=ReadinessCheck)


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
    ai_return_confidence: int | None
    ai_return_remark: str
    result: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list, description="Per-page OCR, detections, barcode")


class ReprocessResponse(BaseModel):
    queue_id: str
    status: str = "REPROCESS_QUEUED"
    message: str = "Job reprocess has been queued."


class ModelVersionResponse(BaseModel):
    ocr: dict[str, Any] = Field(default_factory=lambda: {"engine": "PaddleOCR", "version": "2.8", "use_gpu": True})
    detector: dict[str, Any] = Field(default_factory=lambda: {"framework": "Ultralytics", "model_name": "toyota-document-yolo", "model_version": "2026.07.01"})
    barcode: dict[str, Any] = Field(default_factory=lambda: {"engine": "zxing-cpp", "version": "2.x"})


