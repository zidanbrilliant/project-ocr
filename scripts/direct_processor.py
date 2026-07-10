import asyncio
import io
import time
import uuid
from datetime import datetime
from typing import Any

import numpy as np

from app.domain.entities.business_validation_result import BusinessValidationResult
from app.domain.entities.final_result import FinalResult
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.domain.services.confidence_policy import ConfidencePolicy
from app.domain.services.remark_policy import RemarkPolicy
from app.domain.value_objects.confidence_score import ConfidenceScore
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.barcode.opencv_barcode_adapter import OpenCVBarcodeAdapter
from app.infrastructure.barcode.pyzbar_adapter import PyzbarAdapter
from app.infrastructure.barcode.zxing_adapter import ZXingAdapter
from app.infrastructure.detection.detection_fallback import DetectionFallback
from app.infrastructure.detection.detection_mapper import aggregate_per_object_type, map_to_entity
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.ocr.ocr_fallback_chain import OCRFallbackChain
from app.infrastructure.ocr.document_ocr import DocumentOCR
from app.infrastructure.storage.temp_file_manager import TempFileManager
from app.shared.config.settings import settings
from app.shared.constants import return_codes, statuses
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger, setup_logging
from app.application.services.field_extraction_service import FieldExtractionService
from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.ai_notes_service import AINotesService

logger = get_logger(__name__)


