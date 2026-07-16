from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

_pipeline_instance: Any | None = None


class PaddleOCRVLAdapter:
    """Local PaddleOCR-VL document parser.

    This adapter intentionally loads PaddleOCR lazily. The project can still run
    API/RabbitMQ code without the heavy Paddle dependencies installed, while the
    DGX testing runtime can enable it with OCR_PROVIDER=paddleocr_vl.
    """

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._available = False
        self._load_error: str | None = None

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def load_error(self) -> str | None:
        return self._load_error

    async def warmup(self) -> None:
        global _pipeline_instance

        if _pipeline_instance is not None:
            self._pipeline = _pipeline_instance
            self._available = True
            self._load_error = None
            _register_health("paddleocr-vl", available=True, cached=True)
            return

        model_dir = settings.PADDLEOCR_VL_MODEL_DIR
        if not model_dir:
            self._load_error = "PADDLEOCR_VL_MODEL_DIR is empty"
            _register_health("paddleocr-vl", available=False, error=self._load_error)
            return

        if not Path(model_dir).is_dir():
            self._load_error = f"Model directory not found: {model_dir}"
            _register_health("paddleocr-vl", available=False, error=self._load_error)
            return

        try:
            from paddleocr import PaddleOCRVL  # type: ignore[import]

            pipeline = self._create_pipeline(PaddleOCRVL, model_dir)

            self._pipeline = pipeline
            _pipeline_instance = pipeline
            self._available = True
            self._load_error = None
            _register_health("paddleocr-vl", available=True, model_dir=model_dir)
            logger.info("paddleocr_vl_loaded", model_dir=model_dir)
        except ImportError as exc:
            self._load_error = f"ImportError: {exc}"
            _register_health(
                "paddleocr-vl",
                available=False,
                error=self._load_error,
                hint="Install paddleocr[doc-parser]>=3.0.0 in the OCR runtime, then set OCR_PROVIDER=paddleocr_vl",
            )
            logger.warning("paddleocr_vl_import_failed", error=str(exc))
        except Exception as exc:
            self._load_error = f"Exception: {exc}"
            _register_health("paddleocr-vl", available=False, error=self._load_error)
            logger.warning("paddleocr_vl_load_failed", error=str(exc))

    def _create_pipeline(self, paddle_ocr_vl: Any, model_dir: str) -> Any:
        # Prefer the full documented v1.6 pipeline. Fall back to the legacy
        # constructor signature if the installed package predates these kwargs.
        kwargs = {
            "pipeline_version": settings.PADDLEOCR_VL_PIPELINE_VERSION,
            "engine": settings.PADDLEOCR_VL_ENGINE,
            "device": settings.PADDLEOCR_VL_DEVICE,
            "use_layout_detection": settings.PADDLEOCR_VL_USE_LAYOUT_DETECTION,
            "format_block_content": settings.PADDLEOCR_VL_FORMAT_BLOCK_CONTENT,
            "use_queues": settings.PADDLEOCR_VL_USE_QUEUES,
            "vl_rec_model_dir": model_dir,
        }

        try:
            return paddle_ocr_vl(**kwargs)
        except TypeError:
            pass

        fallback_kwargs = {
            "vl_rec_model_dir": model_dir,
        }

        try:
            return paddle_ocr_vl(**fallback_kwargs)
        except TypeError:
            return paddle_ocr_vl(model_dir)

    async def run(self, image_bytes: bytes, extension: str = ".png") -> dict[str, Any]:
        start = time.monotonic()
        if not self._available or self._pipeline is None:
            return {
                "engine_name": "paddleocr-vl",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": 0.0,
                "error": self._load_error or "model_not_loaded",
                "processing_time_ms": 0,
            }

        suffix = extension if extension.startswith(".") else f".{extension}"
        if suffix.lower() == ".pdf":
            suffix = ".png"

        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)

            try:
                prediction = self._pipeline.predict(input=str(tmp_path))
            finally:
                tmp_path.unlink(missing_ok=True)

            parsed = _parse_paddle_prediction(prediction)
            structured = _to_plain_data(prediction)
            if structured is not None:
                parsed["structured_json"] = structured
            parsed["processing_time_ms"] = int((time.monotonic() - start) * 1000)
            return parsed
        except Exception as exc:
            logger.exception("paddleocr_vl_inference_failed")
            return {
                "engine_name": "paddleocr-vl",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": 0.0,
                "error": str(exc),
                "processing_time_ms": int((time.monotonic() - start) * 1000),
            }


def _parse_paddle_prediction(prediction: Any) -> dict[str, Any]:
    items = prediction if isinstance(prediction, list) else [prediction]
    tokens: list[dict[str, Any]] = []
    lines: list[str] = []
    confidences: list[float] = []

    for item in items:
        data = _to_plain_data(item)
        _collect_text(data, tokens, lines, confidences)

    raw_text = "\n".join(line for line in lines if line.strip())
    average = round(sum(confidences) / len(confidences), 2) if confidences else (95.0 if raw_text else 0.0)
    return {
        "engine_name": "paddleocr-vl",
        "raw_text": raw_text,
        "tokens_json": tokens,
        "average_confidence": average,
    }


def _to_plain_data(item: Any) -> Any:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if hasattr(item, "json"):
        try:
            return json.loads(item.json())
        except Exception:
            return item.json()
    if isinstance(item, (dict, list, str, int, float, bool)) or item is None:
        return item
    return getattr(item, "__dict__", str(item))


def _collect_text(data: Any, tokens: list[dict[str, Any]], lines: list[str], confidences: list[float]) -> None:
    if isinstance(data, dict):
        text = data.get("text") or data.get("content") or data.get("rec_text") or data.get("transcription")
        if isinstance(text, str) and text.strip():
            confidence = _extract_confidence(data)
            token = {"text": text.strip(), "confidence": confidence}
            bbox = data.get("bbox") or data.get("box") or data.get("coordinate")
            if bbox is not None:
                token["bbox"] = bbox
            tokens.append(token)
            lines.append(text.strip())
            confidences.append(confidence)

        for value in data.values():
            if isinstance(value, (dict, list)):
                _collect_text(value, tokens, lines, confidences)
    elif isinstance(data, list):
        for value in data:
            _collect_text(value, tokens, lines, confidences)
    elif isinstance(data, str) and data.strip():
        stripped = data.strip()
        if len(stripped) > 1:
            tokens.append({"text": stripped, "confidence": 95.0})
            lines.append(stripped)
            confidences.append(95.0)


def _extract_confidence(data: dict[str, Any]) -> float:
    for key in ("confidence", "score", "rec_score", "prob"):
        value = data.get(key)
        if value is None:
            continue
        try:
            score = float(value)
            return round(score * 100, 2) if score <= 1 else round(score, 2)
        except (TypeError, ValueError):
            continue
    return 95.0
