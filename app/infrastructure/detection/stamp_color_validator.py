import cv2
import numpy as np

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

SATURATION_THRESHOLD = 30
MIN_COLOR_PIXEL_RATIO = 0.15


class StampColorValidator:
    def validate(self, image_bytes: bytes, bbox: list[int] | None) -> dict:
        if not bbox or len(bbox) != 4:
            return {"stamp_color_valid": False, "reason": "No bounding box for color check", "color_ratio": 0.0}

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"stamp_color_valid": False, "reason": "Image decode failed", "color_ratio": 0.0}

        x1, y1, x2, y2 = bbox
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return {"stamp_color_valid": False, "reason": "Empty crop area", "color_ratio": 0.0}

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        total_pixels = saturation.size
        color_pixels = int(np.sum(saturation > SATURATION_THRESHOLD))
        color_ratio = color_pixels / total_pixels if total_pixels > 0 else 0.0

        is_valid = color_ratio >= MIN_COLOR_PIXEL_RATIO

        return {
            "stamp_color_valid": bool(is_valid),
            "color_ratio": round(color_ratio, 4),
            "saturation_threshold": SATURATION_THRESHOLD,
            "min_color_ratio": MIN_COLOR_PIXEL_RATIO,
        }
