import asyncio
import json
from pathlib import Path
from typing import Any

from app.application.services.local_execution_service import LocalExecutionService
from app.application.services.local_runtime import LocalDocument
from app.application.services.result_builder import build_result_envelope
from app.interfaces.schemas.local_result_contract import validate_local_result
from scripts import result_adapter


class PageImage:
    shape = (100, 200, 3)


class MixedProcessor:
    async def process(
        self,
        _file_bytes: bytes,
        filename: str,
        _doc_type: str,
    ) -> dict[str, Any]:
        if filename == "bad.png":
            raise RuntimeError("cannot process bad.png")
        return {
            "document_id": "document-good",
            "status": "OK",
            "doc_type": "INV",
            "pages": [PageImage()],
            "_page_ocrs": [
                {
                    "engine_name": "fake-ocr",
                    "raw_text": "INV-001",
                    "average_confidence": 0.95,
                    "tokens_json": [],
                }
            ],
            "_page_bcs": [
                {
                    "barcode_found": True,
                    "barcode_decoded": True,
                    "value": "INV-001",
                    "evaluation_status": "not_evaluated",
                }
            ],
            "barcode": {
                "barcode_found": True,
                "barcode_decoded": True,
                "value": "INV-001",
                "evaluation_status": "not_evaluated",
            },
            "fields": {
                "document_number": {
                    "value": "INV-001",
                    "confidence": 0.95,
                    "source_page_number": 1,
                }
            },
            "document_color": {
                "is_colored": True,
                "evaluation_status": "not_evaluated",
            },
            "validation": {"passed": True, "failed_rules": []},
            "confidence": {
                "overall_result": "OK",
                "total": 0.95,
                "level": "HIGH",
            },
            "processing_time_ms": 1,
        }


def document(name: str) -> LocalDocument:
    return LocalDocument(name, "image/png", name.encode(), "INV")


def complete_envelope_with_two_documents() -> dict:
    documents = [
        {
            "document_name": name,
            "document_result": "OK",
            "processing_status": "COMPLETED",
            "processing_time_ms": 10,
            "file_information": {
                "file_name": name,
                "content_type": "image/png",
                "file_size_bytes": 100,
                "file_extension": ".png",
            },
            "confidence": {"total": 0.9},
            "pages": [
                {
                    "page_index": 0,
                    "page_number": 1,
                    "processing_status": "COMPLETED",
                    "ocr": {
                        "status": "SUCCESS",
                        "engine": "fake-ocr",
                        "raw_text": name,
                        "average_confidence": 0.9,
                        "text_blocks": [],
                    },
                    "detections": [],
                    "extracted_fields": [],
                    "errors": [],
                }
            ],
            "errors": [],
        }
        for name in ("a.png", "b.png")
    ]
    return build_result_envelope(documents, 20, job_id="job-001")


def test_ui_adapter_reads_completed_canonical_envelope() -> None:
    envelope = complete_envelope_with_two_documents()

    results = result_adapter.normalize_result_envelope_for_ui(envelope)

    assert [item["document"]["file_name"] for item in results] == ["a.png", "b.png"]
    assert results[0]["rabbitmq_preview"] is envelope


def test_streamlit_does_not_process_documents_directly() -> None:
    source = (Path(__file__).parents[2] / "scripts" / "upload_app.py").read_text(
        encoding="utf-8"
    )

    assert "await processor.process" not in source


def test_local_e2e_keeps_good_document_when_one_fails() -> None:
    snapshot = asyncio.run(
        LocalExecutionService(processor=MixedProcessor()).run_inline(
            [document("good.png"), document("bad.png")]
        )
    )

    assert snapshot.status == "PARTIAL_SUCCESS"
    assert snapshot.result is not None
    assert snapshot.result["summary"]["total_documents"] == 2
    assert snapshot.result["header"]["correlation_id"] == snapshot.job_id

    ui_results = result_adapter.normalize_result_envelope_for_ui(snapshot.result)
    good_document = ui_results[0]["rabbitmq_preview"]["documents"][0]
    good_page = good_document["pages"][0]

    assert ui_results[0]["rabbitmq_preview"] is snapshot.result
    assert good_page["ai_note"] == (
        "OCR text found; 0 detection(s); barcode decoded; color evidence found."
    )
    assert good_page["barcodes"][0]["evaluation_status"] == "not_evaluated"
    assert good_document["barcode"]["evaluation_status"] == "not_evaluated"
    assert good_document["document_color"]["evaluation_status"] == "not_evaluated"
    assert good_document["validation"] == {"passed": True, "failed_rules": []}
    assert good_document["confidence"] == {
        "overall_result": "OK",
        "total": 0.95,
        "level": "HIGH",
    }
    assert validate_local_result(snapshot.result) == snapshot.result
    assert json.loads(json.dumps(snapshot.result)) == snapshot.result
