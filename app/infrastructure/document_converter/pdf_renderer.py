from collections.abc import Iterator

import fitz

from app.shared.config.settings import settings
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class PDFRenderer:
    """Render PDF pages to PNG images using PyMuPDF (fitz)."""

    def __init__(self, dpi: int | None = None) -> None:
        self._dpi = dpi or settings.PDF_DEFAULT_DPI

    def iter_batches(self, content: bytes, batch_size: int | None = None) -> Iterator[list[bytes]]:
        """Render bounded page batches so production never retains a whole PDF."""
        size = max(1, batch_size or settings.PAGE_MICRO_BATCH_SIZE)
        try:
            with fitz.open(stream=content, filetype="pdf") as doc:
                page_count = len(doc)
                if page_count == 0:
                    raise DocumentError("PDF has no pages")
                if page_count > settings.MAX_PAGE_COUNT:
                    raise DocumentError(
                        "PDF page count exceeds maximum limit.",
                        {"pages": page_count, "max": settings.MAX_PAGE_COUNT},
                    )
                matrix = fitz.Matrix(self._dpi / 72, self._dpi / 72)
                batch: list[bytes] = []
                for page in doc:
                    pix = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
                    batch.append(pix.tobytes("png"))
                    if len(batch) == size:
                        yield batch
                        batch = []
                if batch:
                    yield batch
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError(f"PDF render failed: {exc}") from exc

    def render(self, content: bytes) -> list[bytes]:
        images = [image for batch in self.iter_batches(content) for image in batch]
        logger.info("pdf_rendered", pages=len(images), dpi=self._dpi)
        return images
