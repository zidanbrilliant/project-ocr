import io
from typing import Any

import cv2
import numpy as np

from app.infrastructure.barcode.opencv_barcode_adapter import OpenCVBarcodeAdapter
from app.infrastructure.barcode.pyzbar_adapter import PyzbarAdapter
from app.infrastructure.barcode.zxing_adapter import ZXingAdapter
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class BarcodeFallbackChain:
    def __init__(
        self,
        primary: ZXingAdapter,
        fallback: PyzbarAdapter,
        last_resort: OpenCVBarcodeAdapter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._last_resort = last_resort
        self._preprocessor = ImagePreprocessor()

    async def read(self, image_bytes: bytes) -> dict[str, Any]:
        result = await self._primary.read(image_bytes)
        if result.get("barcode_decoded"):
            return result

        processed = self._preprocessor.preprocess_barcode(image_bytes)
        result = await self._primary.read(processed)
        if result.get("barcode_decoded"):
            return result

        if settings.ENABLE_BARCODE_FALLBACK:
            result = await self._fallback.read(processed)
            if result.get("barcode_decoded"):
                return result

            result = await self._last_resort.read(processed)
            if result.get("barcode_decoded"):
                return result

            result = await self._full_page_scan(image_bytes)
            if result.get("barcode_decoded"):
                return result

        return result

    async def _full_page_scan(self, image_bytes: bytes) -> dict[str, Any]:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"barcode_found": False, "barcode_decoded": False}

        h, w = img.shape[:2]
        best: dict[str, Any] = {"barcode_found": False, "barcode_decoded": False}

        for scale in [1.0, 2.0, 4.0]:
            if scale > 1:
                scaled = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
                _, buf = cv2.imencode(".png", scaled)
                scaled_bytes = buf.tobytes()
            else:
                scaled_bytes = image_bytes

            for decoder in [self._primary, self._fallback]:
                result = await decoder.read(scaled_bytes)
                if result.get("barcode_decoded"):
                    result["barcode_found"] = True
                    return result
                if result.get("barcode_found"):
                    best = result

        return best
