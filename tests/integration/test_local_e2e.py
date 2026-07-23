from pathlib import Path

from app.application.services.result_builder import build_result_envelope
from scripts import result_adapter


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
