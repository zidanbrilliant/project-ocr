from typing import Any

from app.domain.entities.detection_result import DetectionResult
from app.domain.entities.ocr_result import OCRResult


class ConfidencePolicy:
    OCR_WEIGHT: float = 0.30
    FIELD_WEIGHT: float = 0.20
    DETECTION_WEIGHT: float = 0.30
    BARCODE_WEIGHT: float = 0.10
    QUALITY_WEIGHT: float = 0.10

    def calculate(
        self,
        ocr: OCRResult,
        detections: list[DetectionResult],
        barcode_confidence: float | None,
        document_quality_score: float | None,
        barcode_required: bool = False,
    ) -> float:
        ocr_score = self._ocr_confidence(ocr)
        field_score = self._field_validation(ocr)
        detection_score = self._detection_confidence(detections)
        barcode_score = self._barcode_confidence(barcode_confidence, barcode_required)
        quality_score = document_quality_score or 100.0

        total = (
            self.OCR_WEIGHT * ocr_score
            + self.FIELD_WEIGHT * field_score
            + self.DETECTION_WEIGHT * detection_score
            + self.BARCODE_WEIGHT * barcode_score
            + self.QUALITY_WEIGHT * quality_score
        )
        return total

    def _ocr_confidence(self, ocr: OCRResult) -> float:
        scores = []
        if ocr.invoice_confidence is not None:
            scores.append(ocr.invoice_confidence)
        if ocr.billing_confidence is not None:
            scores.append(ocr.billing_confidence)
        if ocr.amount_confidence is not None:
            scores.append(ocr.amount_confidence)
        if ocr.date_confidence is not None:
            scores.append(ocr.date_confidence)
        if not scores and ocr.average_confidence is not None:
            scores.append(ocr.average_confidence)
        if not scores:
            return 0.0
        return sum(self._as_percentage(score) for score in scores) / len(scores)

    @staticmethod
    def _as_percentage(value: float) -> float:
        """Accept legacy extractor evidence (0-1) and model scores (0-100)."""
        return value * 100.0 if 0.0 <= value <= 1.0 else value

    def _field_validation(self, ocr: OCRResult) -> float:
        scores = []
        if ocr.invoice_number is not None:
            scores.append(self._as_percentage(ocr.invoice_confidence) if ocr.invoice_confidence is not None else 50.0)
        if ocr.transaction_amount is not None:
            scores.append(self._as_percentage(ocr.amount_confidence) if ocr.amount_confidence is not None else 50.0)
        if ocr.transaction_date is not None:
            scores.append(self._as_percentage(ocr.date_confidence) if ocr.date_confidence is not None else 50.0)
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def _detection_confidence(self, detections: list[DetectionResult]) -> float:
        if not detections:
            return 0.0
        scores = [d.confidence for d in detections if d.confidence is not None]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def _barcode_confidence(self, barcode_confidence: float | None, required: bool) -> float:
        if not required:
            return 100.0
        if barcode_confidence is None:
            return 0.0
        return barcode_confidence
