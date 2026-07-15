import time
from typing import Any

import numpy as np

from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class YOLOAdapter:
    def __init__(self) -> None:
        self._model = None
        self._loaded = False

    async def warmup(self) -> None:
        try:
            from ultralytics import YOLO
            self._model = YOLO(settings.YOLO_MODEL_PATH)
            self._class_names = self._model.names
            device = _get_device()
            _register_health("yolo", available=True, model=str(settings.YOLO_MODEL_PATH), device=device)
            logger.info("yolo_loaded", classes=dict(self._class_names), device=device)
            self._loaded = True
        except Exception as e:
            _register_health("yolo", available=False, error=str(e), model=str(settings.YOLO_MODEL_PATH))
            logger.warning("yolo_load_failed", error=str(e))
            self._loaded = False

    async def detect(self, image_bytes: bytes) -> list[dict[str, Any]]:
        return await self.detect_batch([image_bytes])

    async def detect_batch(self, image_bytes_list: list[bytes], input_size: int | None = None) -> list[dict[str, Any]]:
        if not self._loaded:
            return []

        try:
            import cv2
            imgs = []
            for b in image_bytes_list:
                arr = np.frombuffer(b, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    imgs.append(img)
            if not imgs:
                return []

            results = self._model.predict(
                imgs,
                imgsz=input_size or settings.YOLO_INPUT_SIZE,
                conf=settings.YOLO_CONFIDENCE_THRESHOLD,
                iou=settings.YOLO_NMS_THRESHOLD,
                device=_get_device(),
                verbose=False,
            )
            all_detections: list[dict[str, Any]] = []
            for page_idx, r in enumerate(results):
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    all_detections.append({
                        "object_type": self._class_names.get(cls_id, f"class_{cls_id}"),
                        "class_id": cls_id,
                        "page_number": page_idx + 1,
                        "confidence": round(float(box.conf[0]) * 100, 2),
                        "bounding_box": [int(c) for c in box.xyxy[0].tolist()],
                        "model_name": "yolo_doc",
                        "model_version": "sesi_4",
                    })
            return all_detections

        except Exception as e:
            logger.warning("yolo_detect_failed", error=str(e))
            return []


def _get_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
