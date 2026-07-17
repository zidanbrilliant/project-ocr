from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

_PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown><predict_no_text_in_pic>"
_model_instance: tuple[Any, Any, Any, Any] | None = None


class NemotronParseAdapter:
    def __init__(self) -> None:
        self._runtime: tuple[Any, Any, Any, Any] | None = None
        self._available = False
        self._load_error: str | None = None
        self._service_url = settings.NEMOTRON_SERVICE_URL.rstrip("/")
        self._inference_lock = asyncio.Lock()

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def load_error(self) -> str | None:
        return self._load_error

    async def warmup(self) -> None:
        global _model_instance

        if self._service_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{self._service_url}/api/v1/nemotron/health")
                    response.raise_for_status()
                self._available = True
                self._load_error = None
            except Exception as exc:
                self._available = False
                self._load_error = f"Remote service unavailable: {exc}"
            return

        if _model_instance is not None:
            self._runtime = _model_instance
            self._available = True
            self._load_error = None
            return

        model_dir = Path(settings.NEMOTRON_MODEL_DIR)
        if not model_dir.is_dir():
            self._load_error = f"Model directory not found: {model_dir}"
            _register_health("nemotron-parse", available=False, error=self._load_error)
            return

        try:
            import torch
            from transformers import AutoModel, AutoProcessor, GenerationConfig

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
            model = AutoModel.from_pretrained(
                model_dir,
                trust_remote_code=True,
                local_files_only=True,
                torch_dtype=dtype,
            ).to(device).eval()
            processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
            generation_config = GenerationConfig.from_pretrained(
                model_dir, trust_remote_code=True, local_files_only=True
            )
            postprocessing = _load_postprocessing(model_dir)
            self._runtime = (model, processor, generation_config, postprocessing)
            _model_instance = self._runtime
            self._available = True
            self._load_error = None
            _register_health("nemotron-parse", available=True, model_dir=str(model_dir), device=device)
            logger.info("nemotron_parse_loaded", model_dir=str(model_dir), device=device)
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            _register_health("nemotron-parse", available=False, error=self._load_error)
            logger.exception("nemotron_parse_load_failed")

    async def run(self, image_bytes: bytes, extension: str = ".png") -> dict[str, Any]:
        start = time.monotonic()
        if not image_bytes:
            return _error_result("empty_image", start)

        if self._service_url:
            try:
                async with httpx.AsyncClient(timeout=settings.PAGE_PROCESSING_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self._service_url}/api/v1/nemotron/run",
                        json={"image_b64": base64.b64encode(image_bytes).decode("ascii"), "extension": extension},
                    )
                if response.is_error:
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        detail = response.text
                    return _error_result(f"remote_http_{response.status_code}:{detail}", start)
                result = response.json()
                if not isinstance(result, dict):
                    return _error_result("unexpected_remote_response", start)
                return result
            except Exception as exc:
                logger.exception("nemotron_remote_inference_failed")
                return _error_result(f"remote_inference_error:{exc}", start)

        if not self._available or self._runtime is None:
            return _error_result(self._load_error or "model_not_loaded", start)

        try:
            async with self._inference_lock:
                result = await asyncio.to_thread(self._infer, image_bytes)
            result["processing_time_ms"] = int((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            logger.exception("nemotron_inference_failed")
            return _error_result(f"{type(exc).__name__}: {exc}", start)

    def _infer(self, image_bytes: bytes) -> dict[str, Any]:
        import torch
        from PIL import Image, ImageOps

        model, processor, generation_config, postprocessing = self._runtime  # type: ignore[misc]
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        inputs = processor(
            images=[image],
            text=_PROMPT,
            return_tensors="pt",
            add_special_tokens=False,
        ).to(model.device)
        with torch.inference_mode():
            outputs = model.generate(**inputs, generation_config=generation_config)
        generated = processor.batch_decode(outputs, skip_special_tokens=True)[0]
        classes, bboxes, texts = postprocessing.extract_classes_bboxes(generated)

        tokens: list[dict[str, Any]] = []
        for index, (label, bbox, text) in enumerate(zip(classes, bboxes, texts, strict=False)):
            clean_text = postprocessing.postprocess_text(
                text,
                cls=label,
                table_format="markdown",
                text_format="plain",
                blank_text_in_figures=False,
            )
            tokens.append(
                {
                    "text": clean_text,
                    "confidence": None,
                    "bbox": postprocessing.transform_bbox_to_original(bbox, image.width, image.height),
                    "label": label,
                    "reading_order": index,
                }
            )

        raw_text = "\n".join(str(token["text"]).strip() for token in tokens if str(token["text"]).strip())
        return {
            "engine_name": "nemotron-parse-v1.2",
            "raw_text": raw_text,
            "tokens_json": tokens,
            "average_confidence": None,
            "structured_json": {"blocks": tokens, "model_output": generated},
        }


def _load_postprocessing(model_dir: Path) -> Any:
    path = model_dir / "postprocessing.py"
    if not path.is_file():
        raise FileNotFoundError(f"Nemotron postprocessing file not found: {path}")
    if str(model_dir) not in sys.path:
        sys.path.insert(0, str(model_dir))
    spec = importlib.util.spec_from_file_location("nemotron_parse_postprocessing", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Nemotron postprocessing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _error_result(error: str, start: float) -> dict[str, Any]:
    return {
        "engine_name": "nemotron-parse-v1.2",
        "raw_text": "",
        "tokens_json": [],
        "average_confidence": None,
        "error": error,
        "processing_time_ms": int((time.monotonic() - start) * 1000),
    }
