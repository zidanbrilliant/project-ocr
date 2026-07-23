import pytest
from pydantic import ValidationError

from app.interfaces.schemas.local_result_contract import validate_local_result


def _smallest_valid_envelope() -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "header": {
            "correlation_id": "correlation-001",
            "overall_result": "OK",
            "processing_status": "COMPLETED",
        },
        "documents": [
            {
                "document_id": "document-001",
                "document_name": "invoice.png",
                "document_result": "OK",
                "pages": [
                    {
                        "page_number": 1,
                        "page_result": "OK",
                        "detections": [{"bounding_box": {"pixel_xyxy": [1, 2, 3, 4]}}],
                    }
                ],
            }
        ],
    }


def test_local_result_requires_correlation_id() -> None:
    with pytest.raises(ValidationError):
        validate_local_result({"schema_version": "1.1.0", "header": {}, "documents": []})


def test_local_result_rejects_detection_bbox_without_four_coordinates() -> None:
    envelope = _smallest_valid_envelope()
    document = envelope["documents"][0]
    page = document["pages"][0]
    page["detections"][0]["bounding_box"]["pixel_xyxy"] = [1, 2, 3]

    with pytest.raises(ValidationError):
        validate_local_result(envelope)


def test_local_result_preserves_additive_fields() -> None:
    envelope = _smallest_valid_envelope()
    envelope["request_metadata"] = {"source": "local"}

    assert validate_local_result(envelope)["request_metadata"] == {"source": "local"}
