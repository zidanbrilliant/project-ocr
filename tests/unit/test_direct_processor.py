import asyncio
import sys
import types

import numpy as np
import pytest

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.SimpleNamespace()

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace()

from scripts import direct_processor as dp


def _png_bytes() -> bytes:
    assert cv2 is not None
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_pdf_text_falls_back_when_qwen_page_ocr_is_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp, "setup_logging", lambda: None)
    processor = dp.DirectProcessor()

    monkeypatch.setattr(processor, "_validator", types.SimpleNamespace(validate=lambda *args, **kwargs: {"extension": ".pdf", "size_bytes": 1, "page_count": 1}))
    monkeypatch.setattr(processor, "_pdf_renderer", types.SimpleNamespace(render=lambda *args, **kwargs: [_png_bytes()]))
    monkeypatch.setattr(processor, "_preprocessor", types.SimpleNamespace(preprocess=lambda image_bytes: image_bytes, compute_quality=lambda image_bytes: {"resolution_score": 100, "blur_score": 100, "brightness_score": 100, "page_readability_score": 100}))
    monkeypatch.setattr(processor, "_barcode_chain", types.SimpleNamespace(read=lambda *args, **kwargs: asyncio.sleep(0, result={"barcode_found": False, "barcode_decoded": False})))
    monkeypatch.setattr(processor, "_yolo", types.SimpleNamespace(detect_batch=lambda *args, **kwargs: asyncio.sleep(0, result=[]), load_error=None, last_detect_error=None))
    monkeypatch.setattr(processor, "_field_extractor", types.SimpleNamespace(extract_from_ocr=lambda *args, **kwargs: {}, extract_layout_aware=lambda *args, **kwargs: {}))
    monkeypatch.setattr(processor, "_rule_evaluator", types.SimpleNamespace(validate_invoice=lambda *args, **kwargs: types.SimpleNamespace(passed=False, return_status="NG", return_code="NG", failed_rules=[])))
    monkeypatch.setattr(processor, "_conf_scorer", types.SimpleNamespace(calculate=lambda *args, **kwargs: 0.0))
    monkeypatch.setattr(processor, "_remark", types.SimpleNamespace(generate=lambda *args, **kwargs: ""))
    monkeypatch.setattr(dp, "logger", types.SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None))

    class FakeOCR:
        async def run(self, image_bytes: bytes, extension: str = ".pdf") -> dict:
            if extension == ".pdf":
                return {
                    "engine_name": "pypdf",
                    "raw_text": "PDF TEXT",
                    "tokens_json": [{"text": "PDF TEXT", "confidence": 95.0}],
                    "average_confidence": 95.0,
                }
            return {
                "engine_name": "qwen2.5-vl",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": 0.0,
                "error": "empty_ocr_output",
            }

    processor._ocr = FakeOCR()

    result = asyncio.run(processor.process(b"%PDF-1.4 fake", "test.pdf", "INV"))

    assert result["ocr"]["raw_text"] == "PDF TEXT"
    assert result["ocr"].get("error") is None
