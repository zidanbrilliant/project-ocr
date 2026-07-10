from typing import Any


class DetectionResultDTO:
    def __init__(self, data: dict[str, Any]) -> None:
        self.page_number: int = data.get("page_number", 1)
        self.object_type: str = data.get("object_type", "")
        self.confidence: float | None = data.get("confidence")
        self.bounding_box: list[int] | None = data.get("bounding_box")
        self.result: str = data.get("result", "NG")
        self.detected_colour: str | None = data.get("detected_colour")
