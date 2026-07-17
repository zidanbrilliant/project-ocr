from __future__ import annotations

import os
import time
from typing import Any

from app.infrastructure.ocr.paddleocr_vl_adapter import PaddleOCRVLAdapter
from app.infrastructure.ocr.qwen_vl_adapter import QwenVLAdapter
from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


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

    def _selected_adapter(self) -> QwenVLAdapter | PaddleOCRVLAdapter | None:
        if self._provider == "qwen":
            return self._qwen
        if self._provider == "paddleocr_vl":
            return self._paddle
        return None

    def _provider_error(self) -> str:
        adapter = self._selected_adapter()
        if adapter is None:
            return f"unsupported_ocr_provider:{self._provider}"
        return adapter.load_error or "model_not_loaded"

    async def warmup(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        _register_health("document_ocr", available=True, provider=self._provider)

        if self._provider == "qwen":
            await self._qwen.warmup()
            if self._qwen.is_available:
                return
            raise RuntimeError(self._provider_error())

        if self._provider == "paddleocr_vl":
            await self._paddle.warmup()
            if self._paddle.is_available:
                return
            raise RuntimeError(self._provider_error())

        _register_health("document_ocr", available=False, error=f"Unsupported OCR_PROVIDER={self._provider}")
        logger.warning("unsupported_ocr_provider", provider=self._provider)
        raise RuntimeError(self._provider_error())

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
            if result.get("error") == "model_not_loaded":
                result["error"] = self._provider_error()
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
            "average_confidence": None,
            "processing_time_ms": int((time.monotonic() - start) * 1000),
        }

    def _extract_pdf_text(self, content: bytes) -> dict[str, Any]:
        if not content.startswith(b"%PDF"):
            return {"engine_name": "pypdf", "raw_text": "", "tokens_json": [], "average_confidence": None}

        try:
            pages = self.extract_pdf_pages(content)
            raw = "\n\n".join(page["raw_text"] for page in pages if page["raw_text"])
            tokens = [token for page in pages for token in page["tokens_json"]]
            return {
                "engine_name": "pymupdf",
                "raw_text": raw,
                "tokens_json": tokens,
                # Native PDF text has no statistical confidence. Completeness is
                # represented by text_layer_usable instead of a fabricated score.
                "average_confidence": None,
                "pages": pages,
            }
        except Exception as exc:
            logger.warning("pypdf_text_extract_failed", error=str(exc))
            return {
                "engine_name": "pypdf",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": None,
                "error": str(exc),
            }

    def extract_pdf_pages(self, content: bytes) -> list[dict[str, Any]]:
        """Extract native words and PDF-point boxes without losing page provenance."""
        import fitz

        pages: list[dict[str, Any]] = []
        with fitz.open(stream=content, filetype="pdf") as document:
            for page_index, page in enumerate(document):
                words = page.get_text("words", sort=True)
                tokens = [
                    {
                        "text": str(word[4]),
                        "confidence": None,
                        "page_number": page_index + 1,
                        "bbox": [float(word[0]), float(word[1]), float(word[2]), float(word[3])],
                        "coordinate_space": "pdf_points",
                        "reading_order": index,
                    }
                    for index, word in enumerate(words)
                    if len(word) > 4 and str(word[4]).strip()
                ]
                raw_text = page.get_text("text", sort=True).strip()
                pages.append(
                    {
                        "page_number": page_index + 1,
                        "raw_text": raw_text,
                        "tokens_json": tokens,
                        "text_layer_detected": bool(raw_text),
                        "text_layer_usable": _native_text_usable(raw_text),
                        "page_width_pt": float(page.rect.width),
                        "page_height_pt": float(page.rect.height),
                    }
                )
        return pages


def _native_text_usable(text: str) -> bool:
    compact = "".join(text.split())
    if len(compact) < 40:
        return False
    printable = sum(char.isprintable() for char in compact) / len(compact)
    alphanumeric = sum(char.isalnum() for char in compact) / len(compact)
    return printable >= 0.98 and alphanumeric >= 0.35 and "\ufffd" not in compact
