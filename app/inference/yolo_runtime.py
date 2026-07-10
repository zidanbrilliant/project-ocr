import os
import time
from typing import Any

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)

_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class YoloRuntime:
    """Single YOLO model instance. Loaded once at startup."""

    def __init__(self) -> None:
        self._model: YOLO | None = None
        self._class_names: dict[int, str] = {}

    def load(self) -> None:
        _orig = torch.load
        torch.load = lambda *a, **kw: _orig(*a, **{**kw, "weights_only": False})
        self._model = YOLO(config.YOLO_MODEL_PATH)
        self._class_names = self._model.names
        logger.info("yolo_loaded", path=config.YOLO_MODEL_PATH, device=_DEVICE)

    def warmup(self) -> None:
        if self._model is None:
            self.load()
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        self._model.predict(dummy, device=_DEVICE, verbose=False)
        logger.info("yolo_warmup_done")

    def predict_batch(self, image_paths: list[str]) -> list[list[dict[str, Any]]]:
        if self._model is None:
            self.load()
        t0 = time.monotonic()
        results = self._model.predict(
            source=image_paths,
            imgsz=config.YOLO_INPUT_SIZE,
            conf=config.YOLO_CONFIDENCE_THRESHOLD,
            iou=config.YOLO_NMS_THRESHOLD,
            device=_DEVICE,
            verbose=False,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        all_pages: list[list[dict[str, Any]]] = []
        for r in results:
            page_dets: list[dict[str, Any]] = []
            if r.boxes is not None:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    page_dets.append({
                        "class_id": cls_id,
                        "label": self._class_names.get(cls_id, f"class_{cls_id}"),
                        "confidence": round(float(box.conf[0]), 4),
                        "bbox_pixel_xyxy": [int(c) for c in box.xyxy[0].tolist()],
                    })
            all_pages.append(page_dets)
        logger.info("yolo_batch_complete",
                     total_images=len(image_paths),
                     total_detections=sum(len(p) for p in all_pages),
                     duration_ms=elapsed_ms,
                     batch_size=len(image_paths))
        return all_pages

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
