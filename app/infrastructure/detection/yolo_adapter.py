from pathlib import Path
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
        self._load_error: str | None = None
        self._last_detect_error: str | None = None
        self._device = "cpu"

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def last_detect_error(self) -> str | None:
        return self._last_detect_error

    @property
    def device(self) -> str:
        return self._device

    async def warmup(self) -> None:
        try:
            from ultralytics import YOLO

            if not Path(settings.YOLO_MODEL_PATH).is_file():
                raise FileNotFoundError(f"YOLO model not found: {settings.YOLO_MODEL_PATH}")
            self._model = YOLO(settings.YOLO_MODEL_PATH)
            self._class_names = self._model.names
            self._device = _get_device()
            _register_health("yolo", available=True, model=str(settings.YOLO_MODEL_PATH), device=self._device)
            logger.info("yolo_loaded", classes=_class_map(self._class_names), device=self._device)
            self._loaded = True
            self._load_error = None
        except Exception as e:
            self._load_error = str(e)
            _register_health("yolo", available=False, error=str(e), model=str(settings.YOLO_MODEL_PATH))
            logger.warning("yolo_load_failed", error=str(e))
            self._loaded = False

    async def detect(self, image_bytes: bytes) -> list[dict[str, Any]]:
        return await self.detect_batch([image_bytes])

    async def detect_batch(self, image_bytes_list: list[bytes], input_size: int | None = None) -> list[dict[str, Any]]:
        if not self._loaded:
            return []

        batch_size = max(1, settings.YOLO_BATCH_SIZE)
        if len(image_bytes_list) > batch_size:
            detections: list[dict[str, Any]] = []
            for offset in range(0, len(image_bytes_list), batch_size):
                chunk = await self.detect_batch(image_bytes_list[offset : offset + batch_size], input_size)
                for detection in chunk:
                    detection["page_number"] += offset
                detections.extend(chunk)
            return detections

        try:
            self._last_detect_error = None
            import cv2

            imgs: list[np.ndarray] = []
            page_indexes: list[int] = []
            for page_idx, b in enumerate(image_bytes_list, start=1):
                arr = np.frombuffer(b, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    imgs.append(img)
                    page_indexes.append(page_idx)
                else:
                    logger.warning("yolo_page_decode_failed", page_number=page_idx)
            if not imgs:
                return []

            results = self._model.predict(
                imgs,
                imgsz=input_size or settings.YOLO_INPUT_SIZE,
                conf=settings.YOLO_CONFIDENCE_THRESHOLD,
                iou=settings.YOLO_NMS_THRESHOLD,
                device=self._device,
                verbose=False,
            )
            all_detections: list[dict[str, Any]] = []
            for result_idx, r in enumerate(results):
                if r.boxes is None:
                    continue
                page_number = page_indexes[result_idx]
                height, width = r.orig_shape
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    xyxy = [int(c) for c in box.xyxy[0].tolist()]
                    normalized = _normalized_box(box, xyxy, width, height)
                    all_detections.append(
                        {
                            "object_type": _class_name(self._class_names, cls_id),
                            "class_id": cls_id,
                            "page_number": page_number,
                            "confidence": round(float(box.conf[0]) * 100, 2),
                            "bounding_box": xyxy,
                            "normalized_bounding_box": normalized,
                            "page_width": width,
                            "page_height": height,
                            "threshold_used": settings.YOLO_CONFIDENCE_THRESHOLD,
                            "model_name": Path(settings.YOLO_MODEL_PATH).name,
                            "model_version": "sesi_4",
                        }
                    )
            return all_detections

        except Exception as e:
            self._last_detect_error = str(e)
            logger.warning("yolo_detect_failed", error=str(e))
            return []


def _get_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _class_map(names: Any) -> dict[int, str]:
    if isinstance(names, dict):
        return {int(key): str(value) for key, value in names.items()}
    return {index: str(value) for index, value in enumerate(names)}


def _class_name(names: Any, class_id: int) -> str:
    return _class_map(names).get(class_id, f"class_{class_id}")


def _normalized_box(box: Any, xyxy: list[int], width: int, height: int) -> list[float]:
    xyxyn = getattr(box, "xyxyn", None)
    if xyxyn is not None:
        return [round(float(value), 6) for value in xyxyn[0].tolist()]
    return [
        round(xyxy[0] / width, 6),
        round(xyxy[1] / height, 6),
        round(xyxy[2] / width, 6),
        round(xyxy[3] / height, 6),
    ]
