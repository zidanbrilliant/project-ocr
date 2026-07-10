import imghdr
import struct
from typing import Any

from app.shared.config.settings import settings
from app.shared.exceptions.base import DocumentError

PDF_MAGIC = b"%PDF"
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png"})
SUPPORTED_MIME = frozenset({"application/pdf", "image/jpeg", "image/png"})
MAX_FILE_SIZE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024


class DocumentValidator:
    def validate(self, content: bytes, filename: str) -> dict[str, Any]:
        ext = self._get_extension(filename)
        if ext not in SUPPORTED_EXTENSIONS:
            raise DocumentError("Unsupported document format.", {"extension": ext, "filename": filename})

        if len(content) == 0:
            raise DocumentError("File corrupt or unreadable.", {"filename": filename, "reason": "empty_file"})

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise DocumentError(
                "File size exceeds maximum limit.",
                {"filename": filename, "size": len(content), "max": MAX_FILE_SIZE_BYTES},
            )

        result: dict[str, Any] = {"extension": ext, "size_bytes": len(content), "readable": True}

        if ext == ".pdf":
            if not content.startswith(PDF_MAGIC):
                raise DocumentError("File corrupt or unreadable.", {"filename": filename, "reason": "invalid_pdf_magic"})
            result["page_count"] = self._count_pdf_pages(content)
            if result["page_count"] > settings.MAX_PAGE_COUNT:
                raise DocumentError(
                    "PDF page count exceeds maximum limit.",
                    {"filename": filename, "pages": result["page_count"], "max": settings.MAX_PAGE_COUNT},
                )
            if self._is_pdf_encrypted(content):
                raise DocumentError("PDF is password protected and cannot be processed.", {"filename": filename})
            result["content_type"] = "application/pdf"

        elif ext in (".jpg", ".jpeg"):
            img_type = imghdr.what(None, h=content)
            if img_type not in ("jpeg",):
                raise DocumentError("File corrupt or unreadable.", {"filename": filename, "reason": "invalid_jpeg"})
            result["content_type"] = "image/jpeg"
            result["page_count"] = 1
            result.update(self._get_image_dimensions(content))

        elif ext == ".png":
            img_type = imghdr.what(None, h=content)
            if img_type != "png":
                raise DocumentError("File corrupt or unreadable.", {"filename": filename, "reason": "invalid_png"})
            result["content_type"] = "image/png"
            result["page_count"] = 1
            result.update(self._get_image_dimensions(content))

        if result.get("image_width", 0) > 0 and result.get("image_height", 0) > 0:
            if result["image_width"] < settings.MIN_IMAGE_WIDTH or result["image_height"] < settings.MIN_IMAGE_HEIGHT:
                raise DocumentError(
                    "Document resolution is below minimum requirement.",
                    {"filename": filename, "width": result["image_width"], "height": result["image_height"]},
                )

        return result

    def _get_extension(self, filename: str) -> str:
        idx = filename.lower().rfind(".")
        if idx == -1:
            return ""
        return filename[idx:]

    def _count_pdf_pages(self, content: bytes) -> int:
        try:
            from pypdf import PdfReader
            import io
            return max(len(PdfReader(io.BytesIO(content)).pages), 1)
        except Exception:
            return 1

    def _is_pdf_encrypted(self, content: bytes) -> bool:
        return b"/Encrypt" in content[:4096]

    def _get_image_dimensions(self, content: bytes) -> dict[str, int]:
        if content[:2] == b"\xff\xd8":
            return self._jpeg_dimensions(content)
        if content[:8] == b"\x89PNG\r\n\x1a\n":
            return self._png_dimensions(content)
        return {}

    def _jpeg_dimensions(self, content: bytes) -> dict[str, int]:
        pos = 2
        while pos < len(content) - 1:
            if content[pos] != 0xFF:
                break
            marker = content[pos + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h = struct.unpack(">H", content[pos + 5 : pos + 7])[0]
                w = struct.unpack(">H", content[pos + 7 : pos + 9])[0]
                return {"image_width": w, "image_height": h}
            if marker == 0xD9:
                break
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
                pos += 2
            else:
                length = struct.unpack(">H", content[pos + 2 : pos + 4])[0]
                pos += 2 + length
        return {}

    def _png_dimensions(self, content: bytes) -> dict[str, int]:
        if len(content) < 24:
            return {}
        w = struct.unpack(">I", content[16:20])[0]
        h = struct.unpack(">I", content[20:24])[0]
        return {"image_width": w, "image_height": h}
