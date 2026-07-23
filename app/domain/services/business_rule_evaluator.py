from dataclasses import dataclass
from datetime import date, datetime
import re
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
    require_colored_document: bool = True
    required_signature_count: int = 2
    required_stamp_count: int = 2
    require_colored_stamp: bool = True
    confidence_threshold: int = 80
    amount_match_tolerance: float = 0.0
    min_object_confidence: float = 0.25


class BusinessRuleEvaluator:
    def __init__(self, config: RuleConfig | None = None) -> None:
        self._config = config or RuleConfig(
            require_invoice_number=settings.REQUIRE_INVOICE_NUMBER,
            require_signature=settings.REQUIRE_SIGNATURE_FOR_INVOICE,
            require_stamp=settings.REQUIRE_STAMP_FOR_INVOICE,
            require_barcode=settings.REQUIRE_BARCODE_FOR_INVOICE,
            require_colored_document=settings.REQUIRE_COLORED_DOCUMENT,
            amount_stamp_duty_threshold=settings.AMOUNT_STAMP_DUTY_THRESHOLD,
            require_materai_above_threshold=settings.REQUIRE_MATERAI_ABOVE_THRESHOLD,
            required_signature_count=settings.DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT,
            required_stamp_count=settings.DELIVERY_NOTE_REQUIRED_STAMP_COUNT,
            confidence_threshold=settings.CONFIDENCE_THRESHOLD,
            amount_match_tolerance=settings.AMOUNT_MATCH_TOLERANCE,
        )

    def validate_invoice(
        self,
        ocr: OCRResult,
        detections: list[DetectionResult],
        amount: float | None,
        confidence: float | None,
        business_context: dict[str, Any] | None = None,
        barcode_result: dict[str, Any] | None = None,
        is_colored: bool | None = None,
        field_provenance: dict[str, dict[str, Any]] | None = None,
    ) -> BusinessValidationResult:
        failed: list[FailedRule] = []

        if self._config.require_invoice_number and not ocr.invoice_number:
            failed.append(FailedRule("INV-R001", "Invoice number required", "Invoice number not found."))
        elif self._config.require_invoice_number and field_provenance is not None:
            invoice = field_provenance.get("document_number", {})
            if invoice.get("verification_status") != "VERIFIED":
                failed.append(
                    FailedRule(
                        "INV-R012",
                        "Invoice number requires verified OCR evidence",
                        "Invoice number is a deterministic fallback and requires model verification.",
                    )
                )

        if self._config.require_amount and amount is None:
            failed.append(FailedRule("INV-R002", "Amount required", "Amount not found."))

        if self._config.require_billing_number and not ocr.billing_number:
            failed.append(FailedRule("INV-R003", "Billing number required", "Billing number not found."))

        materai_detected = any(
            d.result == "OK" and d.object_type == "materai" for d in detections
        )
        if self._config.require_materai_above_threshold and amount is not None:
            if amount >= self._config.amount_stamp_duty_threshold and not materai_detected:
                failed.append(FailedRule("INV-R004", "Materai required above threshold", "Above Rp. 5.000.000. Missing Stamp Duty."))

        stamp_detected = any(d.result == "OK" and d.object_type == "stamp" for d in detections)
        if self._config.require_stamp and not stamp_detected:
            failed.append(FailedRule("INV-STAMP-R005", "Company stamp required", "Missing company stamp."))

        signature_detected = any(d.result == "OK" and d.object_type == "signature" for d in detections)
        if self._config.require_signature and not signature_detected:
            failed.append(FailedRule("INV-R006", "Signature required", "Missing signature."))

        barcode_decoded = bool((barcode_result or {}).get("barcode_decoded") and (barcode_result or {}).get("barcode_value"))
        if self._config.require_barcode and not barcode_decoded:
            failed.append(FailedRule("INV-R007", "Decoded barcode required", "Barcode was not decoded."))

        if self._config.require_colored_document and is_colored is False:
            failed.append(FailedRule("DOC-R001", "Colored document required", "Document is monochrome."))

        context = business_context or {}
        expected_amount = _as_number(context.get("total_amount"))
        if expected_amount is not None and amount is not None and abs(expected_amount - amount) > self._config.amount_match_tolerance:
            failed.append(FailedRule("INV-R009", "Amount must match PV amount", "Document amount does not match PV amount."))

        expected_vendor = str(context.get("vendor_name") or "").strip()
        if expected_vendor and ocr.vendor_name and not _same_vendor(expected_vendor, ocr.vendor_name):
            failed.append(FailedRule("INV-R010", "Vendor must match PV vendor", "Document vendor does not match PV vendor."))

        request_date = _as_date(context.get("created_datetime"))
        document_date = _as_date(ocr.transaction_date)
        if request_date and document_date:
            allowed_months = 2 if str(context.get("transaction_type", "")).upper() == "REIMBURSEMENT_TOLL" else 6
            if document_date < _subtract_months(request_date, allowed_months) or document_date > request_date:
                failed.append(FailedRule("INV-R011", "Transaction date within permitted period", "Document date is outside the permitted transaction period."))

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
        is_colored: bool | None = None,
    ) -> BusinessValidationResult:
        failed: list[FailedRule] = []

        signature_count = sum(1 for d in detections if d.result == "OK" and d.object_type == "signature")
        stamp_count = sum(1 for d in detections if d.result == "OK" and d.object_type == "stamp")

        if signature_count < self._config.required_signature_count:
            failed.append(FailedRule("DN-R001", "Delivery Note signature count", f"Required signature count is not met ({signature_count}/{self._config.required_signature_count})."))

        if stamp_count < self._config.required_stamp_count:
            failed.append(FailedRule("DN-R002", "Delivery Note stamp count", f"Required company stamp count is not met ({stamp_count}/{self._config.required_stamp_count})."))

        if self._config.require_colored_document and is_colored is False:
            failed.append(FailedRule("DOC-R001", "Colored document required", "Document is monochrome."))

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


def _as_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None


def _subtract_months(value: date, months: int) -> date:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    # Day 1 is sufficient because the rule is month-based, not 30-day based.
    return date(year, month, 1)


def _same_vendor(expected: str, actual: str) -> bool:
    def normalized(value: str) -> str:
        value = re.sub(r"\b(pt|cv|tbk|persero)\b", "", value.lower())
        return re.sub(r"[^a-z0-9]", "", value)

    return normalized(expected) == normalized(actual)
