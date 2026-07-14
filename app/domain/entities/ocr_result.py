from dataclasses import dataclass, field
from typing import Any


@dataclass
class OCRResult:
    page_number: int = 1
    engine_name: str = "paddleocr"
    engine_version: str | None = None
    raw_text: str | None = None
    tokens_json: list[dict[str, Any]] | None = None
    fields_json: dict[str, Any] | None = None
    average_confidence: float | None = None
    processing_time_ms: int | None = None
    invoice_number: str | None = None
    billing_number: str | None = None
    transaction_amount: float | None = None
    vendor_name: str | None = None
    transaction_date: str | None = None
    transaction_time: str | None = None
    invoice_confidence: float | None = None
    billing_confidence: float | None = None
    amount_confidence: float | None = None
