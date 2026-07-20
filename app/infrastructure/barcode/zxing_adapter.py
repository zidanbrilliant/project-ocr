import asyncio
import time
from typing import Any

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ZXingAdapter:
    def __init__(self) -> None:
        self._available = True

    async def read(self, image_bytes: bytes) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_sync, image_bytes)

    def _read_sync(self, image_bytes: bytes) -> dict[str, Any]:
        start = time.monotonic()
        try:
            import cv2
            import numpy as np
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "zxing-cpp", "error": "decode_failed"}

            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            from zxingcpp import read_barcodes
            results = read_barcodes(rgb)
            elapsed = int((time.monotonic() - start) * 1000)

            if not results:
                return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "zxing-cpp"}

            best = results[0]
            return {
                "barcode_found": True,
                "barcode_decoded": True,
                "barcode_value": best.text,
                "barcode_type": str(best.format),
                "barcode_confidence": 90.0,
                "bounding_box": [
                    best.position.top_left.x, best.position.top_left.y,
                    best.position.bottom_right.x, best.position.bottom_right.y,
                ] if hasattr(best, "position") and best.position else None,
                "decoder_name": "zxing-cpp",
                "processing_time_ms": elapsed,
            }

        except ImportError:
            self._available = False
            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "zxing-cpp", "error": "not_installed"}
        except Exception as e:
            logger.warning("zxing_read_failed", error=str(e))
            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "zxing-cpp", "error": str(e)}
