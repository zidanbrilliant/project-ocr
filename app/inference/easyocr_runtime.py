import time
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import torch
import numpy as np

from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)

_GPU_AVAILABLE = torch.cuda.is_available()


class EasyOCRRuntime:
    """Single EasyOCR instance. GPU-safe: runs on 1 dedicated thread.

    Never use ProcessPoolExecutor with EasyOCR GPU — each child process
    initializes its own CUDA context (30-40s overhead, VRAM waste).
    """

    def __init__(self) -> None:
        self._reader: Any = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="easyocr-gpu")

    def load(self) -> None:
        started = time.perf_counter()
        import easyocr
        self._reader = easyocr.Reader(
            ["en"],
            gpu=_GPU_AVAILABLE,
            download_enabled=(config.OCR_ENGINE == "easyocr"),
        )
        elapsed = round(time.perf_counter() - started, 3)
        logger.info("easyocr_init_done", duration_seconds=elapsed, gpu=_GPU_AVAILABLE)

    def read(self, image_path: str) -> dict[str, Any]:
        if self._reader is None:
            raise RuntimeError("EasyOCR not loaded. Call load() first.")
        t0 = time.perf_counter()

        import cv2
        img = cv2.imread(image_path)
        if img is None:
            return {"status": "FAILED", "error": "image_read_failed", "full_text": "", "mean_confidence": 0.0}

        h, w = img.shape[:2]
        if max(w, h) > 1920:
            scale = 1920 / max(w, h)
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        results = self._reader.readtext(
            img,
            detail=1,
            paragraph=False,
            batch_size=config.EASYOCR_BATCH_SIZE if hasattr(config, 'EASYOCR_BATCH_SIZE') else 4,
            workers=0,
            canvas_size=2560,
        )

        lines = []
        confs = []
        blocks = []
        for bbox, text, conf in results:
            lines.append(text)
            confs.append(float(conf))
            blocks.append({
                "text": text,
                "confidence": round(float(conf), 4),
                "bbox": [float(bbox[0][0]), float(bbox[0][1]), float(bbox[2][0]), float(bbox[2][1])],
            })

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        mean_conf = round(sum(confs) / max(len(confs), 1), 4) if confs else 0.0
        return {
            "status": "SUCCESS",
            "language": ["en"],
            "mean_confidence": mean_conf,
            "full_text": "\n".join(lines),
            "blocks": blocks,
            "duration_ms": elapsed_ms,
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)
