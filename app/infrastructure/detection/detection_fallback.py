from typing import Any

from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class DetectionFallback:
    def __init__(self, yolo: YOLOAdapter) -> None:
        self._yolo = yolo

    async def run_with_fallback(self, image_bytes: bytes) -> list[dict[str, Any]]:
        detections = await self._yolo.detect(image_bytes)
        if self._has_any_detection(detections) is False:
            logger.info("detection_fallback_retry_larger_input")
            old_size = settings.YOLO_INPUT_SIZE
            settings.YOLO_INPUT_SIZE = 960
            detections = await self._yolo.detect(image_bytes)
            settings.YOLO_INPUT_SIZE = old_size

        return detections

    def _has_any_detection(self, detections: list[dict[str, Any]]) -> bool:
        return len(detections) > 0
