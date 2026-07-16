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

    assert captured == {
        "pipeline_version": "v1.6",
        "engine": "transformers",
        "device": "gpu",
        "use_layout_detection": True,
        "format_block_content": True,
        "use_queues": True,
        "vl_rec_model_dir": str(tmp_path),
    }


def test_run_includes_structured_json(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakePrediction:
        def to_dict(self) -> dict[str, object]:
            return {
                "pages": [
                    {
                        "blocks": [
                            {
                                "text": "INV-001",
                                "confidence": 0.98,
                                "bbox": [1, 2, 3, 4],
                            }
                        ]
                    }
                ]
            }

    class FakePaddleOCRVL:
        def __init__(self, **kwargs: object) -> None:
            pass

        def predict(self, input: str) -> FakePrediction:  # noqa: A002
            return FakePrediction()

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
    result = asyncio.run(ocr.run(b"fake-image-bytes"))

    assert result["raw_text"] == "INV-001"
    assert result["structured_json"]["pages"][0]["blocks"][0]["text"] == "INV-001"


def test_run_supports_generator_results_with_json_dict(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakePrediction:
        json = {"pages": [{"blocks": [{"text": "INV-002", "score": 0.99}]}]}

    class FakePaddleOCRVL:
        def __init__(self, **kwargs: object) -> None:
            pass

        def predict(self, input: str):  # noqa: A002
            yield FakePrediction()

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
    result = asyncio.run(ocr.run(b"fake-image-bytes"))

    assert result["raw_text"] == "INV-002"
    assert result["average_confidence"] == 99.0
