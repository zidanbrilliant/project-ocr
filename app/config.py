from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class PipelineConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    RABBITMQ_URL: str = ""
    RABBITMQ_INPUT_QUEUE: str = "ai.transaction.input"
    RABBITMQ_INPUT_EXCHANGE: str = "ai.transaction.exchange"
    RABBITMQ_INPUT_ROUTING_KEY: str = "ai.transaction.input"
    RABBITMQ_RESULT_EXCHANGE: str = "ai.transaction.result.exchange"
    RABBITMQ_RESULT_QUEUE: str = "ai.transaction.result"
    RABBITMQ_RESULT_ROUTING_KEY: str = "ai.transaction.result"
    RABBITMQ_DLX: str = "ai.transaction.dlx"
    RABBITMQ_DLQ: str = "ai.transaction.dlq"
    RABBITMQ_PREFETCH_COUNT: int = 1

    DATABASE_URL: str = ""

    YOLO_MODEL_PATH: str = "./models/best-v5.pt"
    YOLO_INPUT_SIZE: int = 640
    YOLO_CONFIDENCE_THRESHOLD: float = 0.25
    YOLO_NMS_THRESHOLD: float = 0.45
    YOLO_BATCH_SIZE: int = 8
    YOLO_MAX_BATCH_WAIT_MS: int = 20

    OCR_ENGINE: Literal["easyocr", "tesseract"] = "easyocr"
    OCR_USE_GPU: bool = True
    OCR_PROCESS_WORKERS: int = 2
    EASYOCR_BATCH_SIZE: int = 4
    EASYOCR_DOWNLOAD_ENABLED: bool = True

    PDF_DEFAULT_DPI: int = 200
    PDF_MIN_DPI: int = 150
    PDF_MAX_DPI: int = 300
    RENDER_PROCESS_WORKERS: int = 4

    DOCUMENT_CONCURRENCY: int = 3
    PAGE_CONCURRENCY: int = 16
    DOWNLOAD_CONCURRENCY: int = 4

    DOWNLOAD_TIMEOUT_SECONDS: int = 60
    PDF_INSPECT_TIMEOUT_SECONDS: int = 30
    PDF_RENDER_TIMEOUT_SECONDS: int = 120
    YOLO_TIMEOUT_SECONDS: int = 60
    OCR_TIMEOUT_SECONDS: int = 120
    TRANSACTION_TIMEOUT_SECONDS: int = 900
    PUBLISH_TIMEOUT_SECONDS: int = 30

    MAX_RETRY: int = 5
    RETRY_BACKOFF_SECONDS: int = 30
    RETRY_BACKOFF_MULTIPLIER: int = 2

    TEMP_DIR: str = "/tmp/vision-ai"
    OBJECT_STORAGE_ENDPOINT: str = ""
    OBJECT_STORAGE_ACCESS_KEY: str = ""
    OBJECT_STORAGE_SECRET_KEY: str = ""
    OBJECT_STORAGE_BUCKET: str = "vision-ai-artifacts"

    GPU_DEVICE_ID: int = 0
    WORKER_CONCURRENCY: int = 1
    ENABLE_METRICS: bool = True
    ENABLE_SENTRY: bool = False
    SENTRY_DSN: str = ""

    CONFIDENCE_THRESHOLD: int = 80
    AMOUNT_STAMP_DUTY_THRESHOLD: int = 5_000_000
    REQUIRE_SIGNATURE_FOR_INVOICE: bool = False
    REQUIRE_STAMP_FOR_INVOICE: bool = True
    REQUIRE_BARCODE_FOR_INVOICE: bool = False
    REQUIRE_MATERAI_ABOVE_THRESHOLD: bool = True
    DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT: int = 2
    DELIVERY_NOTE_REQUIRED_STAMP_COUNT: int = 2

    MAX_FILE_SIZE_MB: int = 25
    MIN_IMAGE_WIDTH: int = 800
    MIN_IMAGE_HEIGHT: int = 800
    MAX_PAGE_COUNT: int = 200


config = PipelineConfig()
