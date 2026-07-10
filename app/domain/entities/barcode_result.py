from dataclasses import dataclass


@dataclass
class BarcodeResult:
    page_number: int = 1
    required: bool = False
    barcode_found: bool = False
    barcode_decoded: bool = False
    result: str = "NG"
    barcode_value: str | None = None
    barcode_type: str | None = None
    barcode_confidence: float | None = None
    bounding_box: list[int] | None = None
    decoder_name: str | None = None
    reason: str | None = None
