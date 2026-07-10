from typing import Any


class OCRResultDTO:
    def __init__(self, data: dict[str, Any]) -> None:
        self.engine_name: str = data.get("engine_name", "")
        self.raw_text: str | None = data.get("raw_text")
        self.tokens_json: list[dict[str, Any]] | None = data.get("tokens_json")
        self.fields_json: dict[str, Any] | None = data.get("fields_json")
        self.average_confidence: float | None = data.get("average_confidence")
        self.invoice_number: str | None = data.get("invoice_number")
        self.billing_number: str | None = data.get("billing_number")
        self.transaction_amount: float | None = data.get("transaction_amount")
        self.invoice_confidence: float | None = data.get("invoice_confidence")
        self.billing_confidence: float | None = data.get("billing_confidence")
        self.amount_confidence: float | None = data.get("amount_confidence")
