import asyncio
import time
from typing import Any

from PIL import Image
import io

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class PyzbarAdapter:
    async def read(self, image_bytes: bytes) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_sync, image_bytes)

    def _read_sync(self, image_bytes: bytes) -> dict[str, Any]:
        start = time.monotonic()
        try:
            from pyzbar.pyzbar import decode as zbar_decode
            pil_img = Image.open(io.BytesIO(image_bytes))
            results = zbar_decode(pil_img)
            elapsed = int((time.monotonic() - start) * 1000)

            if not results:
                return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "pyzbar"}

            best = results[0]
            return {
                "barcode_found": True,
                "barcode_decoded": True,
                "barcode_value": best.data.decode("utf-8", errors="replace"),
                "barcode_type": str(best.type),
                "barcode_confidence": 80.0,
                "bounding_box": [
                    best.rect.left, best.rect.top,
                    best.rect.left + best.rect.width, best.rect.top + best.rect.height,
                ] if best.rect else None,
                "decoder_name": "pyzbar",
                "processing_time_ms": elapsed,
            }

        except ImportError:
            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "pyzbar", "error": "not_installed"}
        except Exception as e:
            logger.warning("pyzbar_read_failed", error=str(e))
            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "pyzbar", "error": str(e)}
