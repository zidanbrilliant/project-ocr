from __future__ import annotations

import io
import os
import time
from typing import Any

from app.infrastructure.ocr.paddleocr_vl_adapter import PaddleOCRVLAdapter
from app.infrastructure.ocr.qwen_vl_adapter import QwenVLAdapter
from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

try:
    import torch

    _HAS_CUDA = torch.cuda.is_available()
except ImportError:
    _HAS_CUDA = False


class DocumentOCR:
    """Document OCR with explicit provider selection.

    Set OCR_PROVIDER to:
      - qwen: use Qwen2.5-VL for page OCR.
      - paddleocr_vl: use PaddleOCR-VL for page OCR.

    EasyOCR is intentionally not used. If the selected provider is unavailable,
    the caller receives a clear OCR error instead of a silent fallback.
    """

    def __init__(self) -> None:
        self._qwen = QwenVLAdapter()
        self._paddle = PaddleOCRVLAdapter()
        self._provider = settings.OCR_PROVIDER

    async def warmup(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        _register_health("document_ocr", available=True, provider=self._provider, gpu=_HAS_CUDA)

        if self._provider == "qwen":
            await self._qwen.warmup()
            return

        if self._provider == "paddleocr_vl":
            await self._paddle.warmup()
            return

        _register_health("document_ocr", available=False, error=f"Unsupported OCR_PROVIDER={self._provider}")
        logger.warning("unsupported_ocr_provider", provider=self._provider)

    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        start = time.monotonic()

        if extension == ".pdf" and settings.OCR_ENABLE_PDF_TEXT_EXTRACTION:
            result = self._extract_pdf_text(image_bytes)
            if result.get("raw_text", "").strip():
                result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
                logger.info("pdf_text_extracted", len=len(result["raw_text"]))
                return result

        if self._provider == "qwen":
            result = await self._qwen.run(image_bytes)
            result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
            return result

        if self._provider == "paddleocr_vl":
            result = await self._paddle.run(image_bytes, extension=extension)
            result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
            return result

        return {
            "engine_name": "none",
            "raw_text": "",
            "tokens_json": [],
            "error": f"unsupported_ocr_provider:{self._provider}",
            "average_confidence": 0.0,
            "processing_time_ms": int((time.monotonic() - start) * 1000),
        }

    def _extract_pdf_text(self, content: bytes) -> dict[str, Any]:
        if not content.startswith(b"%PDF"):
            return {"engine_name": "pypdf", "raw_text": "", "tokens_json": [], "average_confidence": 0.0}

        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            lines = []
            for page in reader.pages:
                lines.append(page.extract_text() or "")

            raw = "\n".join(lines)
            tokens = [{"text": line, "confidence": 95.0} for line in raw.split("\n") if line.strip()]
            return {
                "engine_name": "pypdf",
                "raw_text": raw,
                "tokens_json": tokens,
                "average_confidence": 95.0 if raw.strip() else 0.0,
            }
        except Exception as exc:
            logger.warning("pypdf_text_extract_failed", error=str(exc))
            return {
                "engine_name": "pypdf",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": 0.0,
                "error": str(exc),
            }
