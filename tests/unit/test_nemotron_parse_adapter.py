import asyncio
import sys
import types

import pytest

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

from app.infrastructure.ocr import nemotron_parse_adapter as adapter


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def raise_for_status(self) -> None:
        if self.is_error:
            raise RuntimeError(self.text)

    def json(self) -> dict:
        return self._payload


class _Client:
    response = _Response(
        200,
        {
            "engine_name": "nemotron-parse-v1.2",
            "raw_text": "Invoice 10",
            "tokens_json": [],
            "average_confidence": None,
        },
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> _Response:
        return _Response(200, {"status": "healthy"})

    async def post(self, url: str, json: dict) -> _Response:
        return self.response


def test_remote_nemotron_returns_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter.settings, "NEMOTRON_SERVICE_URL", "http://nemotron:8000")
    monkeypatch.setattr(adapter.httpx, "AsyncClient", _Client)
    ocr = adapter.NemotronParseAdapter()

    asyncio.run(ocr.warmup())
    result = asyncio.run(ocr.run(b"image", ".jpg"))

    assert ocr.is_available is True
    assert result["raw_text"] == "Invoice 10"


def test_remote_nemotron_preserves_http_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter.settings, "NEMOTRON_SERVICE_URL", "http://nemotron:8000")
    monkeypatch.setattr(adapter.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(_Client, "response", _Response(503, {"detail": "model_not_loaded"}))
    ocr = adapter.NemotronParseAdapter()

    result = asyncio.run(ocr.run(b"image", ".jpg"))

    assert result["error"] == "remote_http_503:model_not_loaded"


def test_empty_image_is_rejected_without_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter.settings, "NEMOTRON_SERVICE_URL", "")
    ocr = adapter.NemotronParseAdapter()

    result = asyncio.run(ocr.run(b""))

    assert result["error"] == "empty_image"
