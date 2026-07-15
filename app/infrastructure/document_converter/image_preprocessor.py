import io
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ImagePreprocessor:
    def preprocess(self, image_bytes: bytes) -> bytes:
        img = self._load_image(image_bytes)
        img = self._denoise(img)
        img = self._sharpen(img)
        img = self._deskew(img)
        return self._to_bytes(img)

    def preprocess_barcode(self, image_bytes: bytes) -> bytes:
        img = self._load_image(image_bytes)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = self._sharpen(gray)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return self._to_bytes(cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR))

    def compute_quality(self, image_bytes: bytes) -> dict[str, Any]:
        img = self._load_image(image_bytes)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = img.shape[:2]

        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = min(100, max(0, laplacian_var * 2))

        brightness = gray.mean()
        brightness_score = 100 - abs(128 - brightness) / 1.28

        resolution_score = min(100, (w * h) / (1920 * 1080) * 100)

        page_readability = (blur_score * 0.5 + brightness_score * 0.3 + resolution_score * 0.2)

        return {
            "resolution_score": round(min(100, resolution_score), 2),
            "blur_score": round(min(100, blur_score), 2),
            "brightness_score": round(min(100, brightness_score), 2),
            "page_readability_score": round(min(100, page_readability), 2),
            "width": w,
            "height": h,
        }

    def _load_image(self, image_bytes: bytes) -> np.ndarray:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            pil_img = Image.open(io.BytesIO(image_bytes))
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img

    def _denoise(self, img: np.ndarray) -> np.ndarray:
        return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

    def _sharpen(self, img: np.ndarray) -> np.ndarray:
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        return cv2.filter2D(img, -1, kernel)

    def _deskew(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bitwise_not(gray)
        coords = np.column_stack(np.where(gray > 0))
        if len(coords) == 0:
            return img
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.5:
            return img
        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rotated

    def _to_bytes(self, img: np.ndarray) -> bytes:
        _, buf = cv2.imencode(".png", img)
        return buf.tobytes()
