from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["local", "staging", "production"] = "local"
    SERVICE_NAME: str = "ai-invoice-verification-agent"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = ""
    RABBITMQ_URL: str = ""

    RABBITMQ_INPUT_EXCHANGE: str = "vision.ai.invoice.request.exchange"
    RABBITMQ_INPUT_QUEUE: str = "vision.ai.invoice.request.queue"
    RABBITMQ_INPUT_ROUTING_KEY: str = "vision.ai.invoice.request"
    RABBITMQ_RESULT_EXCHANGE: str = "vision.ai.invoice.result.exchange"
    RABBITMQ_RESULT_QUEUE: str = "vision.ai.invoice.result.queue"
    RABBITMQ_RESULT_ROUTING_KEY: str = "vision.ai.invoice.result"
    RABBITMQ_RETRY_EXCHANGE: str = "vision.ai.invoice.retry.exchange"
    RABBITMQ_RETRY_QUEUE: str = "vision.ai.invoice.retry.queue"
    RABBITMQ_RETRY_ROUTING_KEY: str = "vision.ai.invoice.retry"
    RABBITMQ_DLX: str = "vision.ai.invoice.dlx"
    RABBITMQ_DLQ: str = "vision.ai.invoice.dlq"

    IMAGE_SERVER_BASE_URL: str = ""
    IMAGE_SERVER_TIMEOUT_SECONDS: int = 30

    MAX_FILE_SIZE_MB: int = 25
    MIN_IMAGE_WIDTH: int = 800
    MIN_IMAGE_HEIGHT: int = 800
    MAX_PAGE_COUNT: int = 200

    YOLO_MODEL_PATH: str = "./models/best-v5.pt"
    YOLO_INPUT_SIZE: int = 640
    YOLO_CONFIDENCE_THRESHOLD: float = 0.40
    YOLO_NMS_THRESHOLD: float = 0.45

    OCR_ENGINE: str = "document_ocr"
    OCR_USE_GPU: bool = True
    OCR_FALLBACK_ENABLED: bool = True

    CONFIDENCE_THRESHOLD: int = 80
    AMOUNT_STAMP_DUTY_THRESHOLD: int = 5_000_000
    REQUIRE_SIGNATURE_FOR_INVOICE: bool = False
    REQUIRE_STAMP_FOR_INVOICE: bool = True
    REQUIRE_BARCODE_FOR_INVOICE: bool = False
    REQUIRE_MATERAI_ABOVE_THRESHOLD: bool = True

    DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT: int = 2
    DELIVERY_NOTE_REQUIRED_STAMP_COUNT: int = 2

    ENABLE_BARCODE_FALLBACK: bool = True

    MAX_RETRY: int = 5
    RETRY_BACKOFF_SECONDS: int = 30
    RETRY_BACKOFF_MULTIPLIER: int = 2

    WORKER_PREFETCH_COUNT: int = 1
    GPU_DEVICE_ID: int = 0

    API_AUTH_MODE: Literal["api_key", "jwt", "none"] = "api_key"
    INTERNAL_API_KEY: str = ""

    # --- concurrency ---
    MAX_PARALLEL_DOCUMENTS: int = 3
    MAX_PARALLEL_DOWNLOADS: int = 4
    MAX_PARALLEL_PDF_RENDER: int = 4
    MAX_PARALLEL_PAGES: int = 16
    OCR_CONCURRENCY: int = 2
    BARCODE_CONCURRENCY: int = 4
    GPU_CONCURRENCY: int = 1
    YOLO_GPU_CONCURRENCY: int = 1
    OCR_GPU_CONCURRENCY: int = 1

    # --- timeouts ---
    DOCUMENT_PROCESSING_TIMEOUT_SECONDS: int = 300
    PAGE_PROCESSING_TIMEOUT_SECONDS: int = 120
    JOB_PROCESSING_TIMEOUT_SECONDS: int = 900

    # --- database ---
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT_SECONDS: int = 30

    # --- outbox ---
    OUTBOX_POLL_INTERVAL_SECONDS: int = 5
    OUTBOX_BATCH_SIZE: int = 10
    OUTBOX_MAX_RETRY: int = 10
    OUTBOX_LOCK_TIMEOUT_SECONDS: int = 60

    # --- result ---
    RESULT_DELIVERY_MODE: Literal["INLINE", "HYBRID", "REFERENCE"] = "INLINE"
    MAX_RABBITMQ_RESULT_BYTES: int = 5_242_880
    RESULT_OBJECT_STORAGE_ENABLED: bool = False
    RESULT_OBJECT_STORAGE_BUCKET: str = ""
    RESULT_OBJECT_STORAGE_PREFIX: str = "results/"
    RESULT_SCHEMA_VERSION: str = "1.1"

    # --- retention ---
    FINAL_RESULT_RETENTION_DAYS: int = 365
    OCR_RESULT_RETENTION_DAYS: int = 90
    DETECTION_RESULT_RETENTION_DAYS: int = 90
    ERROR_LOG_RETENTION_DAYS: int = 90
    AUDIT_LOG_RETENTION_DAYS: int = 365
    OUTBOX_PUBLISHED_RETENTION_DAYS: int = 30
    ARTIFACT_RETENTION_DAYS: int = 30
    DEBUG_ARTIFACT_RETENTION_DAYS: int = 7

    # --- debug ---
    KEEP_DEBUG_ARTIFACTS: bool = False
    TEMP_ROOT_DIR: str = "/tmp/vision-ai"


settings = Settings()
