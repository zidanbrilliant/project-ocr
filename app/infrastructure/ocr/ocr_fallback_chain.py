from typing import Any

from app.infrastructure.ocr.document_ocr import DocumentOCR
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class OCRFallbackChain:
    """Single engine: DocumentOCR (fitz text → EasyOCR fallback)."""

    def __init__(self, primary: DocumentOCR) -> None:
        self._primary = primary

    async def run(self, image_bytes: bytes, preprocessed_bytes: bytes | None = None, extension: str = ".pdf") -> dict[str, Any]:
        try:
            result = await self._primary.run(image_bytes, extension=extension)
            logger.info("ocr_result", engine=result.get("engine_name"), conf=result.get("average_confidence"))
            return result
        except Exception as e:
            logger.error("ocr_failed", error=str(e))
            return {"engine_name": "document_ocr", "raw_text": "", "error": str(e), "average_confidence": 0.0}
