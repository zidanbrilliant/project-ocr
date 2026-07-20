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

    async def read(self, image_bytes: bytes, candidate_boxes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        for cropped, offset in self._barcode_crops(image_bytes, candidate_boxes or []):
            result = await self._read_without_crops(cropped)
            if result.get("barcode_decoded"):
                return self._offset_bbox(result, offset)
        return await self._read_without_crops(image_bytes)

    async def _read_without_crops(self, image_bytes: bytes) -> dict[str, Any]:
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

    @staticmethod
    def _barcode_crops(image_bytes: bytes, detections: list[dict[str, Any]]):
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return
        height, width = image.shape[:2]
        for detection in detections:
            if detection.get("object_type") != "barcode":
                continue
            box = detection.get("bounding_box")
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            x1, y1, x2, y2 = (max(0, int(value)) for value in box)
            x2, y2 = min(x2, width), min(y2, height)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            ok, encoded = cv2.imencode(".png", image[y1:y2, x1:x2])
            if ok:
                yield encoded.tobytes(), (x1, y1)

    @staticmethod
    def _offset_bbox(result: dict[str, Any], offset: tuple[int, int]) -> dict[str, Any]:
        adjusted = dict(result)
        if result.get("bounding_box"):
            x1, y1 = offset
            adjusted["bounding_box"] = [
                int(result["bounding_box"][0]) + x1,
                int(result["bounding_box"][1]) + y1,
                int(result["bounding_box"][2]) + x1,
                int(result["bounding_box"][3]) + y1,
            ]
        adjusted["decode_region"] = "yolo_barcode_crop"
        return adjusted

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
                    return self._rescale_bbox(result, scale)
                if result.get("barcode_found"):
                    best = self._rescale_bbox(result, scale)

        return best

    @staticmethod
    def _rescale_bbox(result: dict[str, Any], scale: float) -> dict[str, Any]:
        if scale == 1.0 or not result.get("bounding_box"):
            return result
        adjusted = dict(result)
        adjusted["bounding_box"] = [round(float(value) / scale) for value in result["bounding_box"]]
        return adjusted
