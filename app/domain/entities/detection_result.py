from dataclasses import dataclass
from typing import Any


@dataclass
class DetectionResult:
    page_number: int
    model_name: str
    model_version: str
    object_type: str
    result: str = "NG"
    required: bool = False
    confidence: float | None = None
    bounding_box: list[int] | None = None
    crop_uri: str | None = None
    detected_colour: str | None = None
    reason: str | None = None
    attributes: dict[str, Any] | None = None
