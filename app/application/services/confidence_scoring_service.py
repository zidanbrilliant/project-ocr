from typing import Any

from app.domain.entities.detection_result import DetectionResult
from app.domain.entities.ocr_result import OCRResult as OCREntity
from app.domain.services.confidence_policy import ConfidencePolicy
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ConfidenceScoringService:
    def __init__(self) -> None:
        self._policy = ConfidencePolicy()
        self._preprocessor = ImagePreprocessor()

    def calculate(
        self,
        ocr_result: dict[str, Any],
        detections: list[dict[str, Any]],
        barcode_result: dict[str, Any],
        document_info: dict[str, Any],
        image_bytes: bytes | None = None,
    ) -> float:
        from app.domain.entities.ocr_result import OCRResult
        from app.domain.entities.detection_result import DetectionResult

        ocr = self._ocr_result_from_dict(ocr_result)
        detection_entities = [self._detection_from_dict(d) for d in detections]

        barcode_required = settings.REQUIRE_BARCODE_FOR_INVOICE
        barcode_decoded = barcode_result.get("barcode_decoded", False)
        # ponytail: use real decoder confidence instead of hardcoded 100/70/0
        barcode_confidence = barcode_result.get("barcode_confidence", 0.0) or 0.0
        if not barcode_required:
            barcode_confidence = 100.0
        elif not barcode_decoded:
            barcode_decoder_err = not barcode_result.get("barcode_found", False)
            barcode_confidence = 0.0 if barcode_decoder_err else 30.0

        quality_score = self._compute_quality(document_info, image_bytes)

        total = self._policy.calculate(
            ocr=ocr,
            detections=detection_entities,
            barcode_confidence=barcode_confidence,
            document_quality_score=quality_score,
            barcode_required=barcode_required,
        )
        return round(total, 2)

    def _compute_quality(self, document_info: dict[str, Any], image_bytes: bytes | None) -> float:
        if image_bytes:
            quality = self._preprocessor.compute_quality(image_bytes)
            scores = [
                quality.get("resolution_score", 100),
                quality.get("blur_score", 100),
                quality.get("brightness_score", 100),
                quality.get("page_readability_score", 100),
            ]
            return round(sum(scores) / len(scores), 2)
        return 100.0

    def _ocr_result_from_dict(self, data: dict[str, Any]) -> OCREntity:
        r = OCREntity()
        r.raw_text = data.get("raw_text")
        r.average_confidence = data.get("average_confidence")
        r.invoice_number = data.get("invoice_number")
        r.billing_number = data.get("billing_number")
        r.transaction_amount = data.get("transaction_amount")
        r.transaction_date = data.get("transaction_date")
        r.invoice_confidence = data.get("invoice_confidence")
        r.billing_confidence = data.get("billing_confidence")
        r.amount_confidence = data.get("amount_confidence")
        r.date_confidence = data.get("date_confidence")
        return r

    def _detection_from_dict(self, data: dict[str, Any]) -> DetectionResult:
        from app.domain.entities.detection_result import DetectionResult
        return DetectionResult(
            page_number=data.get("page_number", 1),
            model_name=data.get("model_name", ""),
            model_version=data.get("model_version", ""),
            object_type=data.get("object_type", ""),
            result=data.get("result", "NG"),
            required=data.get("required", False),
            confidence=data.get("confidence"),
            bounding_box=data.get("bounding_box"),
        )
