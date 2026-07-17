from app.application.services.result_builder import build_result_payload


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
    assert payload["schema_version"] == "1.1"
    assert payload["header"]["response_schema_version"] == "1.1"