class DirectProcessor:
    def __init__(self) -> None:
        setup_logging()
        self._validator = DocumentValidator()
        self._pdf_renderer = PDFRenderer(dpi=200)
        self._preprocessor = ImagePreprocessor()
        self._field_extractor = FieldExtractionService()
        self._rule_evaluator = BusinessRuleEvaluator()
        self._conf_scorer = ConfidenceScoringService()
        self._notes = AINotesService()
        self._remark = RemarkPolicy()
        self._temp_mgr = TempFileManager()

        self._ocr = DocumentOCR()
        self._ocr_chain = OCRFallbackChain(self._ocr)

        self._yolo = YOLOAdapter()
        self._det_fallback = DetectionFallback(self._yolo)

        self._barcode_chain = BarcodeFallbackChain(
            ZXingAdapter(), PyzbarAdapter(), OpenCVBarcodeAdapter()
        )

        self._models_loaded = False

    async def warmup(self) -> None:
        logger.info("processor_warmup_start")
        for name, eng in [("document_ocr", self._ocr), ("yolo", self._yolo)]:
            try:
                await eng.warmup()
            except Exception as e:
                logger.warning(f"{name}_warmup_failed", error=str(e))
        self._models_loaded = True
        logger.info("processor_warmup_done")

    async def process(self, file_bytes: bytes, filename: str, doc_type: str = "INV") -> dict[str, Any]:
        start = time.monotonic()
        result: dict[str, Any] = {
            "filename": filename,
            "doc_type": doc_type,
            "status": "error",
            "error": None,
            "processing_time_ms": 0,
            "document_info": {},
            "ocr": {},
            "detections": [],
            "detection_aggregated": {},
            "barcode": {},
            "fields": {},
            "validation": {},
            "confidence": {},
            "remarks": "",
            "pages": [],
        }

        try:
            doc_info = self._validator.validate(file_bytes, filename)
            result["document_info"] = doc_info

            ext = doc_info.get("extension", "")
            page_images: list[bytes] = []
            ocr_ext = ext
            ocr_raw: dict[str, Any] = {}
            if ext == ".pdf":
                pdf_text = await self._ocr_chain.run(file_bytes, None, extension=".pdf")
                if pdf_text.get("raw_text", "").strip():
                    ocr_raw = pdf_text
                    page_images = self._pdf_renderer.render(file_bytes)
                else:
                    page_images = self._pdf_renderer.render(file_bytes)
                    ocr_ext = ".png"
            else:
                page_images = [file_bytes]

            if not page_images:
                raise DocumentError("No page images generated")

            preview_images = []
            for img_bytes in page_images:
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                import cv2
                preview_images.append(cv2.imdecode(arr, cv2.IMREAD_COLOR))

            result["pages"] = preview_images

            preprocessed = [self._preprocessor.preprocess(img) for img in page_images]
            n_pages = len(preprocessed or page_images)

            if ocr_ext != ".pdf":
                all_texts = [""] * n_pages
                all_tokens: list[dict[str, Any]] = []
                total_conf_sum = 0.0
                total_conf_count = 0
                bc_raw: dict[str, Any] = {"barcode_found": False, "barcode_decoded": False}

                for i in range(n_pages):
                    p_img = page_images[i] if i < len(page_images) else b""
                    pp_img = preprocessed[i] if i < len(preprocessed) else None
                    ocr_task = self._ocr_chain.run(p_img, pp_img, extension=ocr_ext)
                    bc_task = self._barcode_chain.read(pp_img or p_img)
                    page_ocr, page_bc = await asyncio.gather(ocr_task, bc_task)

                    txt = page_ocr.get("raw_text", "") or ""
                    all_texts[i] = txt
                    for t in (page_ocr.get("tokens_json", []) or []):
                        t["page_number"] = i + 1
                        all_tokens.append(t)
                    c = page_ocr.get("average_confidence")
                    if c is not None:
                        total_conf_sum += c
                        total_conf_count += 1

                    if page_bc.get("barcode_decoded") and not bc_raw.get("barcode_decoded"):
                        bc_raw = page_bc
                    if not bc_raw.get("barcode_found") and page_bc.get("barcode_found"):
                        bc_raw = page_bc

                ocr_raw["raw_text"] = "\n".join(all_texts)
                ocr_raw["tokens_json"] = all_tokens
                ocr_raw["average_confidence"] = round(total_conf_sum / max(total_conf_count, 1), 2)
            else:
                bc_raw = {"barcode_found": False, "barcode_decoded": False}
            result["ocr"] = ocr_raw

            quality_scores = []
            for pp_img in preprocessed or page_images:
                quality_scores.append(self._preprocessor.compute_quality(pp_img))
            quality = quality_scores[0] if quality_scores else {}

            all_detections: list[dict[str, Any]] = []
            if preprocessed:
                import sys
                all_detections = await self._yolo.detect_batch(preprocessed)
            else:
                all_detections = []

            det_entities = [map_to_entity(d) for d in all_detections]
            aggregated = aggregate_per_object_type(det_entities)
            result["detections"] = all_detections
            result["detection_aggregated"] = {
                obj_type: {
                    "object_type": d.object_type,
                    "result": d.result,
                    "confidence": d.confidence,
                    "bounding_box": d.bounding_box,
                }
                for obj_type, d in aggregated.items()
            }
            barcode_raw = bc_raw
            result["barcode"] = barcode_raw

            fields = ocr_raw.get("fields_json") or self._field_extractor.extract_from_ocr(ocr_raw)
            layout_fields = self._field_extractor.extract_layout_aware(ocr_raw.get("tokens_json", []))
            fields.update(layout_fields)
            result["fields"] = fields

            amount = None
            if fields.get("transaction_amount"):
                amount = fields["transaction_amount"].get("value")

            from app.domain.entities.ocr_result import OCRResult as OCREntity
            ocr_entity = OCREntity()
            ocr_entity.raw_text = ocr_raw.get("raw_text")
            ocr_entity.average_confidence = ocr_raw.get("average_confidence")
            ocr_entity.invoice_number = ocr_raw.get("invoice_number") or (fields.get("document_number", {}).get("value"))
            ocr_entity.billing_number = ocr_raw.get("billing_number") or (fields.get("billing_number", {}).get("value"))
            ocr_entity.transaction_amount = ocr_raw.get("transaction_amount") or amount
            ocr_entity.invoice_confidence = ocr_raw.get("invoice_confidence") or fields.get("document_number", {}).get("confidence")
            ocr_entity.billing_confidence = ocr_raw.get("billing_confidence") or fields.get("billing_number", {}).get("confidence")
            ocr_entity.amount_confidence = ocr_raw.get("amount_confidence") or fields.get("transaction_amount", {}).get("confidence")

            validation = self._rule_evaluator.validate_invoice(
                ocr=ocr_entity,
                detections=list(aggregated.values()),
                amount=amount,
                confidence=ocr_raw.get("average_confidence"),
            )

            total_conf = self._conf_scorer.calculate(
                ocr_result=ocr_raw,
                detections=all_detections,
                barcode_result=barcode_raw,
                document_info=doc_info,
                image_bytes=preprocessed[0] if preprocessed else None,
            )

            passed = validation.passed and total_conf >= settings.CONFIDENCE_THRESHOLD
            overall = statuses.OK if passed else statuses.NG
            remark = self._notes.generate_remark(validation)

            confidence_level = ConfidenceScore.level(total_conf)

            result["validation"] = {
                "passed": validation.passed,
                "return_status": validation.return_status,
                "return_code": validation.return_code,
                "failed_rules": [
                    {"rule_id": r.rule_id, "rule_name": r.rule_name, "message": r.message}
                    for r in validation.failed_rules
                ],
            }

            if barcode_raw.get("barcode_decoded"):
                barcode_score = 100.0
            elif barcode_raw.get("barcode_found"):
                barcode_score = 70.0
            else:
                barcode_score = 0.0

            quality_avg = (
                quality.get("resolution_score", 100)
                + quality.get("blur_score", 100)
                + quality.get("brightness_score", 100)
                + quality.get("page_readability_score", 100)
            ) / 4.0

            ocr_field_avg = self._get_ocr_field_avg(ocr_entity)
            field_val = 100.0 if (ocr_entity.invoice_number and ocr_entity.transaction_amount) else 30.0
            detection_avg = (
                sum(d.get("confidence", 0) or 0 for d in all_detections) / max(len(all_detections), 1)
            )

            result["confidence"] = {
                "total": round(total_conf, 2),
                "level": confidence_level,
                "overall_result": overall,
                "components": {
                    "ocr_field_confidence": round(ocr_field_avg, 2),
                    "field_validation_confidence": round(field_val, 2),
                    "object_detection_confidence": round(detection_avg, 2),
                    "barcode_confidence": barcode_score,
                    "document_quality_confidence": round(quality_avg, 2),
                },
            }

            result["remarks"] = remark
            result["status"] = overall
            result["quality_scores"] = quality

            elapsed_ms = int((time.monotonic() - start) * 1000)
            result["processing_time_ms"] = elapsed_ms

        except DocumentError as e:
            result["status"] = statuses.NG
            result["error"] = str(e)
            result["remarks"] = str(e)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result["processing_time_ms"] = elapsed_ms
        except Exception as e:
            logger.exception("direct_process_failed")
            result["status"] = "error"
            result["error"] = str(e)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result["processing_time_ms"] = elapsed_ms

        return result

    def _get_ocr_field_avg(self, ocr_entity: Any) -> float:
        scores = []
        if ocr_entity.invoice_confidence is not None:
            scores.append(ocr_entity.invoice_confidence)
        if ocr_entity.amount_confidence is not None:
            scores.append(ocr_entity.amount_confidence)
        if ocr_entity.billing_confidence is not None:
            scores.append(ocr_entity.billing_confidence)
        return sum(scores) / len(scores) if scores else 0.0

    async def close(self) -> None:
        self._temp_mgr.cleanup_all()
