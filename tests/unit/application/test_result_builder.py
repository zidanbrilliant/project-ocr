from app.application.services.result_builder import build_result_envelope, build_result_payload


class _PageImage:
    shape = (100, 200, 3)


def test_result_payload_contains_ocr_fields_and_normalized_detection_box() -> None:
    raw = {
        "status": "OK", "doc_type": "INV", "pages": [_PageImage()],
        "_page_ocrs": [{"engine_name": "nemotron-parse-v1.2", "raw_text": "INV-1", "average_confidence": None, "tokens_json": [{"text": "INV-1", "confidence": None, "bbox": [1, 2, 3, 4]}]}],
        "document_id": "DOC-42",
        "fields": {"document_number": {"value": "INV-1", "raw_value": "INV-1", "confidence": 90, "status": "FOUND", "source_page_number": 1, "source_bbox": [1, 2, 3, 4], "source_block_id": "p1-b1", "extraction_method": "regex"}},
        "detections": [{"class_id": 3, "object_type": "stamp", "confidence": 90, "page_number": 1, "bounding_box": [20, 10, 120, 60], "normalized_bounding_box": [0.1, 0.1, 0.6, 0.6]}],
    }

    payload = build_result_payload(raw, "invoice.png", "image/png", 10, 20)
    page = payload["documents"][0]["pages"][0]

    assert page["ocr"]["raw_text"] == "INV-1"
    assert page["extracted_fields"][0]["field_name"] == "document_number"
    assert payload["documents"][0]["document_id"] == "DOC-42"
    assert page["extracted_fields"][0]["source_page_index"] == 0
    assert page["extracted_fields"][0]["source_bbox"] == [1, 2, 3, 4]
    assert page["extracted_fields"][0]["source_block_id"] == "p1-b1"
    assert page["detections"][0]["bounding_box"]["normalized_xyxy"] == [0.1, 0.1, 0.6, 0.6]
    assert payload["schema_version"] == "1.1.0"
    assert payload["header"]["response_schema_version"] == "1.1.0"


def test_result_payload_preserves_field_candidate_audit() -> None:
    raw = {
        "status": "OK",
        "pages": [],
        "field_candidate_audit": {
            "document_number": [{"value": "RI - 23014073", "selection_status": "SELECTED"}]
        },
    }

    payload = build_result_payload(raw, "invoice.png", "image/png", 10, 20)

    assert payload["documents"][0]["field_candidate_audit"]["document_number"][0]["selection_status"] == "SELECTED"


def test_result_envelope_includes_local_identifiers_and_deterministic_page_note() -> None:
    result = build_result_envelope(
        [
            {
                "document_id": "DOC-42",
                "document_name": "invoice.png",
                "document_result": "OK",
                "pages": [
                    {
                        "page_number": 1,
                        "ocr": {"raw_text": "INV-1"},
                        "detections": [{"label": "stamp"}],
                        "barcodes": [{"text": "INV-1"}],
                        "document_color": {"is_colored": True},
                    }
                ],
            }
        ],
        20,
        correlation_id="correlation-001",
        job_id="job-001",
    )

    assert result["header"]["correlation_id"] == "correlation-001"
    assert result["processing"]["job_id"] == "job-001"
    assert result["documents"][0]["pages"][0]["ai_note"] == "OCR text found; 1 detection(s); barcode found; color evidence found."
