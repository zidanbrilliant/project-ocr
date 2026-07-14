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

Fallback behaviour
------------------
  If vLLM is not installed *or* the model directory does not exist,
  _available stays False and every call to run() returns an empty result
  dict so that DocumentOCR can fall through to EasyOCR gracefully.
"""

from __future__ import annotations

import base64
import io
import os
import sys
import time
import types as _types
from typing import Any

import torch

from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

_HAS_CUDA = torch.cuda.is_available()

# ---------------------------------------------------------------------------
# Defensive guards — must run BEFORE any vLLM import
# ---------------------------------------------------------------------------

def _suppress_bad_torch_addons() -> None:  # noqa: C901
    """Prevent broken optional torch add-ons from crashing the vLLM import chain.

    WHY THIS IS NEEDED
    ------------------
    vLLM >= 0.6 checks optional packages in TWO separate ways:

        ① import torchcodec             — resolved via sys.modules
        ② importlib.metadata.version("torchcodec")  — reads dist-info on disk

    These are completely independent systems.  Stubbing sys.modules only
    fixes ①.  If the package is uninstalled (no dist-info on disk), ②
    raises PackageNotFoundError (subclass of ImportError) even when the
    sys.modules stub is in place — and since vLLM does not always catch
    that error internally, it propagates to our except ImportError block.

    THREE-LAYER FIX
    ---------------
    Layer 1 — sys.modules stub
        Pre-populate sys.modules with a fake module before vLLM imports it,
        so ``import torchcodec`` resolves without touching the filesystem.

    Layer 2 — valid __spec__ on every stub
        importlib.util.find_spec() raises ValueError if __spec__ is None.
        Use importlib.machinery.ModuleSpec(name, loader=None) instead of a
        bare types.ModuleType() to satisfy that contract.

    Layer 3 — importlib.metadata patch
        importlib.metadata.version(name) reads dist-info from disk; it has
        no knowledge of sys.modules.  We monkey-patch it to return "0.0.0"
        for packages we have stubbed, so vLLM's version checks pass cleanly.
    """
    import importlib.machinery
    import importlib.metadata as _imeta

    # ------------------------------------------------------------------ #
    # Track which packages we stub so Layer 3 knows what to intercept.
    # ------------------------------------------------------------------ #
    _stubbed: set[str] = set()

    def _make_stub(name: str) -> _types.ModuleType:
        """Return a ModuleType with a valid __spec__ (loader=None is legal)."""
        m = _types.ModuleType(name)
        m.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
        return m

    # ------------------------------------------------------------------ #
    # Layer 1 + 2 — sys.modules stubs with valid __spec__
    # ------------------------------------------------------------------ #

    # 1a. torchcodec — dlopen FFmpeg fails when FFmpeg is not installed
    if "torchcodec" not in sys.modules:
        try:
            import torchcodec  # type: ignore[import]  # noqa: F401
        except Exception:
            _root = _make_stub("torchcodec")
            for _sub in ("decoders", "decoders._core", "_internally_replaced_utils"):
                _full = f"torchcodec.{_sub}"
                _m = _make_stub(_full)
                sys.modules[_full] = _m
                setattr(_root, _sub.split(".")[0], _m)
            sys.modules["torchcodec"] = _root
            _stubbed.add("torchcodec")
            logger.debug("torchcodec_stubbed",
                         reason="FFmpeg shared libs not found; image-only mode")

    # 1b. torchaudio — CUDA version mismatch (cu12.8 vs cu13.0)
    # Fix pre-existing stub from an earlier import attempt with __spec__=None.
    _ta_existing = sys.modules.get("torchaudio")
    if _ta_existing is not None and getattr(_ta_existing, "__spec__", None) is None:
        _ta_existing.__spec__ = importlib.machinery.ModuleSpec("torchaudio", loader=None)
        _stubbed.add("torchaudio")
        logger.debug("torchaudio_spec_fixed",
                     reason="Patched pre-existing stub that had __spec__=None")

    if "torchaudio" not in sys.modules:
        try:
            import torchaudio  # type: ignore[import]  # noqa: F401
        except Exception:
            sys.modules["torchaudio"] = _make_stub("torchaudio")
            _stubbed.add("torchaudio")
            logger.debug("torchaudio_stubbed",
                         reason="CUDA version mismatch; not needed for OCR")

    # ------------------------------------------------------------------ #
    # Layer 3 — patch importlib.metadata.version() for stubbed packages
    #
    # sys.modules stub  →  fixes ``import torchcodec``
    # metadata patch    →  fixes ``importlib.metadata.version("torchcodec")``
    #
    # Without this, vLLM's internal version check raises:
    #   PackageNotFoundError: No package metadata was found for torchcodec
    # which is a subclass of ImportError and bubbles up to our warmup().
    # ------------------------------------------------------------------ #
    if _stubbed:
        _real_version = _imeta.version  # keep reference to original

        def _safe_version(dist_name: str, *args: Any, **kwargs: Any) -> str:
            if dist_name in _stubbed:
                return "0.0.0+stub"
            return _real_version(dist_name, *args, **kwargs)

        _imeta.version = _safe_version  # type: ignore[assignment]

        # Some vLLM versions also call importlib.metadata.packages_distributions()
        # or Distribution.from_name() — patch those too for robustness.
        _real_from_name = _imeta.Distribution.from_name

        @classmethod  # type: ignore[misc]
        def _safe_from_name(cls: Any, name: str) -> Any:  # type: ignore[override]
            if name in _stubbed:
                # Return a minimal Distribution-like object
                class _FakeDist:
                    metadata: dict = {"Name": name, "Version": "0.0.0+stub"}
                    name = dist_name if (dist_name := name) else name
                return _FakeDist()
            return _real_from_name.__func__(cls, name)  # type: ignore[attr-defined]

        _imeta.Distribution.from_name = _safe_from_name
        logger.debug("importlib_metadata_patched", stubbed=sorted(_stubbed))


_suppress_bad_torch_addons()


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
            logger.warning(
                "qwen_vl_skip_load",
                reason=self._load_error,
            )
            return

        if not os.path.isdir(model_path):
            self._load_error = f"Model directory not found: {model_path}"
            logger.warning(
                "qwen_vl_skip_load",
                reason=self._load_error,
            )
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
                # Limit GPU memory to leave headroom for YOLO + EasyOCR
                gpu_memory_utilization=0.70,
                max_model_len=4096,
                # Do NOT try to download anything from HuggingFace Hub
                download_dir=None,
            )

            if not _HAS_CUDA:
                # CPU fallback (very slow, for smoke-testing only)
                llm_kwargs.pop("quantization", None)
                llm_kwargs["device"] = "cpu"
                logger.warning("qwen_vl_cpu_mode", reason="No CUDA device detected")

            self._llm = LLM(**llm_kwargs)
            _llm_instance = self._llm
            self._available = True
            self._load_error = None
            logger.info("qwen_vl_loaded", gpu=_HAS_CUDA, backend="vllm", quant=quant)

        except ImportError as exc:
            self._load_error = f"ImportError: {str(exc)}"
            logger.warning(
                "qwen_vl_not_available",
                error=str(exc),
                hint="Run `pip install vllm>=0.7.2` in your (ocr) environment",
            )
        except Exception as exc:
            self._load_error = f"Exception: {str(exc)}"
            logger.warning("qwen_vl_load_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Public run interface (mirrors old AutoModel adapter)
    # ------------------------------------------------------------------
    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        return await self._run_qwen(image_bytes)

    async def _run_qwen(self, image_bytes: bytes) -> dict[str, Any]:
        if not self._available or self._llm is None:
            return {
                "engine_name": "qwen2.5-vl",
                "raw_text": "",
                "error": "model_not_loaded",
                "average_confidence": 0.0,
            }

        start = time.monotonic()

        try:
            from vllm import SamplingParams  # type: ignore[import]

            # ----------------------------------------------------------------
            # Build a Qwen2.5-VL chat prompt with the image embedded as
            # base64 data-URI so vLLM's vision pipeline can decode it.
            # ----------------------------------------------------------------
            b64 = base64.b64encode(image_bytes).decode("ascii")

            # Detect MIME type from magic bytes
            if image_bytes[:4] == b"%PDF":
                mime = "image/png"   # caller should have rasterised PDFs first
            elif image_bytes[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif image_bytes[:4] == b"\x89PNG":
                mime = "image/png"
            else:
                mime = "image/png"

            data_uri = f"data:{mime};base64,{b64}"

            prompt_text = (
                "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
                "<|im_start|>user\n"
                f"<|vision_start|><|image_pad|><|vision_end|>"
                "Extract ALL text from this document image exactly as written. "
                "Preserve the original layout order. Return only the extracted text, no explanations."
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
                "engine_name": "qwen2.5-vl",
                "raw_text": output_text,
                "tokens_json": tokens,
                "average_confidence": 95.0,
                "processing_time_ms": elapsed_ms,
            }

        except Exception:
            logger.exception("qwen_vl_inference_failed")
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "engine_name": "qwen2.5-vl",
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
