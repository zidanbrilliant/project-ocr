import asyncio
import sys
import types

import pytest

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.SimpleNamespace(
        frombuffer=lambda data, *args, **kwargs: data,
        uint8=object(),
        ndarray=object,
    )

if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace(
        IMREAD_COLOR=1,
        COLOR_BGR2GRAY=0,
        THRESH_BINARY=0,
        imdecode=lambda *args, **kwargs: None,
        cvtColor=lambda *args, **kwargs: None,
        threshold=lambda *args, **kwargs: (None, None),
        imencode=lambda *args, **kwargs: (True, types.SimpleNamespace(tobytes=lambda: b"")),
    )

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

from app.application.services.result_builder import build_result_payload
from scripts import direct_processor as dp


def _png_bytes() -> bytes:
    return b"fake-rendered-page"


def test_direct_processor_has_no_local_database_persistence() -> None:
    assert not hasattr(dp.DirectProcessor, "_save_to_db")


def test_direct_processor_disables_color_rule_only_for_local_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dp, "setup_logging", lambda: None)

    processor = dp.DirectProcessor()

    config = processor._rule_evaluator._config
    assert config.require_colored_document is False
    assert config.require_invoice_number == dp.settings.REQUIRE_INVOICE_NUMBER
    assert config.confidence_threshold == dp.settings.CONFIDENCE_THRESHOLD
    assert config.require_signature == dp.settings.REQUIRE_SIGNATURE_FOR_INVOICE
    assert config.require_stamp == dp.settings.REQUIRE_STAMP_FOR_INVOICE
    assert config.require_barcode == dp.settings.REQUIRE_BARCODE_FOR_INVOICE
    assert (
        config.require_materai_above_threshold
        == dp.settings.REQUIRE_MATERAI_ABOVE_THRESHOLD
    )
    assert (
        config.amount_stamp_duty_threshold
        == dp.settings.AMOUNT_STAMP_DUTY_THRESHOLD
    )
    assert (
        config.required_signature_count
        == dp.settings.DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT
    )
    assert (
        config.required_stamp_count
        == dp.settings.DELIVERY_NOTE_REQUIRED_STAMP_COUNT
    )
    assert config.amount_match_tolerance == dp.settings.AMOUNT_MATCH_TOLERANCE


def test_pdf_text_falls_back_when_page_ocr_is_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp, "setup_logging", lambda: None)
    processor = dp.DirectProcessor()

    monkeypatch.setattr(processor, "_validator", types.SimpleNamespace(validate=lambda *args, **kwargs: {"extension": ".pdf", "size_bytes": 1, "page_count": 1}))
    monkeypatch.setattr(processor, "_pdf_renderer", types.SimpleNamespace(render=lambda *args, **kwargs: [_png_bytes()]))
    monkeypatch.setattr(processor, "_preprocessor", types.SimpleNamespace(preprocess=lambda image_bytes: image_bytes, compute_quality=lambda image_bytes: {"resolution_score": 100, "blur_score": 100, "brightness_score": 100, "page_readability_score": 100}))
    monkeypatch.setattr(processor, "_barcode_chain", types.SimpleNamespace(read=lambda *args, **kwargs: asyncio.sleep(0, result={"barcode_found": False, "barcode_decoded": False})))
    monkeypatch.setattr(processor, "_yolo", types.SimpleNamespace(detect_batch=lambda *args, **kwargs: asyncio.sleep(0, result=[]), load_error=None, last_detect_error=None))
    monkeypatch.setattr(
        processor,
        "_field_extractor",
        types.SimpleNamespace(
            collect_document_candidates=lambda *args, **kwargs: {},
            resolve_document_candidates=lambda *args, **kwargs: {},
        ),
    )
    monkeypatch.setattr(
        processor,
        "_field_reasoning",
        types.SimpleNamespace(resolve=lambda *args, **kwargs: asyncio.sleep(0, result=({}, {"used": False}))),
    )
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
                "engine_name": "nemotron-parse-v1.2",
                "raw_text": "",
                "tokens_json": [],
                "average_confidence": 0.0,
                "error": "empty_ocr_output",
            }

    processor._ocr = FakeOCR()

    result = asyncio.run(processor.process(b"%PDF-1.4 fake", "test.pdf", "INV"))

    assert result["ocr"]["raw_text"] == "PDF TEXT"
    assert result["ocr"].get("error") is None
    assert result["barcode"]["evaluation_status"] == "not_evaluated"
    assert result["document_color"]["evaluation_status"] == "not_evaluated"

    document = build_result_payload(
        result,
        "test.pdf",
        "application/pdf",
        10,
        result["processing_time_ms"],
    )["documents"][0]

    assert document["barcode"]["evaluation_status"] == "not_evaluated"
    assert document["pages"][0]["barcodes"][0]["evaluation_status"] == "not_evaluated"
    assert document["document_color"]["evaluation_status"] == "not_evaluated"
