import asyncio
import base64
import sys
import types

import pytest

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.SimpleNamespace(
        frombuffer=lambda data, *args, **kwargs: data,
        uint8=object(),
        ndarray=object,
    )

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

from app.infrastructure.detection.yolo_adapter import YOLOAdapter

_SMALL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7nQAAAAASUVORK5CYII=",
)


def test_detection_keeps_original_page_number_and_normalized_box(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.detection import yolo_adapter

    sys.modules["cv2"] = types.SimpleNamespace(
        IMREAD_COLOR=1,
        imdecode=lambda arr, flag: object() if arr != b"broken" else None,
    )

    class FakeBox:
        cls = [3]
        conf = [0.9]
        xyxy = [types.SimpleNamespace(tolist=lambda: [20, 10, 120, 60])]

    class FakeResult:
        boxes = [FakeBox()]
        orig_shape = (100, 200)

    adapter = YOLOAdapter()
    adapter._loaded = True
    adapter._class_names = ["barcode", "materai", "signature", "stamp"]
    adapter._model = types.SimpleNamespace(predict=lambda *args, **kwargs: [FakeResult()])
    monkeypatch.setattr(yolo_adapter, "logger", types.SimpleNamespace(warning=lambda *args, **kwargs: None))

    result = asyncio.run(adapter.detect_batch([b"broken", _SMALL_PNG]))

    assert result[0]["page_number"] == 2
    assert result[0]["bounding_box"] == [20, 10, 120, 60]
    assert result[0]["normalized_bounding_box"] == [0.1, 0.1, 0.6, 0.6]


def test_detection_batches_pages_without_losing_page_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.detection import yolo_adapter

    sys.modules["cv2"] = types.SimpleNamespace(IMREAD_COLOR=1, imdecode=lambda arr, flag: object())

    class FakeBox:
        cls = [0]
        conf = [0.8]
        xyxy = [types.SimpleNamespace(tolist=lambda: [0, 0, 10, 10])]

    class FakeResult:
        boxes = [FakeBox()]
        orig_shape = (20, 20)

    calls: list[int] = []

    def predict(images, **kwargs):
        calls.append(len(images))
        return [FakeResult() for _ in images]

    adapter = YOLOAdapter()
    adapter._loaded = True
    adapter._class_names = ["stamp"]
    adapter._model = types.SimpleNamespace(predict=predict)
    monkeypatch.setattr(yolo_adapter.settings, "YOLO_BATCH_SIZE", 2)

    result = asyncio.run(adapter.detect_batch([_SMALL_PNG] * 5))

    assert calls == [2, 2, 1]
    assert [item["page_number"] for item in result] == [1, 2, 3, 4, 5]
