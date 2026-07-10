import pytest

from app.domain.entities.business_validation_result import BusinessValidationResult
from app.domain.entities.detection_result import DetectionResult
from app.domain.entities.ocr_result import OCRResult
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator, RuleConfig


@pytest.fixture
def evaluator() -> BusinessRuleEvaluator:
    config = RuleConfig(
        require_invoice_number=True,
        require_amount=True,
        require_billing_number=False,
        require_stamp=True,
        require_signature=False,
        require_materai_above_threshold=True,
        amount_stamp_duty_threshold=5_000_000,
        require_barcode=False,
        confidence_threshold=80,
    )
    return BusinessRuleEvaluator(config)


def test_invoice_all_rules_pass(evaluator: BusinessRuleEvaluator) -> None:
    ocr = OCRResult()
    ocr.invoice_number = "INV-001"
    ocr.transaction_amount = 1_000_000.0
    ocr.invoice_confidence = 95.0
    ocr.amount_confidence = 90.0

    detections = [
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="materai", result="OK", required=True, confidence=95.0),
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=90.0),
    ]

    result = evaluator.validate_invoice(ocr, detections, 1_000_000.0, 90.0)
    assert result.passed is True
    assert result.return_status == "OK"


def test_invoice_missing_stamp(evaluator: BusinessRuleEvaluator) -> None:
    ocr = OCRResult()
    ocr.invoice_number = "INV-001"
    ocr.transaction_amount = 1_000_000.0

    result = evaluator.validate_invoice(ocr, [], 1_000_000.0, 90.0)
    assert result.passed is False
    assert result.return_status == "NG"
    assert any("stamp" in r.rule_id.lower() for r in result.failed_rules)


def test_invoice_missing_materai_above_threshold(evaluator: BusinessRuleEvaluator) -> None:
    ocr = OCRResult()
    ocr.invoice_number = "INV-002"
    ocr.transaction_amount = 10_000_000.0

    detections = [
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=90.0),
    ]

    result = evaluator.validate_invoice(ocr, detections, 10_000_000.0, 90.0)
    assert result.passed is False
    assert any("INV-R004" in r.rule_id for r in result.failed_rules)


def test_delivery_note_missing_signatures(evaluator: BusinessRuleEvaluator) -> None:
    result = evaluator.validate_delivery_note([])
    assert result.passed is False
    assert len(result.failed_rules) == 2
    assert any("DN-R001" in r.rule_id for r in result.failed_rules)
    assert any("DN-R002" in r.rule_id for r in result.failed_rules)


def test_delivery_note_all_pass() -> None:
    config = RuleConfig(required_signature_count=2, required_stamp_count=2)
    eval = BusinessRuleEvaluator(config)
    detections = [
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="signature", result="OK", required=True, confidence=90.0),
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="signature", result="OK", required=True, confidence=85.0),
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=95.0),
        DetectionResult(page_number=1, model_name="yolo", model_version="1", object_type="stamp", result="OK", required=True, confidence=92.0),
    ]
    result = eval.validate_delivery_note(detections)
    assert result.passed is True
