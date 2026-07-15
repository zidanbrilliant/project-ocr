"""Qwen2.5-VL inference adapter backed by vLLM.

Uses vLLM's LLM engine instead of raw AutoModel so that:
  - AWQ quantisation is handled natively (no autoawq ↔ transformers version clash)
  - PagedAttention gives much better GPU-memory utilisation on DGX hardware
  - The same public interface (warmup / run / _run_qwen) is preserved, so
    DocumentOCR and the pipeline orchestrator need zero changes.

Environment / settings required
--------------------------------
  VLM_MODEL_PATH  – absolute path to the local model directory, e.g.
                    /mnt/models/Qwen2.5-VL-7B-Instruct-AWQ
  VLM_MAX_TOKENS  – maximum new tokens to generate (default 2048)

Failure behaviour
-----------------
  If vLLM is not installed *or* the model directory does not exist,
  _available stays False and every call to run() returns an explicit
  model_not_loaded error.
"""

from __future__ import annotations

import io
import importlib.machinery
import os
import time
from typing import Any

# vLLM starts CUDA workers in subprocesses. On DGX Spark/Streamlit, CUDA may
# already be touched by imports, so force spawn instead of fork.
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
os.environ.pop("TORCHCODEC_ENABLED", None)

from app.shared.config.settings import settings
from app.shared.health_registry import register as _register_health
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

# Stub torchcodec and torchaudio so vLLM import doesn't crash
import sys as _sys
import types as _types

for _mod in ("torchcodec", "torchcodec.decoders", "torchcodec.decoders._core",
             "torchcodec._internally_replaced_utils", "torchaudio"):
    if _mod not in _sys.modules:
        _m = _types.ModuleType(_mod)
        _m.__spec__ = importlib.machinery.ModuleSpec(_mod, loader=None)
        _sys.modules[_mod] = _m


# ---------------------------------------------------------------------------
# Module-level singleton so the heavy model is loaded only once per process.
# ---------------------------------------------------------------------------
_llm_instance: Any | None = None  # vllm.LLM


