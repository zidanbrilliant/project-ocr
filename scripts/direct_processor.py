import asyncio
import time
from datetime import datetime
from typing import Any

from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.field_extraction_service import FieldExtractionService
from app.application.services.field_reasoning_service import FieldReasoningService
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.domain.services.remark_policy import RemarkPolicy
from app.domain.value_objects.confidence_score import ConfidenceScore
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.barcode.opencv_barcode_adapter import OpenCVBarcodeAdapter
from app.infrastructure.barcode.pyzbar_adapter import PyzbarAdapter
from app.infrastructure.barcode.zxing_adapter import ZXingAdapter
from app.infrastructure.detection.detection_mapper import aggregate_per_object_type, map_to_entity
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.ocr.document_ocr import DocumentOCR
from app.shared.config.settings import settings
from app.shared.constants import return_codes, statuses
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger, setup_logging

logger = get_logger(__name__)


def _ocr_error(ocr_result: dict[str, Any]) -> str | None:
    error = ocr_result.get("error")
    if isinstance(error, str) and error.strip():
        return error
    return None


class DirectProcessor:
    def __init__(self) -> None:
        setup_logging()
        self._validator = DocumentValidator()
        self._pdf_renderer = PDFRenderer(dpi=200)
        self._preprocessor = ImagePreprocessor()
        self._field_extractor = FieldExtractionService()
        self._field_reasoning = FieldReasoningService()
        self._rule_evaluator = BusinessRuleEvaluator()
        self._conf_scorer = ConfidenceScoringService()
        self._remark = RemarkPolicy()

        self._ocr = DocumentOCR()
        self._yolo = YOLOAdapter()

        self._barcode_chain = BarcodeFallbackChain(ZXingAdapter(), PyzbarAdapter(), OpenCVBarcodeAdapter())

    async def warmup(self) -> None:
        logger.info("processor_warmup_start")
        engines = [("document_ocr", self._ocr), ("yolo", self._yolo), ("field_reasoning", self._field_reasoning)]

        for name, eng in engines:
            try:
                await eng.warmup()
            except Exception as e:
                if name == "document_ocr" and settings.RUN_MODE != "standalone":
                    raise
                logger.warning(f"{name}_warmup_failed", error=str(e))
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
            ocr_ext = ".png" if ext == ".pdf" else ext
            pdf_text_result: dict[str, Any] = {}
            native_pages: list[dict[str, Any]] = []
            ocr_raw: dict[str, Any] = {}
            if ext == ".pdf":
                pdf_text_result = await self._ocr.run(file_bytes, extension=".pdf")
                native_pages = pdf_text_result.get("pages", []) or []
                if not native_pages and pdf_text_result.get("raw_text", "").strip():
                    native_pages = [
                        {
                            "page_number": 1,
                            "raw_text": pdf_text_result["raw_text"],
                            "tokens_json": pdf_text_result.get("tokens_json", []),
                            "text_layer_detected": True,
                            "text_layer_usable": True,
                        }
                    ]
                if pdf_text_result.get("raw_text", "").strip():
                    ocr_raw = dict(pdf_text_result)
                    page_images = self._pdf_renderer.render(file_bytes)
                else:
                    page_images = self._pdf_renderer.render(file_bytes)
                    ocr_ext = ".png"
            else:
                page_images = [file_bytes]

            if not page_images:
                raise DocumentError("No page images generated")

            # Keep compressed bytes in session state; decoding every page here
            # doubles memory for large PDFs and Streamlit can display bytes.
            result["pages"] = page_images

            preprocessed = [self._preprocessor.preprocess(img) for img in page_images]
            n_pages = len(preprocessed or page_images)

            # ponytail: collect per-page data for DB
            page_ocrs: list[dict] = []
            page_bcs: list[dict] = []
            bc_raw: dict[str, Any] = {"barcode_found": False, "barcode_decoded": False}

            all_texts = [""] * n_pages
            all_tokens: list[dict[str, Any]] = []
            total_conf_sum = 0.0
            total_conf_count = 0

            for i in range(n_pages):
                p_img = page_images[i] if i < len(page_images) else b""
                pp_img = preprocessed[i] if i < len(preprocessed) else None
                native = native_pages[i] if i < len(native_pages) else None
                if native and native.get("text_layer_usable"):
                    ocr_task = asyncio.sleep(
                        0,
                        result={
                            "engine_name": "pymupdf",
                            "raw_text": native["raw_text"],
                            "tokens_json": native["tokens_json"],
                            "average_confidence": None,
                        },
                    )
                else:
                    ocr_task = self._ocr.run(p_img, extension=ocr_ext)
                bc_task = self._barcode_chain.read(pp_img or p_img)
                page_ocr, page_bc = await asyncio.gather(ocr_task, bc_task)
                if not (page_ocr.get("raw_text") or "").strip() and pp_img and pp_img != p_img:
                    fallback_ocr = await self._ocr.run(pp_img, extension=ocr_ext)
                    if (fallback_ocr.get("raw_text") or "").strip():
                        page_ocr = fallback_ocr

                page_ocrs.append(page_ocr)
                page_bcs.append(page_bc)

                txt = page_ocr.get("raw_text", "") or ""
                all_texts[i] = txt
                for t in page_ocr.get("tokens_json", []) or []:
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
            ocr_raw["average_confidence"] = round(total_conf_sum / total_conf_count, 2) if total_conf_count else None
            ocr_errors = [err for err in (_ocr_error(page_ocr) for page_ocr in page_ocrs) if err]
            if page_ocrs:
                ocr_raw["engine_name"] = page_ocrs[0].get("engine_name", "none")
            if ocr_errors:
                ocr_raw["error"] = ocr_errors[0]

            if not ocr_raw.get("raw_text", "").strip():
                ocr_raw.setdefault("engine_name", page_ocrs[0].get("engine_name", "none") if page_ocrs else "none")
                ocr_raw["error"] = ocr_raw.get("error") or "selected OCR provider returned no text"
                result["error"] = result.get("error") or ocr_raw["error"]

            result["ocr"] = ocr_raw
            result["_page_ocrs"] = page_ocrs
            result["_page_bcs"] = page_bcs

            quality_scores = []
            for pp_img in preprocessed or page_images:
                quality_scores.append(self._preprocessor.compute_quality(pp_img))
            quality = quality_scores[0] if quality_scores else {}

            all_detections: list[dict[str, Any]] = []
            if page_images:
                all_detections = await self._yolo.detect_batch(page_images)
                if not all_detections and self._yolo.load_error is None:
                    all_detections = await self._yolo.detect_batch(
                        page_images, input_size=settings.YOLO_HIGH_RES_INPUT_SIZE
                    )
            else:
                all_detections = []

            yolo_error = self._yolo.load_error or self._yolo.last_detect_error
            if yolo_error:
                result["detection_error"] = yolo_error

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
            if yolo_error and not all_detections:
                result["error"] = result.get("error") or yolo_error
            barcode_raw = bc_raw
            result["barcode"] = barcode_raw

            candidates = self._field_extractor.collect_document_candidates(page_ocrs, doc_type)
            fields = self._field_extractor.resolve_document_candidates(candidates)
            fields, reasoning = await self._field_reasoning.resolve(fields, candidates, doc_type)
            result["fields"] = fields
            result["reasoning"] = reasoning

            amount = None
            if fields.get("transaction_amount"):
                amount = fields["transaction_amount"].get("value")

            from app.domain.entities.ocr_result import OCRResult as OCREntity

            ocr_entity = OCREntity()
            ocr_entity.raw_text = ocr_raw.get("raw_text")
            ocr_entity.average_confidence = ocr_raw.get("average_confidence")
            ocr_entity.invoice_number = ocr_raw.get("invoice_number") or (
                fields.get("document_number", {}).get("value")
            )
            ocr_entity.billing_number = ocr_raw.get("billing_number") or (fields.get("billing_number", {}).get("value"))
            ocr_entity.transaction_amount = ocr_raw.get("transaction_amount") or amount
            ocr_entity.vendor_name = fields.get("vendor_name", {}).get("value")
            ocr_entity.transaction_date = fields.get("transaction_date", {}).get("value")
            ocr_entity.invoice_confidence = ocr_raw.get("invoice_confidence") or fields.get("document_number", {}).get(
                "confidence"
            )
            ocr_entity.billing_confidence = ocr_raw.get("billing_confidence") or fields.get("billing_number", {}).get(
                "confidence"
            )
            ocr_entity.amount_confidence = ocr_raw.get("amount_confidence") or fields.get("transaction_amount", {}).get(
                "confidence"
            )

            if doc_type in {"DN", "DELIVERY_NOTE"}:
                validation = self._rule_evaluator.validate_delivery_note(detections=det_entities)
            else:
                validation = self._rule_evaluator.validate_invoice(
                    ocr=ocr_entity,
                    detections=list(aggregated.values()),
                    amount=amount,
                    confidence=ocr_raw.get("average_confidence"),
                    business_context=None,
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
            remark = self._remark.generate(validation)

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
            result["document_summary"] = await self._field_reasoning.summarize(
                overall,
                fields,
                result["validation"]["failed_rules"],
            )

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
            detection_avg = sum(d.get("confidence", 0) or 0 for d in all_detections) / max(len(all_detections), 1)

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
            if ocr_errors:
                result["status"] = statuses.NG
                result["error"] = ocr_errors[0]
            result["quality_scores"] = quality

            elapsed_ms = int((time.monotonic() - start) * 1000)
            result["processing_time_ms"] = elapsed_ms
            if settings.ENABLE_DATABASE:
                try:
                    await self._save_to_db(result, file_bytes, filename, doc_type)
                except Exception as e:
                    logger.warning("db_save_failed", error=str(e))

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

    async def _save_to_db(self, result: dict[str, Any], file_bytes: bytes, filename: str, doc_type: str) -> None:
        import uuid as uuid_mod

        from app.domain.entities.ai_job import AIJob as AIJobEntity
        from app.domain.entities.final_result import FinalResult
        from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
        from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
        from app.infrastructure.database.session import async_session_factory
        from app.shared.utils.hash import build_idempotency_key

        job_id = uuid_mod.uuid4()
        queue_id = f"ST-{uuid_mod.uuid4().hex[:8]}"
        page_images = result.get("_page_ocrs", [])
        page_bcs = result.get("_page_bcs", [])
        all_dets = result.get("detections", [])
        total_conf = result.get("confidence", {}).get("total")
        overall = result.get("status", "error")
        remark = result.get("remarks", "")
        doc_info = result.get("document_info", {})
        ext = doc_info.get("extension", "")

        async with async_session_factory() as session:
            job_repo = AIJobPostgresRepository(session)
            result_repo = ResultPostgresRepository(session)
            # ponytail: queue_id = ST-{random} so idempotency key won't collide
            idempotency_key = build_idempotency_key(
                f"streamlit-{uuid_mod.uuid4()}", doc_type, 1, filename, file_bytes.hex()[:64]
            )
            job = AIJobEntity(
                job_id=job_id,
                queue_id=queue_id,
                idempotency_key=idempotency_key,
                doc_no=f"STL-{uuid_mod.uuid4().hex[:8]}",
                doc_type=doc_type,
                doc_seq=1,
                trans_type_cd="STREAMLIT",
                file_nm=filename,
                ai_scan_app="STREAMLIT",
                path_file="local",
                processing_status=statuses.COMPLETED,
                overall_result=overall,
                request_datetime=datetime.utcnow(),
                start_datetime=datetime.utcnow(),
                finish_datetime=datetime.utcnow(),
                duration_ms=result.get("processing_time_ms", 0),
            )
            await job_repo.save(job)

            pk = await result_repo.save_document(
                job_id,
                {
                    "document_id": "DOC-001",
                    "document_name": filename,
                    "document_type": doc_type,
                    "file_extension": ext,
                    "file_size_bytes": doc_info.get("size_bytes"),
                    "page_count": doc_info.get("page_count", len(page_images)),
                    "readable": True,
                    "validation_status": "VALID",
                },
            )

            for i, po in enumerate(page_images):
                await result_repo.save_ocr(
                    job_id,
                    pk,
                    {
                        "page_number": i + 1,
                        "engine_name": po.get("engine_name", settings.OCR_PROVIDER),
                        "raw_text": po.get("raw_text"),
                        "tokens_json": po.get("tokens_json"),
                        "average_confidence": po.get("average_confidence"),
                        "processing_time_ms": po.get("processing_time_ms"),
                    },
                )

            for d in all_dets:
                await result_repo.save_detection(job_id, pk, d)

            for i, pb in enumerate(page_bcs):
                await result_repo.save_barcode(
                    job_id,
                    pk,
                    {
                        "page_number": i + 1,
                        "barcode_found": pb.get("barcode_found", False),
                        "barcode_decoded": pb.get("barcode_decoded", False),
                        "barcode_value": pb.get("barcode_value"),
                        "barcode_type": pb.get("barcode_type"),
                        "barcode_confidence": pb.get("barcode_confidence"),
                        "bounding_box": pb.get("bounding_box"),
                        "decoder_name": pb.get("decoder_name"),
                    },
                )

            pages = []
            for i in range(len(page_images)):
                page_dets = [d for d in all_dets if d.get("page_number", 1) == i + 1]
                pages.append(
                    {
                        "page_number": i + 1,
                        "page_index": i,
                        "ocr": {
                            "engine": page_images[i].get("engine_name", "?"),
                            "raw_text": page_images[i].get("raw_text"),
                            "average_confidence": page_images[i].get("average_confidence"),
                        },
                        "detections": page_dets,
                        "barcode": page_bcs[i] if i < len(page_bcs) else {},
                    }
                )

            await result_repo.save_final(
                FinalResult(
                    job_id=job_id,
                    queue_id=queue_id,
                    overall_result=overall,
                    processing_status=statuses.COMPLETED,
                    ai_confidence=total_conf,
                    ai_confidence_level=ConfidenceScore.level(total_conf),
                    ai_note=remark,
                    ai_return_status=overall,
                    ai_return_cd=return_codes.SUCCESS,
                    ai_return_remark=remark,
                    ai_return_confidence=round(total_conf) if total_conf else None,
                    internal_result_json={"pages": pages},
                    processing_time_ms=result.get("processing_time_ms", 0),
                    published_at=datetime.utcnow(),
                )
            )

            await session.commit()
            logger.info("db_save_ok", queue_id=queue_id)

    async def close(self) -> None:
        return None


def _merge_ocr_text(native_text: str, visual_text: str) -> str:
    native = native_text.strip()
    visual = visual_text.strip()
    if not native:
        return visual
    if not visual or visual in native:
        return native
    if native in visual:
        return visual
    return f"{native}\n\n{visual}"
