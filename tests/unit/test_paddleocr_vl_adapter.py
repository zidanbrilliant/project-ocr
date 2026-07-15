import asyncio
import sys
import types

import pytest

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

from app.infrastructure.ocr import paddleocr_vl_adapter as adapter


def test_warmup_uses_vl_rec_model_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakePaddleOCRVL:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCRVL=FakePaddleOCRVL))
    monkeypatch.setattr(adapter.settings, "PADDLEOCR_VL_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(adapter, "_pipeline_instance", None)
    monkeypatch.setattr(
        adapter,
        "logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None),
    )

    ocr = adapter.PaddleOCRVLAdapter()
    asyncio.run(ocr.warmup())

    assert captured == {"vl_rec_model_dir": str(tmp_path)}
