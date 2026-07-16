from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["local", "staging", "production"] = "local"
    RUN_MODE: Literal["standalone", "api", "worker"] = "standalone"
    SERVICE_NAME: str = "ai-invoice-verification-agent"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = ""
    RABBITMQ_URL: str = ""
    ENABLE_DATABASE: bool = False
    ENABLE_RABBITMQ: bool = False

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
    YOLO_CONFIDENCE_THRESHOLD: float = 0.25
    YOLO_NMS_THRESHOLD: float = 0.45

    OCR_PROVIDER: Literal["qwen", "paddleocr_vl"] = "paddleocr_vl"
    OCR_ENABLE_PDF_TEXT_EXTRACTION: bool = True

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
    VLM_MODEL_PATH: str = ""
    VLM_MAX_TOKENS: int = 2048
    QWEN_SERVICE_URL: str = ""
    PADDLEOCR_VL_MODEL_DIR: str = "/mnt/models/PaddleOCR-VL-1.6"

    ENABLE_QWEN_REASONING: bool = False

    API_AUTH_MODE: Literal["api_key", "jwt", "none"] = "api_key"
    INTERNAL_API_KEY: str = ""

    # --- concurrency ---
    MAX_PARALLEL_DOCUMENTS: int = 3
    MAX_PARALLEL_DOWNLOADS: int = 4
    MAX_PARALLEL_PAGES: int = 16

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
settings = Settings()
