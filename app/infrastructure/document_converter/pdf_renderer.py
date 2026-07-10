import io
from typing import Any

import fitz

from app.shared.config.settings import settings
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class PDFRenderer:
    """Render PDF pages to PNG images using PyMuPDF (fitz)."""

    def __init__(self, dpi: int = 200) -> None:
        self._dpi = dpi

    def render(self, content: bytes) -> list[bytes]:
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            page_count = min(len(doc), settings.MAX_PAGE_COUNT)
            if page_count == 0:
                doc.close()
                raise DocumentError("PDF has no pages")

            matrix = fitz.Matrix(self._dpi / 72, self._dpi / 72)
            images: list[bytes] = []
            for i in range(page_count):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)

            doc.close()
            logger.info("pdf_rendered", pages=len(images), dpi=self._dpi)
            return images

        except DocumentError:
            raise
        except Exception as e:
            raise DocumentError(f"PDF render failed: {e}")
