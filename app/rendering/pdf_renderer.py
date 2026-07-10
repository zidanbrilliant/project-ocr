import os
import time
from typing import Any

from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF"


def inspect_pdf(file_path: str) -> dict[str, Any]:
    """Inspect PDF metadata without full render."""
    if not os.path.exists(file_path):
        return {"status": "FAILED", "error": "file_not_found"}
    try:
        import fitz
        doc = fitz.open(file_path)
        info = {
            "status": "SUCCESS",
            "page_count": doc.page_count,
            "has_text_layer": False,
            "pages": [],
        }
        for i in range(min(doc.page_count, 5)):
            page = doc.load_page(i)
            text = page.get_text("text").strip()
            if text:
                info["has_text_layer"] = True
            info["pages"].append({
                "page_index": i,
                "page_number": i + 1,
                "page_width_pt": page.rect.width,
                "page_height_pt": page.rect.height,
                "rotation": page.rotation or 0,
                "has_text": bool(text),
            })
        doc.close()
        return info
    except Exception as e:
        return {"status": "FAILED", "error": str(e)}


def render_page(args: dict) -> dict[str, Any]:
    """Render a single PDF page to PNG. Runs in ProcessPoolExecutor."""
    file_path = args["file_path"]
    page_index = args["page_index"]
    document_id = args["document_id"]
    output_dir = args["output_dir"]
    dpi = args.get("dpi", config.PDF_DEFAULT_DPI)

    t0 = time.monotonic()
    try:
        import fitz
        doc = fitz.open(file_path)
        page = doc.load_page(page_index)
        page_width_pt = page.rect.width
        page_height_pt = page.rect.height
        rotation = page.rotation or 0

        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)

        page_number = page_index + 1
        filename = f"{document_id}_page_{page_number:05d}.png"
        output_path = os.path.join(output_dir, filename)
        pix.save(output_path)

        doc.close()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "status": "SUCCESS",
            "document_id": document_id,
            "page_index": page_index,
            "page_number": page_number,
            "image_path": output_path,
            "image_width": pix.width,
            "image_height": pix.height,
            "dpi": dpi,
            "rotation": rotation,
            "page_width_pt": page_width_pt,
            "page_height_pt": page_height_pt,
            "duration_ms": elapsed_ms,
        }
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e),
            "document_id": document_id,
            "page_index": page_index,
            "page_number": page_index + 1,
        }
