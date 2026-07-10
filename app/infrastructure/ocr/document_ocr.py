import io
import os
import time
from typing import Any

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import torch

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

_HAS_CUDA = torch.cuda.is_available()


class DocumentOCR:
    """Two-phase OCR: pypdf text extraction for PDFs → EasyOCR for images/scans."""

    def __init__(self) -> None:
        self._easyocr_reader = None

    async def warmup(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        import easyocr
        self._easyocr_reader = easyocr.Reader(["en"], gpu=_HAS_CUDA)
        if _HAS_CUDA:
            import torch
            logger.info("document_ocr_warmed_up", gpu=True, device=torch.cuda.get_device_name(0))
        else:
            logger.info("document_ocr_warmed_up", gpu=False)

    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        start = time.monotonic()

        if extension == ".pdf":
            result = self._extract_pdf_text(image_bytes)
            if result.get("raw_text", "").strip():
                elapsed = int((time.monotonic() - start) * 1000)
                result["processing_time_ms"] = elapsed
                logger.info("pdf_text_extracted", len=len(result["raw_text"]))
                return result

        result = await self._run_easyocr(image_bytes)
        elapsed = int((time.monotonic() - start) * 1000)
        result["processing_time_ms"] = elapsed
        return result

    def _extract_pdf_text(self, content: bytes) -> dict[str, Any]:
        if not content.startswith(b"%PDF"):
            return {"engine_name": "pypdf", "raw_text": "", "average_confidence": 0.0}
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            lines = []
            for page in reader.pages:
                text = page.extract_text() or ""
                lines.append(text)
            raw = "\n".join(lines)
            tokens = [{"text": l, "confidence": 95.0} for l in raw.split("\n") if l.strip()]
            return {
                "engine_name": "pypdf",
                "raw_text": raw,
                "tokens_json": tokens,
                "average_confidence": 95.0,
            }
        except Exception as e:
            logger.warning("pypdf_text_extract_failed", error=str(e))
            return {"engine_name": "pypdf", "raw_text": "", "average_confidence": 0.0}

    async def _run_easyocr(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes or len(image_bytes) < 100:
            return {"engine_name": "easyocr", "raw_text": "", "error": "empty_image", "average_confidence": 0.0}

        if self._easyocr_reader is None:
            raise RuntimeError("EasyOCR not loaded. Call warmup() first.")

        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            import cv2
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return {"engine_name": "easyocr", "raw_text": "", "error": "decode_failed", "average_confidence": 0.0}

            h, w = img.shape[:2]
            if max(w, h) > 1920:
                scale = 1920 / max(w, h)
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                logger.info("easyocr_resized", original=f"{w}x{h}", new=f"{img.shape[1]}x{img.shape[0]}")

            results = self._easyocr_reader.readtext(img)
            tokens = []
            lines = []
            confs = []
            for bbox, text, conf in results:
                tokens.append({
                    "text": text,
                    "confidence": round(conf * 100, 2),
                    "bbox": [float(bbox[0][0]), float(bbox[0][1]), float(bbox[2][0]), float(bbox[2][1])],
                })
                lines.append(text)
                confs.append(conf * 100)

            avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0
            return {
                "engine_name": "easyocr",
                "raw_text": "\n".join(lines),
                "tokens_json": tokens,
                "average_confidence": avg_conf,
            }
        except Exception as e:
            logger.exception("easyocr_failed")
            return {"engine_name": "easyocr", "raw_text": "", "error": str(e), "average_confidence": 0.0}
