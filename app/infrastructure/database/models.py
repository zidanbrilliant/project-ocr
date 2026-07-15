import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.session import Base


class AIJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    doc_no: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    doc_seq: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trans_type_cd: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_nm: Mapped[str] = mapped_column(String(255), nullable=False)
    ai_scan_app: Mapped[str] = mapped_column(String(50), nullable=False)
    path_file: Mapped[str] = mapped_column(Text, nullable=False)
    pv_no: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    pv_year: Mapped[str | None] = mapped_column(String(4), index=True, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default="Pending")
    overall_result: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_datetime: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    start_datetime: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    finish_datetime: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    # --- new columns for multi-document support ---
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_system: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    business_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    business_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    business_entity_year: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    request_schema_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_schema_version: Mapped[str | None] = mapped_column(String(20), nullable=True, default="1.1")
    processing_result: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    business_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processing_options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("source_system", "message_id", name="uq_job_message"),
        CheckConstraint("document_count >= 0", name="ck_job_doc_count"),
        CheckConstraint("page_count >= 0", name="ck_job_page_count"),
        CheckConstraint("retry_count >= 0", name="ck_job_retry_count"),
    )

    documents = relationship("AIDocument", back_populates="job", cascade="all, delete-orphan")
    ocr_results = relationship("AIOCRResult", back_populates="job", cascade="all, delete-orphan")
    detection_results = relationship("AIDetectionResult", back_populates="job", cascade="all, delete-orphan")
    barcode_results = relationship("AIBarcodeResult", back_populates="job", cascade="all, delete-orphan")
    duplicate_check_results = relationship("AIDuplicateCheckResult", back_populates="job", cascade="all, delete-orphan")
    business_validation_results = relationship("AIBusinessValidationResult", back_populates="job", cascade="all, delete-orphan")
    document_summaries = relationship("AIDocumentSummary", back_populates="job", cascade="all, delete-orphan")
    final_result = relationship("AIFinalResult", back_populates="job", uselist=False, cascade="all, delete-orphan")
    error_logs = relationship("AIErrorLog", back_populates="job", cascade="all, delete-orphan")
    audit_logs = relationship("AIAuditLog", back_populates="job", cascade="all, delete-orphan")
    retry_logs = relationship("AIRetryLog", back_populates="job", cascade="all, delete-orphan")
    outbox_events = relationship("AIOutboxEvent", back_populates="job", cascade="all, delete-orphan")


class AIDocument(Base):
    __tablename__ = "ai_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    external_document_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    document_category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    readable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    validation_errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # --- new columns ---
    document_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    processing_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True, default="PENDING")
    processing_result: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    document_result: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    doc_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    job = relationship("AIJob", back_populates="documents")
    ocr_results = relationship("AIOCRResult", back_populates="document", cascade="all, delete-orphan")
    detection_results = relationship("AIDetectionResult", back_populates="document", cascade="all, delete-orphan")
    barcode_results = relationship("AIBarcodeResult", back_populates="document", cascade="all, delete-orphan")
    duplicate_check_results = relationship("AIDuplicateCheckResult", back_populates="document", cascade="all, delete-orphan")
    business_validation_results = relationship("AIBusinessValidationResult", back_populates="document", cascade="all, delete-orphan")
    summary = relationship("AIDocumentSummary", back_populates="document", uselist=False, cascade="all, delete-orphan")


class AIOCRResult(Base):
    __tablename__ = "ai_ocr_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    engine_name: Mapped[str] = mapped_column(String(50), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fields_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    average_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="ocr_results")
    document = relationship("AIDocument", back_populates="ocr_results")


class AIDetectionResult(Base):
    __tablename__ = "ai_detection_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    crop_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_colour: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="detection_results")
    document = relationship("AIDocument", back_populates="detection_results")


class AIBarcodeResult(Base):
    __tablename__ = "ai_barcode_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    barcode_found: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    barcode_decoded: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    barcode_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    barcode_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    barcode_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decoder_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="barcode_results")
    document = relationship("AIDocument", back_populates="barcode_results")


class AIDuplicateCheckResult(Base):
    __tablename__ = "ai_duplicate_check_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    matched_document: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    matched_pv: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    matched_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lookup_window_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="duplicate_check_results")
    document = relationship("AIDocument", back_populates="duplicate_check_results")


class AIBusinessValidationResult(Base):
    __tablename__ = "ai_business_validation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=True, index=True)
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(150), nullable=False)
    rule_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    required_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="business_validation_results")
    document = relationship("AIDocument", back_populates="business_validation_results")


class AIDocumentSummary(Base):
    __tablename__ = "ai_document_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    document_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), unique=True, nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    total_validation: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_validation: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_validation: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="document_summaries")
    document = relationship("AIDocument", back_populates="summary")


class AIFinalResult(Base):
    __tablename__ = "ai_final_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), unique=True, nullable=False, index=True)
    queue_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    overall_result: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True, index=True)
    ai_confidence_level: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_return_status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    ai_return_cd: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    ai_return_remark: Mapped[str] = mapped_column(Text, nullable=False)
    ai_return_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    internal_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rabbitmq_result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="final_result")


class AIErrorLog(Base):
    __tablename__ = "ai_error_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=True, index=True)
    queue_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    document_pk: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_documents.id"), nullable=True, index=True)
    error_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="error_logs")
    document = relationship("AIDocument")


class AIAuditLog(Base):
    __tablename__ = "ai_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=True, index=True)
    queue_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="audit_logs")


class AIRetryLog(Base):
    __tablename__ = "ai_retry_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=True, index=True)
    queue_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    job = relationship("AIJob", back_populates="retry_logs")


class AIInboxMessage(Base):
    __tablename__ = "ai_inbox_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    queue_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    routing_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="RECEIVED", index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_system", "message_id", name="uq_inbox_message"),
    )


class AIOutboxEvent(Base):
    __tablename__ = "ai_outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_jobs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    destination_exchange: Mapped[str | None] = mapped_column(String(100), nullable=True)
    routing_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    available_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "event_type", name="uq_outbox_event"),
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt"),
        CheckConstraint("max_attempts >= 1", name="ck_outbox_max_attempt"),
    )

    job = relationship("AIJob", back_populates="outbox_events")
