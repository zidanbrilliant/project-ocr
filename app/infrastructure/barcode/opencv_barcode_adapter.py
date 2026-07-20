import asyncio
import time
from typing import Any

import cv2
import numpy as np

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class OpenCVBarcodeAdapter:
    async def read(self, image_bytes: bytes) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_sync, image_bytes)

    def _read_sync(self, image_bytes: bytes) -> dict[str, Any]:
        start = time.monotonic()
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "opencv"}

            barcode_detector = cv2.barcode.BarcodeDetector()
            ret = barcode_detector.detectAndDecode(img)
            elapsed = int((time.monotonic() - start) * 1000)

            if isinstance(ret, tuple) and len(ret) == 4:
                ok, decoded_info, decoded_type, points = ret
            elif isinstance(ret, tuple) and len(ret) == 3:
                ok, decoded_info, points = ret
                decoded_type = ["UNKNOWN"]
            else:
                ok = False
                decoded_info = None
                decoded_type = None
                points = None

            if ok and decoded_info and any(decoded_info):
                bbox = None
                if points is not None and len(points) > 0:
                    pts = points[0]
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

                return {
                    "barcode_found": True,
                    "barcode_decoded": True,
                    "barcode_value": decoded_info[0] if isinstance(decoded_info, list) else str(decoded_info),
                    "barcode_type": str(decoded_type[0]) if isinstance(decoded_type, list) else str(decoded_type),
                    "barcode_confidence": 70.0,
                    "bounding_box": bbox,
                    "decoder_name": "opencv",
                    "processing_time_ms": elapsed,
                }

            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "opencv", "processing_time_ms": elapsed}

        except Exception as e:
            logger.warning("opencv_barcode_failed", error=str(e))
            return {"barcode_found": False, "barcode_decoded": False, "decoder_name": "opencv", "error": str(e)}
