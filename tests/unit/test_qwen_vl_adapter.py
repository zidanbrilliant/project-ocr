import asyncio
import sys
import types

import pytest

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

from app.infrastructure.ocr import qwen_vl_adapter as adapter


class _Response:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {}
        self.status_code = 200
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    last_instance: "_Client | None" = None
    instances: list["_Client"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        _Client.last_instance = self
        _Client.instances.append(self)

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> _Response:
        self.calls.append(("get", url, None))
        return _Response({"status": "healthy"})

    async def post(self, url: str, json: dict | None = None) -> _Response:
        self.calls.append(("post", url, json))
        return _Response(
            {
                "engine_name": (json or {}).get("engine_name", "qwen2.5-vl"),
                "raw_text": "ok",
                "tokens_json": [],
                "average_confidence": 95.0,
            }
        )


def test_remote_qwen_service_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter.settings, "QWEN_SERVICE_URL", "http://qwen:8000")
    monkeypatch.setattr(adapter, "_llm_instance", None)
    monkeypatch.setattr(adapter.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        adapter,
        "logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )

    qwen = adapter.QwenVLAdapter()

    asyncio.run(qwen.warmup())
    result = asyncio.run(qwen.reason(b"image-bytes", "ocr", {}, []))

    assert qwen.is_available is True
    assert len(_Client.instances) >= 2
    assert _Client.instances[0].calls[0][1].endswith("/api/v1/qwen/health")
    assert _Client.instances[1].calls[0][1].endswith("/api/v1/qwen/run")
    assert result["raw_text"] == "ok"
    assert result["engine_name"] == "qwen2.5-vl-reasoning"


def test_local_qwen_blank_output_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "vllm", types.SimpleNamespace(SamplingParams=lambda **kwargs: object()))
    monkeypatch.setattr(adapter, "_llm_instance", None)
    monkeypatch.setattr(adapter, "logger", types.SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None))
    monkeypatch.setattr(adapter, "_load_pil_image", lambda image_bytes: object())

    class FakeLLM:
        def generate(self, *args: object, **kwargs: object) -> list[object]:
            return [types.SimpleNamespace(outputs=[types.SimpleNamespace(text="   ")])]

    qwen = adapter.QwenVLAdapter()
    qwen._available = True
    qwen._llm = FakeLLM()

    result = asyncio.run(qwen._run_qwen(b"image-bytes"))

    assert result["error"] == "empty_ocr_output"
    assert result["average_confidence"] == 0.0
