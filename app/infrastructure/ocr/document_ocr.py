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
    """Three-phase OCR: pypdf → PaddleOCR (lang=id) → EasyOCR fallback."""

    def __init__(self) -> None:
        self._paddle_reader = None
        self._easyocr_reader = None
        self._paddle_available = False

    async def warmup(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

        # Try PaddleOCR first (best accuracy for Indonesian docs)
        try:
            from paddleocr import PaddleOCR
            self._paddle_reader = PaddleOCR(
                use_angle_cls=True,
                lang="id",
                use_gpu=_HAS_CUDA,
                show_log=False,
            )
            self._paddle_available = True
            logger.info("document_ocr_warmed_up", engine="paddleocr", lang="id", gpu=_HAS_CUDA)
        except ImportError:
            logger.info("paddleocr_not_available_using_easyocr")
        except Exception as e:
            logger.warning("paddleocr_warmup_failed", error=str(e))

        # Always load EasyOCR as fallback
        import easyocr
        self._easyocr_reader = easyocr.Reader(["en", "id"], gpu=_HAS_CUDA)
        logger.info("easyocr_fallback_ready", gpu=_HAS_CUDA)

    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        start = time.monotonic()

        # Phase 1: For PDFs, try direct text extraction first
        if extension == ".pdf":
            result = self._extract_pdf_text(image_bytes)
            if result.get("raw_text", "").strip():
                result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
                logger.info("pdf_text_extracted", len=len(result["raw_text"]))
                return result

        # Phase 2: Try PaddleOCR (Indonesian model)
        if self._paddle_available:
            result = self._run_paddle(image_bytes)
            if result.get("raw_text", "").strip():
                result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
                return result

        # Phase 3: Fallback to EasyOCR
        result = self._run_easyocr(image_bytes)
        result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
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

    def _run_paddle(self, image_bytes: bytes) -> dict[str, Any]:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        import cv2
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"engine_name": "paddleocr", "raw_text": "", "error": "decode_failed", "average_confidence": 0.0}

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        result = self._paddle_reader.ocr(img_rgb, cls=True)

        if not result or result[0] is None:
            return {"engine_name": "paddleocr", "raw_text": "", "average_confidence": 0.0}

        lines = []
        tokens = []
        confs = []
        for line in result[0]:
            bbox, (text, conf) = line
            tokens.append({
                "text": text,
                "confidence": round(float(conf) * 100, 2),
                "bbox": [float(bbox[0][0]), float(bbox[0][1]), float(bbox[2][0]), float(bbox[2][1])],
            })
            lines.append(text)
            confs.append(float(conf) * 100)

        return {
            "engine_name": "paddleocr",
            "raw_text": "\n".join(lines),
            "tokens_json": tokens,
            "average_confidence": round(sum(confs) / max(len(confs), 1), 2),
        }

    def _run_easyocr(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes or len(image_bytes) < 100:
            return {"engine_name": "easyocr", "raw_text": "", "error": "empty_image", "average_confidence": 0.0}

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

            results = self._easyocr_reader.readtext(img)
            tokens = []
            lines = []
            confs = []
            for bbox, text, conf in results:
                tokens.append({
                    "text": text,
                    "confidence": round(float(conf) * 100, 2),
                    "bbox": [float(bbox[0][0]), float(bbox[0][1]), float(bbox[2][0]), float(bbox[2][1])],
                })
                lines.append(text)
                confs.append(conf * 100)

            avg_conf = round(sum(confs) / max(len(confs), 1), 2) if confs else 0.0
            return {
                "engine_name": "easyocr",
                "raw_text": "\n".join(lines),
                "tokens_json": tokens,
                "average_confidence": avg_conf,
            }
        except Exception as e:
            logger.exception("easyocr_failed")
            return {"engine_name": "easyocr", "raw_text": "", "error": str(e), "average_confidence": 0.0}
