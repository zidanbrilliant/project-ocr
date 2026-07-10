import pytest

from app.domain.entities.detection_result import DetectionResult
from app.domain.entities.ocr_result import OCRResult
from app.domain.services.confidence_policy import ConfidencePolicy


@pytest.fixture
def policy() -> ConfidencePolicy:
    return ConfidencePolicy()


def test_ocr_confidence_average(policy: ConfidencePolicy) -> None:
    ocr = OCRResult()
    ocr.invoice_confidence = 90.0
    ocr.amount_confidence = 80.0
    score = policy._ocr_confidence(ocr)
    assert score == 85.0


def test_detection_confidence_average(policy: ConfidencePolicy) -> None:
    detections = [
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="materai", result="OK", required=True, confidence=95.0),
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=85.0),
    ]
    score = policy._detection_confidence(detections)
    assert score == 90.0


def test_barcode_not_required_full_score(policy: ConfidencePolicy) -> None:
    score = policy._barcode_confidence(None, required=False)
    assert score == 100.0


def test_barcode_required_missing(policy: ConfidencePolicy) -> None:
    score = policy._barcode_confidence(None, required=True)
    assert score == 0.0


def test_total_confidence_calculation(policy: ConfidencePolicy) -> None:
    ocr = OCRResult()
    ocr.invoice_confidence = 90.0
    ocr.amount_confidence = 90.0

    detections = [
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=100.0),
    ]

    total = policy.calculate(
        ocr=ocr,
        detections=detections,
        barcode_confidence=100.0,
        document_quality_score=100.0,
        barcode_required=False,
    )
    assert 0 <= total <= 100


def test_confidence_score_boundaries() -> None:
    from app.domain.value_objects.confidence_score import ConfidenceScore
    c = ConfidenceScore(85.0)
    assert c.is_above_threshold(80) is True
    assert c.to_int() == 85
    assert ConfidenceScore.level(97.0) == "Very High"
    assert ConfidenceScore.level(85.0) == "High"
    assert ConfidenceScore.level(65.0) == "Medium"
    assert ConfidenceScore.level(40.0) == "Low"
    assert ConfidenceScore.level(None) is None
