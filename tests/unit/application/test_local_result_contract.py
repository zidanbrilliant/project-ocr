import pytest
from pydantic import ValidationError

from app.application.services.result_builder import build_result_envelope
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


def test_local_result_rejects_empty_detection_bbox() -> None:
    envelope = _smallest_valid_envelope()
    document = envelope["documents"][0]
    page = document["pages"][0]
    page["detections"][0]["bounding_box"] = {}

    with pytest.raises(ValidationError):
        validate_local_result(envelope)


def test_local_result_validates_builder_envelope_with_local_identifiers() -> None:
    payload = build_result_envelope(
        [
            {
                "document_id": "DOC-42",
                "document_name": "invoice.png",
                "document_result": "NG",
                "detections": [
                    {"bounding_box": [1, 2, 3, 4], "normalized_bounding_box": [0.1, 0.2, 0.3, 0.4]}
                ],
                "pages": [
                    {
                        "page_number": 1,
                        "detections": [
                            {"bounding_box": [1, 2, 3, 4], "normalized_bounding_box": [0.1, 0.2, 0.3, 0.4]}
                        ],
                    }
                ],
            }
        ],
        20,
        correlation_id="correlation-001",
        job_id="job-001",
    )

    validated = validate_local_result(payload)

    assert validated["header"]["correlation_id"] == "correlation-001"
    assert validated["processing"]["job_id"] == "job-001"
    assert validated["documents"][0]["document_id"] == "DOC-42"
    assert validated["documents"][0]["document_name"] == "invoice.png"
    assert validated["documents"][0]["pages"][0]["detections"][0]["bounding_box"]["pixel_xyxy"] == [
        1.0,
        2.0,
        3.0,
        4.0,
    ]


def test_local_result_preserves_additive_fields() -> None:
    envelope = _smallest_valid_envelope()
    envelope["request_metadata"] = {"source": "local"}

    assert validate_local_result(envelope)["request_metadata"] == {"source": "local"}
