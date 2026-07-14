import os
import time
from typing import Any

import torch
import numpy as np

from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

_HAS_CUDA = torch.cuda.is_available()

# ponytail: single global model instance, loaded once at warmup
_model_instance = None
_processor_instance = None


class QwenVLAdapter:
    """Vision-Language Model OCR using Qwen2.5-VL-7B.

    Directly reads document images and extracts structured text.
    Much higher accuracy than traditional OCR for complex layouts.
    Requires ~16GB VRAM. Falls back gracefully if model not available.
    """

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._available = False

    async def warmup(self) -> None:
        global _model_instance, _processor_instance
        if _model_instance is not None and _processor_instance is not None:
            self._model = _model_instance
            self._processor = _processor_instance
            self._available = True
            logger.info("qwen_vl_reusing_cached_model")
            return

        try:
            from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
            from qwen_vl_utils import process_vision_info

            # ponytail: use local model path from settings, fallback to HuggingFace
            model_name = settings.VLM_MODEL_PATH or "Qwen/Qwen2.5-VL-7B-Instruct"
            logger.info("qwen_vl_loading_model", model=model_name, local=bool(settings.VLM_MODEL_PATH))

            load_kwargs = dict(
                pretrained_model_name_or_path=model_name,
                torch_dtype=torch.float16,
                device_map="cuda:0" if _HAS_CUDA else None,
            )
            if _HAS_CUDA:
                try:
                    import flash_attn  # noqa: F401
                    load_kwargs["attn_implementation"] = "flash_attention_2"
                except ImportError:
                    load_kwargs["attn_implementation"] = "sdpa"
                    logger.info("flash_attn_not_available_using_sdpa")

            if bool(settings.VLM_MODEL_PATH):
                load_kwargs["local_files_only"] = True
            load_kwargs["trust_remote_code"] = True
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(**load_kwargs)
            self._processor = AutoProcessor.from_pretrained(model_name)
            _model_instance = self._model
            _processor_instance = self._processor
            self._available = True
            logger.info("qwen_vl_loaded", gpu=_HAS_CUDA)

        except ImportError as e:
            logger.warning("qwen_vl_not_available", error=str(e))
        except Exception as e:
            logger.warning("qwen_vl_load_failed", error=str(e))

    async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict[str, Any]:
        return await self._run_qwen(image_bytes)

    async def _run_qwen(self, image_bytes: bytes) -> dict[str, Any]:
        if not self._available:
            return {"engine_name": "qwen2.5-vl", "raw_text": "", "error": "model_not_loaded", "average_confidence": 0.0}

        from qwen_vl_utils import process_vision_info
        start = time.monotonic()

        try:
            import PIL.Image
            import io
            image = PIL.Image.open(io.BytesIO(image_bytes))

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": (
                            "Extract ALL text from this document image exactly as written. "
                            "Preserve the original layout order. Return only the extracted text, no explanations."
                        )},
                    ],
                }
            ]

            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, _ = process_vision_info(messages)
            inputs = self._processor(
                text=[text],
                images=image_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self._model.device)

            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=settings.VLM_MAX_TOKENS,
                temperature=0.1,
                top_p=0.9,
                do_sample=False,
            )
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self._processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]

            elapsed_ms = int((time.monotonic() - start) * 1000)
            lines = [l for l in output_text.split("\n") if l.strip()]
            tokens = [{"text": l, "confidence": 95.0} for l in lines]

            return {
                "engine_name": "qwen2.5-vl",
                "raw_text": output_text,
                "tokens_json": tokens,
                "average_confidence": 95.0,
                "processing_time_ms": elapsed_ms,
            }

        except Exception as e:
            logger.exception("qwen_vl_inference_failed")
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "engine_name": "qwen2.5-vl", "raw_text": "",
                "error": str(e), "average_confidence": 0.0,
                "processing_time_ms": elapsed_ms,
            }
