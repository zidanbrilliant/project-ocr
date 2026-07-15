from dataclasses import dataclass, field
from typing import Any

from app.domain.entities.business_validation_result import BusinessValidationResult, FailedRule
from app.domain.entities.detection_result import DetectionResult
from app.domain.entities.ocr_result import OCRResult
from app.shared.config.settings import settings
from app.shared.constants.doc_types import INV


@dataclass
class RuleConfig:
    require_invoice_number: bool = True
    require_amount: bool = True
    require_billing_number: bool = False
    amount_stamp_duty_threshold: int = 5_000_000
    require_materai_above_threshold: bool = True
    require_signature: bool = False
    require_stamp: bool = True
    require_barcode: bool = False
    required_signature_count: int = 2
    required_stamp_count: int = 2
    require_colored_stamp: bool = True
    confidence_threshold: int = 80
    min_object_confidence: float = 0.25


class BusinessRuleEvaluator:
    def __init__(self, config: RuleConfig | None = None) -> None:
        self._config = config or RuleConfig(
            require_signature=settings.REQUIRE_SIGNATURE_FOR_INVOICE,
            require_stamp=settings.REQUIRE_STAMP_FOR_INVOICE,
            require_barcode=settings.REQUIRE_BARCODE_FOR_INVOICE,
            amount_stamp_duty_threshold=settings.AMOUNT_STAMP_DUTY_THRESHOLD,
            require_materai_above_threshold=settings.REQUIRE_MATERAI_ABOVE_THRESHOLD,
            required_signature_count=settings.DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT,
            required_stamp_count=settings.DELIVERY_NOTE_REQUIRED_STAMP_COUNT,
            confidence_threshold=settings.CONFIDENCE_THRESHOLD,
        )

    def validate_invoice(
        self,
        ocr: OCRResult,
        detections: list[DetectionResult],
        amount: float | None,
        confidence: float | None,
    ) -> BusinessValidationResult:
        failed: list[FailedRule] = []

        if self._config.require_invoice_number and not ocr.invoice_number:
            failed.append(FailedRule("INV-R001", "Invoice number required", "Invoice number not found."))

        if self._config.require_amount and amount is None:
            failed.append(FailedRule("INV-R002", "Amount required", "Amount not found."))

        if self._config.require_billing_number and not ocr.billing_number:
            failed.append(FailedRule("INV-R003", "Billing number required", "Billing number not found."))

        materai_detected = any(
            d.result == "OK" and d.object_type == "materai" for d in detections
        )
        if self._config.require_materai_above_threshold and amount is not None:
            if amount > self._config.amount_stamp_duty_threshold and not materai_detected:
                failed.append(FailedRule("INV-R004", "Materai required above threshold", "Above Rp. 5.000.000. Missing Stamp Duty."))

        stamp_detected = any(d.result == "OK" and d.object_type == "stamp" for d in detections)
        if self._config.require_stamp and not stamp_detected:
            failed.append(FailedRule("INV-STAMP-R005", "Company stamp required", "Missing company stamp."))

        signature_detected = any(d.result == "OK" and d.object_type == "signature" for d in detections)
        if self._config.require_signature and not signature_detected:
            failed.append(FailedRule("INV-R006", "Signature required", "Missing signature."))

        barcode_detected = any(d.result == "OK" and d.object_type == "barcode" for d in detections)
        if self._config.require_barcode and not barcode_detected:
            failed.append(FailedRule("INV-R007", "Barcode required", "Barcode not found."))

        if confidence is not None and confidence < self._config.confidence_threshold:
            failed.append(FailedRule("INV-R008", "Confidence below threshold", "AI confidence below threshold. Manual verification required."))

        passed = len(failed) == 0
        return BusinessValidationResult(
            passed=passed,
            return_status="OK" if passed else "NG",
            return_code="SUCCESS",
            failed_rules=failed,
            remark=self._build_remark(failed, passed),
        )

    def validate_delivery_note(
        self,
        detections: list[DetectionResult],
    ) -> BusinessValidationResult:
        failed: list[FailedRule] = []

        signature_count = sum(1 for d in detections if d.result == "OK" and d.object_type == "signature")
        stamp_count = sum(1 for d in detections if d.result == "OK" and d.object_type == "stamp")

        if signature_count < self._config.required_signature_count:
            failed.append(FailedRule("DN-R001", "Delivery Note signature count", f"Required signature count is not met ({signature_count}/{self._config.required_signature_count})."))

        if stamp_count < self._config.required_stamp_count:
            failed.append(FailedRule("DN-R002", "Delivery Note stamp count", f"Required company stamp count is not met ({stamp_count}/{self._config.required_stamp_count})."))

        passed = len(failed) == 0
        return BusinessValidationResult(
            passed=passed,
            return_status="OK" if passed else "NG",
            return_code="SUCCESS",
            failed_rules=failed,
            remark=self._build_remark(failed, passed),
        )

    def _build_remark(self, failed: list[FailedRule], passed: bool) -> str:
        if passed:
            return "Verification passed."
        if not failed:
            return "Verification failed."
        return "; ".join(f.message for f in failed)
