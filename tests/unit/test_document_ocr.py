import asyncio
import sys
import types

import pytest

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )

from app.infrastructure.ocr.document_ocr import DocumentOCR


def test_warmup_raises_when_selected_provider_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    ocr = DocumentOCR()
    ocr._nemotron._available = False
    ocr._nemotron._load_error = "missing model"

    async def fake_warmup() -> None:
        return None

    monkeypatch.setattr(ocr._nemotron, "warmup", fake_warmup)

    with pytest.raises(RuntimeError, match="missing model"):
        asyncio.run(ocr.warmup())
