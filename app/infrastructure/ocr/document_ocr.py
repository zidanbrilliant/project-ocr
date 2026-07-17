from __future__ import annotations

import os
import time
from typing import Any

from app.infrastructure.ocr.nemotron_parse_adapter import NemotronParseAdapter
from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class DocumentOCR:
    """Native PDF text extraction with Nemotron Parse for scanned pages."""

    def __init__(self) -> None:
        self._nemotron = NemotronParseAdapter()
        self._provider = "nemotron"

    def _provider_error(self) -> str:
        return self._nemotron.load_error or "model_not_loaded"

    async def warmup(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        _register_health("document_ocr", available=True, provider=self._provider)

        await self._nemotron.warmup()
        if not self._nemotron.is_available:
            _register_health("document_ocr", available=False, error=self._provider_error())
            raise RuntimeError(self._provider_error())

    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        start = time.monotonic()

        if extension == ".pdf" and settings.OCR_ENABLE_PDF_TEXT_EXTRACTION:
            result = self._extract_pdf_text(image_bytes)
            if result.get("raw_text", "").strip():
                result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
                logger.info("pdf_text_extracted", len=len(result["raw_text"]))
                return result

        result = await self._nemotron.run(image_bytes, extension=extension)
        result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
        return result

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