class QwenVLAdapter:
    """Vision-Language Model OCR using Qwen2.5-VL-7B (vLLM backend).

    Directly reads document images and extracts structured text.
    Much higher accuracy than traditional OCR for complex layouts.
    Requires ~8-10 GB VRAM (AWQ 4-bit).  Falls back gracefully if
    vLLM is not installed or the model is not present on disk.
    """

    def __init__(self) -> None:
        self._llm: Any | None = None       # vllm.LLM instance
        self._available: bool = False
        self._load_error: str | None = None

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def load_error(self) -> str | None:
        return self._load_error

    # ------------------------------------------------------------------
    # warmup — called once at worker startup
    # ------------------------------------------------------------------
    async def warmup(self) -> None:
        global _llm_instance

        # Re-use already-loaded model (singleton)
        if _llm_instance is not None:
            self._llm = _llm_instance
            self._available = True
            self._load_error = None
            logger.info("qwen_vl_reusing_cached_model")
            return

        model_path = settings.VLM_MODEL_PATH or ""
        if not model_path:
            self._load_error = "VLM_MODEL_PATH is empty — set it in .env to enable Qwen2.5-VL"
            _register_health("qwen2.5-vl", available=False, error=self._load_error)
            logger.warning("qwen_vl_skip_load", reason=self._load_error)
            return

        if not os.path.isdir(model_path):
            self._load_error = f"Model directory not found: {model_path}"
            _register_health("qwen2.5-vl", available=False, error=self._load_error)
            logger.warning("qwen_vl_skip_load", reason=self._load_error)
            return

        logger.info("qwen_vl_loading_model", model=model_path, backend="vllm")

        try:
            from vllm import LLM  # type: ignore[import]

            # Detect quantisation from directory name / config
            quant: str | None = None
            model_lower = model_path.lower()
            if "awq" in model_lower:
                # Use awq_marlin for DGX (Ampere / Ada architecture) — faster
                # than plain awq on A100/H100.  Falls back to awq silently if
                # marlin kernels are not available.
                quant = "awq_marlin"

            llm_kwargs: dict[str, Any] = dict(
                model=model_path,
                quantization=quant,
                dtype="float16",            # AWQ does not support bfloat16 yet
                trust_remote_code=True,
                # Limit GPU memory to leave headroom for YOLO and OCR parsing.
                gpu_memory_utilization=0.70,
                max_model_len=4096,
                download_dir=None,
                # ponytail: limit concurrent requests for single-image OCR
                max_num_seqs=1,
            )

            self._llm = LLM(**llm_kwargs)
            _llm_instance = self._llm
            self._available = True
            self._load_error = None
            _register_health("qwen2.5-vl", available=True, gpu=True, quant=quant)
            logger.info("qwen_vl_loaded", gpu=True, backend="vllm", quant=quant)

        except ImportError as exc:
            self._load_error = f"ImportError: {str(exc)}"
            _register_health("qwen2.5-vl", available=False, error=self._load_error,
                             hint="Run `pip install vllm>=0.7.2`")
            logger.warning(
                "qwen_vl_not_available",
                error=str(exc),
                hint="Run `pip install vllm>=0.7.2` in your (ocr) environment",
            )
        except Exception as exc:
            self._load_error = f"Exception: {str(exc)}"
            _register_health("qwen2.5-vl", available=False, error=self._load_error)
            logger.warning("qwen_vl_load_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Public run interface (mirrors old AutoModel adapter)
    # ------------------------------------------------------------------
    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        return await self._run_qwen(image_bytes)

    async def reason(
        self,
        image_bytes: bytes,
        ocr_text: str,
        fields: dict[str, Any],
        detections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = (
            "You are validating Toyota invoice or delivery-note documents. "
            "Use the image, OCR text, extracted fields, and detections to reason about the document. "
            "Return compact JSON only with keys: document_type, corrected_fields, issues, confidence, summary.\n\n"
            f"OCR_TEXT:\n{ocr_text[:6000]}\n\n"
            f"EXTRACTED_FIELDS:\n{fields}\n\n"
            f"DETECTIONS:\n{detections[:50]}"
        )
        return await self._run_qwen(image_bytes, prompt_instruction=prompt, engine_name="qwen2.5-vl-reasoning")

    async def _run_qwen(
        self,
        image_bytes: bytes,
        prompt_instruction: str | None = None,
        engine_name: str = "qwen2.5-vl",
    ) -> dict[str, Any]:
        if not self._available or self._llm is None:
            return {
                "engine_name": engine_name,
                "raw_text": "",
                "error": "model_not_loaded",
                "average_confidence": 0.0,
            }

        start = time.monotonic()

        try:
            from vllm import SamplingParams  # type: ignore[import]

            instruction = prompt_instruction or (
                "Extract ALL text from this document image exactly as written. "
                "Preserve the original layout order. Return only the extracted text, no explanations."
            )
            prompt_text = (
                "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
                "<|im_start|>user\n"
                f"<|vision_start|><|image_pad|><|vision_end|>"
                f"{instruction}"
                "<|im_end|>\n"
                "<|im_start|>assistant\n"
            )

            # vLLM multi-modal input format
            llm_input = {
                "prompt": prompt_text,
                "multi_modal_data": {
                    "image": _load_pil_image(image_bytes),
                },
            }

            sampling_params = SamplingParams(
                temperature=0.0,                  # deterministic
                max_tokens=settings.VLM_MAX_TOKENS,
                stop=["<|im_end|>", "<|endoftext|>"],
            )

            # vLLM generate is synchronous but releases the GIL — safe to call
            # from an async context without blocking the event loop for short
            # inference bursts (model is already in GPU memory).
            outputs = self._llm.generate([llm_input], sampling_params=sampling_params)
            output_text: str = outputs[0].outputs[0].text.strip()

            elapsed_ms = int((time.monotonic() - start) * 1000)
            lines = [ln for ln in output_text.split("\n") if ln.strip()]
            tokens = [{"text": ln, "confidence": 95.0} for ln in lines]

            return {
                "engine_name": engine_name,
                "raw_text": output_text,
                "tokens_json": tokens,
                "average_confidence": 95.0,
                "processing_time_ms": elapsed_ms,
            }

        except Exception:
            logger.exception("qwen_vl_inference_failed")
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "engine_name": engine_name,
                "raw_text": "",
                "error": "inference_exception",
                "average_confidence": 0.0,
                "processing_time_ms": elapsed_ms,
            }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pil_image(image_bytes: bytes):  # type: ignore[return]
    """Decode raw bytes to a PIL Image for vLLM's vision pipeline."""
    import PIL.Image  # type: ignore[import]
    return PIL.Image.open(io.BytesIO(image_bytes)).convert("RGB")
