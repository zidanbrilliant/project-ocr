import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedDocumentRequest:
    external_document_id: str
    document_index: int
    document_type: str
    document_category: str
    file_name: str
    file_url: str
    mime_type: str | None = None
    checksum_sha256: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class NormalizedJobRequest:
    message_id: str
    queue_id: str
    correlation_id: str
    trace_id: str | None = None
    source_system: str = "UNKNOWN"
    request_schema_version: str = "1.0"
    idempotency_key: str | None = None
    business_entity_type: str | None = None
    business_entity_id: str | None = None
    business_entity_year: str | None = None
    transaction_type: str | None = None
    documents: list[NormalizedDocumentRequest] = field(default_factory=list)
    processing_options: dict[str, Any] | None = None
    business_context: dict[str, Any] | None = None
    request_metadata: dict[str, Any] | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass
class PageProcessingResult:
    page_index: int
    page_number: int
    processing_status: str
    processing_result: str | None = None
    width: int | None = None
    height: int | None = None
    dpi: int | None = None
    rotation: int = 0
    page_width_pt: float | None = None
    page_height_pt: float | None = None
    text_layer_detected: bool = False
    readable: bool = False
    quality_metrics: dict[str, Any] | None = None
    ocr_raw_text: str | None = None
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    text_blocks: list[dict[str, Any]] | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    barcodes: list[dict[str, Any]] = field(default_factory=list)
    extracted_fields: list[dict[str, Any]] = field(default_factory=list)
    financials: dict[str, Any] | None = None
    timings_ms: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DocumentProcessingResult:
    document_index: int
    external_document_id: str
    document_type: str
    processing_status: str
    processing_result: str | None = None
    document_result: str | None = None
    confidence: float | None = None
    confidence_level: str | None = None
    manual_review_required: bool = False
    pages: list[PageProcessingResult] = field(default_factory=list)
    ocr_aggregate: dict[str, Any] | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    detections_aggregated: dict[str, Any] | None = None
    barcode_result: dict[str, Any] | None = None
    extracted_fields: list[dict[str, Any]] = field(default_factory=list)
    field_candidate_audit: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reasoning: dict[str, Any] | None = None
    duplicate_check: dict[str, Any] | None = None
    validations: list[dict[str, Any]] = field(default_factory=list)
    document_summary: dict[str, Any] | None = None
    quality_metrics: dict[str, Any] | None = None
    processing_time_ms: int | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
