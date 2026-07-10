import os
import time
from typing import Any

import cv2
import numpy as np

from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)

_OCR_READER: Any = None


def init_ocr_worker() -> None:
    """CPU-only OCR worker. Called once per ProcessPoolExecutor worker.
    GPU EasyOCR is handled by EasyOCRRuntime (single thread, not process).
    """
    global _OCR_READER
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    if config.OCR_ENGINE == "easyocr":
        try:
            import easyocr
            _OCR_READER = easyocr.Reader(["en"], gpu=False)
            logger.info("ocr_worker_init", engine="easyocr_cpu", pid=os.getpid())
        except Exception:
            _OCR_READER = None
    else:
        try:
            import pytesseract
            _OCR_READER = pytesseract
            logger.info("ocr_worker_init", engine="tesseract", pid=os.getpid())
        except ImportError:
            _OCR_READER = None


def run_ocr(image_path: str) -> dict[str, Any]:
    """Run OCR on a single image file via process pool. CPU only."""
    global _OCR_READER
    t0 = time.perf_counter()

    img = cv2.imread(image_path)
    if img is None:
        return {"status": "FAILED", "error": "image_read_failed", "full_text": "", "mean_confidence": 0.0}

    if _OCR_READER is None:
        return {"status": "FAILED", "error": "ocr_not_available", "full_text": "", "mean_confidence": 0.0}

    if config.OCR_ENGINE == "easyocr":
        results = _OCR_READER.readtext(img, detail=1, paragraph=False)
        lines = [r[1] for r in results]
        confs = [float(r[2]) for r in results]
        blocks = [{"text": r[1], "confidence": round(float(r[2]), 4),
                    "bbox": [float(r[0][0][0]), float(r[0][0][1]), float(r[0][2][0]), float(r[0][2][1])]} for r in results]
        full_text = "\n".join(lines)
        mean_conf = round(sum(confs) / max(len(confs), 1), 4) if confs else 0.0
    else:
        full_text = _OCR_READER.image_to_string(img)
        mean_conf = 0.85
        blocks = []

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": "SUCCESS",
        "language": ["id", "en"],
        "mean_confidence": mean_conf,
        "full_text": full_text,
        "blocks": blocks,
        "duration_ms": elapsed_ms,
    }
