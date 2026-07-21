import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.field_extraction_service import FieldExtractionService
from app.application.services.field_reasoning_service import FieldReasoningService
from app.application.services.result_builder import RESULT_SCHEMA_VERSION, build_result_envelope
from app.domain.entities.ai_job import AIJob as AIJobEntity
from app.domain.entities.final_result import FinalResult
from app.domain.entities.normalized_request import (
    DocumentProcessingResult,
    NormalizedDocumentRequest,
    NormalizedJobRequest,
    PageProcessingResult,
)
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.domain.value_objects.confidence_score import ConfidenceScore
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.audit_log_postgres_repository import AuditLogPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.detection.detection_mapper import aggregate_per_object_type, map_to_entity
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.ocr.document_ocr import DocumentOCR
from app.infrastructure.rabbitmq.publisher import ResultPublisher
from app.infrastructure.rabbitmq.retry import RetryHandler
from app.infrastructure.storage.image_server_client import ImageServerClient
from app.shared.config.settings import settings
from app.shared.constants import return_codes, statuses
from app.shared.constants.doc_types import DN
from app.shared.exceptions.base import DocumentError
from app.shared.logging.log_context import log_context
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


def _page_ocr_extension(document_extension: str) -> str:
    if document_extension in {".pdf", ".doc", ".docx"}:
        return ".png"
    return document_extension


def _ocr_error(ocr_result: dict[str, Any]) -> str | None:
    error = ocr_result.get("error")
    if isinstance(error, str) and error.strip():
        return error
    return None


def _average_confidence(ocr_results: list[dict[str, Any]]) -> float | None:
    scores = [float(item["average_confidence"]) for item in ocr_results if item.get("average_confidence") is not None]
    return sum(scores) / len(scores) if scores else None


class AIPipelineOrchestrator:
    def __init__(
        self,
        job_repo: AIJobPostgresRepository,
        result_repo: ResultPostgresRepository,
        audit: AuditLogPostgresRepository,
        publisher: ResultPublisher,
        retry_handler: RetryHandler,
        file_client: ImageServerClient,
        pdf_renderer: PDFRenderer,
        preprocessor: ImagePreprocessor,
        ocr_engine: DocumentOCR,
        yolo: YOLOAdapter,
        barcode_chain: BarcodeFallbackChain,
        validator: DocumentValidator,
        field_extractor: FieldExtractionService,
        field_reasoning: FieldReasoningService,
        rule_evaluator: BusinessRuleEvaluator,
        confidence_scorer: ConfidenceScoringService,
    ) -> None:
        self._job_repo = job_repo
        self._result_repo = result_repo
        self._audit = audit
        self._publisher = publisher
        self._retry = retry_handler
        self._file_client = file_client
        self._pdf_renderer = pdf_renderer
        self._preprocessor = preprocessor
        self._ocr_engine = ocr_engine
        self._yolo = yolo
        self._barcode_chain = barcode_chain
        self._validator = validator
        self._field_extractor = field_extractor
        self._field_reasoning = field_reasoning
        self._rule_evaluator = rule_evaluator
        self._confidence_scorer = confidence_scorer
        # Global per-worker page budget. A semaphore created per document would
        # multiply GPU work by the number of concurrent documents.
        self._page_sem = asyncio.Semaphore(max(1, settings.MAX_INFLIGHT_PAGES))

    async def process(self, normalized: NormalizedJobRequest, msg: AbstractIncomingMessage) -> bool:
        existing = await self._job_repo.get_by_queue_id(normalized.queue_id)
        job_id = existing.job_id if existing else uuid.uuid4()
        async with log_context(
            job_id=str(job_id),
            queue_id=normalized.queue_id,
            message_id=normalized.message_id,
            source=normalized.source_system,
        ):
            try:
                await self._process_job(normalized, job_id, msg)
                return True
            except Exception as e:
                logger.exception("pipeline_unhandled_error")
                await self._handle_job_error(normalized, job_id, msg, str(e))
                return False

    async def _process_job(self, req: NormalizedJobRequest, job_id: uuid.UUID, msg: AbstractIncomingMessage) -> None:
        start_dt = datetime.utcnow()
        existing = await self._job_repo.get_by_id(job_id)
        if existing is None:
            first_doc = req.documents[0] if req.documents else None
            await self._job_repo.save(
                AIJobEntity(
                    job_id=job_id,
                    queue_id=req.queue_id,
                    idempotency_key=req.idempotency_key or req.queue_id,
                    doc_no=req.business_entity_id or req.queue_id,
                    doc_type=first_doc.document_type if first_doc else "UNKNOWN",
                    doc_seq=1,
                    trans_type_cd=req.transaction_type or "UNKNOWN",
                    file_nm=first_doc.file_name if first_doc else "",
                    ai_scan_app=req.source_system,
                    path_file=first_doc.file_url if first_doc else "",
                    pv_no=req.business_entity_id,
                    pv_year=req.business_entity_year,
                    original_payload={
                        key: value for key, value in (req.raw_payload or {}).items() if key != "_raw_body"
                    },
                    request_datetime=start_dt,
                    start_datetime=start_dt,
                )
            )
        await self._audit.log(job_id, req.queue_id, "worker", "job_accepted", after={"doc_count": len(req.documents)})
        await self._job_repo.commit()

        # ponytail: process documents in parallel with bounded concurrency
        doc_sem = asyncio.Semaphore(settings.MAX_PARALLEL_DOCUMENTS)
        download_sem = asyncio.Semaphore(settings.MAX_PARALLEL_DOWNLOADS)

        async def process_one_doc(doc: NormalizedDocumentRequest) -> DocumentProcessingResult:
            async with doc_sem:
                return await self._process_single_document(req, job_id, doc, download_sem)

        tasks = [asyncio.create_task(process_one_doc(d)) for d in req.documents]
        doc_results: list[DocumentProcessingResult] = []
        for coro in asyncio.as_completed(tasks):
            try:
                doc_results.append(await coro)
            except Exception:
                logger.exception("document_task_failed")
                doc_results.append(
                    DocumentProcessingResult(
                        document_index=-1,
                        external_document_id="unknown",
                        document_type="unknown",
                        processing_status=statuses.FAILED,
                        processing_result=statuses.INTERNAL_ERROR,
                    )
                )

        # Sort by document_index for deterministic output
        doc_results.sort(key=lambda r: r.document_index)

        # Aggregate job results
        ok_count = sum(1 for d in doc_results if d.document_result == statuses.OK)
        ng_count = sum(1 for d in doc_results if d.document_result == statuses.NG)
        error_count = sum(
            1 for d in doc_results if d.processing_result in (statuses.INTERNAL_ERROR, statuses.DOCUMENT_ERROR)
        )
        overall = statuses.OK if ok_count == len(doc_results) and error_count == 0 else statuses.NG
        document_confidences = [item.confidence for item in doc_results if item.confidence is not None]
        folder_confidence = min(document_confidences) if document_confidences else None

        finish_dt = datetime.utcnow()
        duration_ms = int((finish_dt - start_dt).total_seconds() * 1000)

        # Build result payload
        result_payload: dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "request": {
                "queue_no": req.queue_id,
                "correlation_id": req.correlation_id,
                "pv_no": req.business_entity_id,
                "pv_year": req.business_entity_year,
                "transaction_type": req.transaction_type,
            },
            "QUEUE_ID": req.queue_id,
            "AI_RETURN_STATUS": overall,
            "AI_RETURN_CD": return_codes.SUCCESS if error_count == 0 else return_codes.PARTIAL_SUCCESS,
            "AI_RETURN_CONFIDENCE": folder_confidence,
            "AI_SCAN_APP": req.source_system,
            "documents": [],
        }
        for dr in doc_results:
            doc_entry = {
                "document_index": dr.document_index,
                "external_document_id": dr.external_document_id,
                "document_type": dr.document_type,
                "processing_status": dr.processing_status,
                "processing_result": dr.processing_result,
                "document_result": dr.document_result,
                "confidence": {
                    "total": dr.confidence,
                    "level": ConfidenceScore.level(dr.confidence),
                    "threshold": settings.CONFIDENCE_THRESHOLD,
                    "overall_result": dr.document_result,
                    "scale": "0-100",
                },
                "ai_note": (dr.document_summary or {}).get("reason", "No document summary available."),
                "fields": dr.extracted_fields,
                "field_candidate_audit": dr.field_candidate_audit,
                "financials": dr.financials or {},
                "reasoning": dr.reasoning,
                "document_summary": dr.document_summary,
                "detections": dr.detections,
                "barcode": dr.barcode_result or {"barcode_found": False, "barcode_decoded": False},
                "document_quality": dr.quality_metrics or {},
                "validation": dr.validations,
                "business_rule": {
                    "rule_version": "v1.0",
                    "rules_passed": 0,
                    "rules_failed": len(dr.validations),
                    "rules": dr.validations,
                },
                "pages": [
                    {
                        "page_index": p.page_index,
                        "page_number": p.page_number,
                        "processing_status": p.processing_status,
                        "processing_result": p.processing_result,
                        "ocr_raw_text": p.ocr_raw_text,
                        "ocr_engine": p.ocr_engine,
                        "ocr_confidence": p.ocr_confidence,
                        "ocr": {
                            "raw_text": p.ocr_raw_text,
                            "engine": p.ocr_engine,
                            "average_confidence": p.ocr_confidence,
                            "text_blocks": p.text_blocks or [],
                        },
                        "image": {
                            "width": p.width,
                            "height": p.height,
                            "page_width_pt": p.page_width_pt,
                            "page_height_pt": p.page_height_pt,
                        },
                        "text_blocks": p.text_blocks,
                        "detections": p.detections,
                        "barcodes": p.barcodes,
                        "extracted_fields": p.extracted_fields,
                        "document_quality": p.quality_metrics or {},
                        "ai_note": (
                            "Page completed." if not p.errors else p.errors[0].get("error", "Page processing failed.")
                        ),
                        "errors": p.errors,
                    }
                    for p in dr.pages
                ],
                "errors": dr.errors,
            }
            result_payload["documents"].append(doc_entry)

        envelope = build_result_envelope(
            result_payload["documents"],
            duration_ms,
            statuses.COMPLETED if error_count == 0 else return_codes.PARTIAL_SUCCESS,
            queue_id=req.queue_id,
            pv_no=req.business_entity_id or "",
            pv_year=req.business_entity_year or "",
            source_system=req.source_system,
            overall_confidence=folder_confidence,
            confidence_level=ConfidenceScore.level(folder_confidence),
            confidence_threshold=settings.CONFIDENCE_THRESHOLD,
            ai_note_override=f"{ok_count} OK, {ng_count} NG document(s); folder confidence uses the lowest document score.",
        )
        result_payload.update({key: value for key, value in envelope.items() if key != "documents"})

        # Save final result
        final_result = FinalResult(
            job_id=job_id,
            queue_id=req.queue_id,
            overall_result=overall,
            processing_status=statuses.COMPLETED,
            ai_confidence=folder_confidence,
            ai_confidence_level=ConfidenceScore.level(folder_confidence),
            ai_note=result_payload["header"]["ai_note"],
            ai_return_status=overall,
            ai_return_cd=result_payload["AI_RETURN_CD"],
            ai_return_remark=(
                f"{ok_count} OK, {ng_count} NG, {error_count} errors" if error_count else "All documents processed"
            ),
            ai_return_confidence=folder_confidence,
            internal_result_json={
                "documents": result_payload["documents"],
                "summary": {
                    "total": len(doc_results),
                    "ok": ok_count,
                    "ng": ng_count,
                    "errors": error_count,
                },
            },
            processing_time_ms=duration_ms,
            published_at=finish_dt,
        )
        await self._result_repo.save_final(final_result)
        await self._job_repo.update_result(job_id, overall, statuses.COMPLETED, finish_dt, duration_ms)
        await self._result_repo.save_outbox_event(
            job_id=job_id,
            event_type="FINAL_RESULT",
            payload=result_payload,
            message_id=f"out-{req.queue_id}",
        )
        await self._job_repo.commit()

        await self._audit.log(job_id, req.queue_id, "worker", "result_published", after={"overall": overall})
        await msg.ack()
        logger.info("job_completed", queue_id=req.queue_id, doc_count=len(doc_results), overall=overall, ms=duration_ms)

    async def _process_single_document(
        self,
        req: NormalizedJobRequest,
        job_id: uuid.UUID,
        doc: NormalizedDocumentRequest,
        download_sem: asyncio.Semaphore,
    ) -> DocumentProcessingResult:
        doc_id = doc.external_document_id
        di = doc.document_index
        result = DocumentProcessingResult(
            document_index=di,
            external_document_id=doc_id,
            document_type=doc.document_type,
            processing_status=statuses.PROCESSING,
        )
        start = time.monotonic()
        try:
            # Download
            async with download_sem:
                file_content = await self._file_client.fetch(doc.file_url)

            # Validate
            doc_info = self._validator.validate(file_content, doc.file_name)
            ext = doc_info.get("extension", "")

            page_results_list: list[PageProcessingResult] = []
            ocr_results: list[dict] = []
            barcode_results: list[dict] = []
            raw_detections: list[dict[str, Any]] = []
            native_pages = self._ocr_engine.extract_pdf_pages(file_content) if ext == ".pdf" else []
            batches = (
                self._pdf_renderer.iter_batches(file_content, settings.PAGE_MICRO_BATCH_SIZE)
                if ext == ".pdf"
                else iter([[file_content]])
            )
            quality_image: bytes | None = None
            page_offset = 0

            for batch in batches:
                if quality_image is None and batch:
                    quality_image = batch[0]
                batch_detections = await self._yolo.detect_batch(batch)
                for detection in batch_detections:
                    detection["page_number"] = page_offset + detection.get("page_number", 1)
                raw_detections.extend(batch_detections)

                async def process_one_page(
                    image: bytes,
                    local_index: int,
                    batch_offset: int = page_offset,
                    page_detections: list[dict[str, Any]] = batch_detections,
                ) -> tuple[dict, dict]:
                    page_index = batch_offset + local_index
                    native = native_pages[page_index] if page_index < len(native_pages) else None
                    async with self._page_sem:
                        if native and native.get("text_layer_usable"):
                            ocr = {
                                "engine_name": "pymupdf",
                                "raw_text": native["raw_text"],
                                "tokens_json": native["tokens_json"],
                                "average_confidence": None,
                                "text_layer_detected": True,
                            }
                            needs_visual_ocr = getattr(self._field_extractor, "needs_visual_ocr", None)
                            if callable(needs_visual_ocr) and needs_visual_ocr(native, doc.document_type):
                                visual_ocr = await self._ocr_engine.run(image, extension=_page_ocr_extension(ext))
                                if (visual_ocr.get("raw_text") or "").strip():
                                    visual_ocr["engine_name"] = "pymupdf+" + visual_ocr.get("engine_name", "nemotron")
                                    visual_ocr["raw_text"] = f"{ocr['raw_text']}\n{visual_ocr['raw_text']}"
                                    visual_ocr["tokens_json"] = ocr["tokens_json"] + (
                                        visual_ocr.get("tokens_json", []) or []
                                    )
                                    ocr = visual_ocr
                        else:
                            ocr = await self._ocr_engine.run(image, extension=_page_ocr_extension(ext))
                        barcode = await self._barcode_chain.read(
                            image,
                            [
                                detection
                                for detection in page_detections
                                if detection.get("page_number") == local_index + 1
                                and detection.get("object_type") == "barcode"
                            ],
                        )
                    return ocr, barcode

                page_results = await asyncio.gather(
                    *(process_one_page(image, index) for index, image in enumerate(batch)),
                    return_exceptions=True,
                )
                for local_index, page_result in enumerate(page_results):
                    page_index = page_offset + local_index
                    page_number = page_index + 1
                    if isinstance(page_result, Exception):
                        ocr_res = {"engine_name": settings.OCR_PROVIDER, "raw_text": "", "average_confidence": None}
                        bc_res = {"barcode_found": False, "barcode_decoded": False}
                        error = str(page_result)
                    else:
                        ocr_res, bc_res = page_result
                        error = _ocr_error(ocr_res)
                    ocr_results.append(ocr_res)
                    barcode_results.append(bc_res)
                    native = native_pages[page_index] if page_index < len(native_pages) else {}
                    page_results_list.append(
                        PageProcessingResult(
                            page_index=page_index,
                            page_number=page_number,
                            processing_status=statuses.FAILED if error else statuses.COMPLETED,
                            processing_result=statuses.INTERNAL_ERROR if error else statuses.SUCCESS,
                            page_width_pt=native.get("page_width_pt"),
                            page_height_pt=native.get("page_height_pt"),
                            text_layer_detected=bool(native.get("text_layer_detected")),
                            ocr_raw_text=ocr_res.get("raw_text"),
                            ocr_engine=ocr_res.get("engine_name", settings.OCR_PROVIDER),
                            ocr_confidence=ocr_res.get("average_confidence"),
                            text_blocks=ocr_res.get("tokens_json", []),
                            quality_metrics=self._preprocessor.compute_quality(batch[local_index]),
                            detections=[d for d in raw_detections if d.get("page_number") == page_number],
                            barcodes=[bc_res],
                            errors=[{"stage": "PAGE", "error": error}] if error else [],
                        )
                    )
                page_offset += len(batch)

            result.pages = page_results_list
            result.quality_metrics = {
                "is_colored": bool(result.pages)
                and all(bool(page.quality_metrics and page.quality_metrics.get("is_colored")) for page in result.pages),
                "pages": [page.quality_metrics for page in result.pages],
            }

            # Aggregate OCR for field extraction
            visual_text = "\n".join(r.get("raw_text", "") or "" for r in ocr_results if r.get("raw_text"))
            all_text = visual_text
            ocr_errors = [err for err in (_ocr_error(r) for r in ocr_results) if err]
            ocr_aggregated = {
                "engine_name": (
                    ocr_results[0].get("engine_name", settings.OCR_PROVIDER) if ocr_results else settings.OCR_PROVIDER
                ),
                "raw_text": all_text,
                "tokens_json": [token for item in ocr_results for token in item.get("tokens_json", []) or []],
                "average_confidence": _average_confidence(ocr_results),
            }
            if ocr_errors:
                ocr_aggregated["error"] = ocr_errors[0]

            # Extract fields
            candidates = self._field_extractor.collect_document_candidates(ocr_results, doc.document_type)
            fields, reasoning = await self._field_reasoning.resolve(candidates, doc.document_type, ocr_results)
            result.financials = self._field_extractor.build_financials(candidates, fields)
            ocr_aggregated.update(
                {
                    "invoice_number": fields.get("document_number", {}).get("value"),
                    "billing_number": fields.get("billing_number", {}).get("value"),
                    "transaction_amount": fields.get("transaction_amount", {}).get("value"),
                    "transaction_date": fields.get("transaction_date", {}).get("value"),
                    "invoice_confidence": fields.get("document_number", {}).get("confidence"),
                    "billing_confidence": fields.get("billing_number", {}).get("confidence"),
                    "amount_confidence": fields.get("transaction_amount", {}).get("confidence"),
                    "date_confidence": fields.get("transaction_date", {}).get("confidence"),
                }
            )
            result.extracted_fields = [{"field_name": name, **field} for name, field in fields.items()]
            result.field_candidate_audit = self._field_extractor.build_candidate_audit(candidates, fields)
            result.reasoning = reasoning
            for page in result.pages:
                page.extracted_fields = [
                    field for field in result.extracted_fields if field.get("source_page_number", 1) == page.page_number
                ]

            # Business validation
            from app.domain.entities.ocr_result import OCRResult as OCREntity

            ocr_entity = OCREntity()
            ocr_entity.raw_text = ocr_aggregated.get("raw_text")
            ocr_entity.average_confidence = ocr_aggregated.get("average_confidence")
            ocr_entity.invoice_number = fields.get("document_number", {}).get("value")
            ocr_entity.transaction_amount = (
                fields.get("transaction_amount", {}).get("value") if fields.get("transaction_amount") else None
            )
            ocr_entity.vendor_name = fields.get("vendor_name", {}).get("value")
            ocr_entity.transaction_date = fields.get("transaction_date", {}).get("value")
            ocr_entity.invoice_confidence = fields.get("document_number", {}).get("confidence")
            ocr_entity.amount_confidence = fields.get("transaction_amount", {}).get("confidence")
            ocr_entity.date_confidence = fields.get("transaction_date", {}).get("confidence")

            det_entities = [map_to_entity(d) for d in raw_detections]
            aggregated = aggregate_per_object_type(det_entities)

            amount = fields.get("transaction_amount", {}).get("value") if fields.get("transaction_amount") else None

            bc_final = {"barcode_found": False, "barcode_decoded": False}
            for bc in barcode_results:
                if bc.get("barcode_decoded"):
                    bc_final = bc
                    break
                if bc.get("barcode_found") and not bc_final.get("barcode_found"):
                    bc_final = bc
            result.barcode_result = bc_final

            if doc.document_type in {DN, "DELIVERY_NOTE"}:
                validation = self._rule_evaluator.validate_delivery_note(
                    detections=det_entities, is_colored=result.quality_metrics["is_colored"]
                )
            else:
                validation = self._rule_evaluator.validate_invoice(
                    ocr=ocr_entity,
                    detections=list(aggregated.values()),
                    amount=amount,
                    confidence=None,
                    business_context=req.business_context,
                    barcode_result=bc_final,
                    is_colored=result.quality_metrics["is_colored"],
                    field_provenance=fields,
                )

            # Confidence
            total_conf = self._confidence_scorer.calculate(
                ocr_result=ocr_aggregated,
                detections=raw_detections,
                barcode_result=bc_final,
                document_info=doc_info,
                image_bytes=quality_image,
            )

            passed = validation.passed and total_conf >= settings.CONFIDENCE_THRESHOLD
            doc_result = statuses.OK if passed else statuses.NG
            result.document_result = doc_result
            result.detections = raw_detections
            result.detections_aggregated = {
                name: {"result": item.result, "confidence": item.confidence, "bounding_box": item.bounding_box}
                for name, item in aggregated.items()
            }
            result.validations = [
                {"rule_id": rule.rule_id, "rule_name": rule.rule_name, "result": "FAILED", "reason": rule.message}
                for rule in validation.failed_rules
            ]
            result.document_summary = await self._field_reasoning.summarize(doc_result, fields, result.validations)
            result.confidence = total_conf
            result.processing_status = statuses.FAILED if ocr_errors else statuses.COMPLETED
            result.processing_result = statuses.INTERNAL_ERROR if ocr_errors else statuses.SUCCESS
            if ocr_errors:
                result.errors.append({"stage": "OCR", "error": ocr_errors[0]})

        except DocumentError as e:
            result.processing_status = statuses.FAILED
            result.processing_result = statuses.DOCUMENT_ERROR
            result.document_result = statuses.NG
            result.errors.append({"stage": "VALIDATION", "error": str(e)})
        except Exception as e:
            logger.exception("document_processing_error", doc_id=doc_id)
            result.processing_status = statuses.FAILED
            result.processing_result = statuses.INTERNAL_ERROR
            result.errors.append({"stage": "PROCESSING", "error": str(e)})

        result.processing_time_ms = int((time.monotonic() - start) * 1000)
        return result

    async def _handle_job_error(
        self, req: NormalizedJobRequest, job_id: uuid.UUID, msg: AbstractIncomingMessage, reason: str
    ) -> None:
        retry_count = 0
        existing = await self._job_repo.get_by_id(job_id)
        if existing:
            retry_count = existing.retry_count
        if retry_count < settings.MAX_RETRY:
            await self._retry.send_to_retry(req.raw_payload or {}, retry_count + 1)
            await self._job_repo.increment_retry(job_id)
            await self._job_repo.update_status(job_id, statuses.FAILED_INTERNAL_ERROR)
            await self._audit.log(job_id, req.queue_id, "worker", "retry_scheduled", after={"retry": retry_count + 1})
            await self._job_repo.commit()
            await msg.ack()
        else:
            await self._publisher.publish(
                {
                    "QUEUE_ID": req.queue_id,
                    "AI_RETURN_STATUS": statuses.NG,
                    "AI_RETURN_CD": return_codes.DLQ_ERROR,
                    "AI_RETURN_REMARK": "Processing failed after retries.",
                    "AI_RETURN_CONFIDENCE": None,
                    "AI_SCAN_APP": req.source_system,
                }
            )
            await self._job_repo.update_result(job_id, statuses.NG, statuses.DLQ, datetime.utcnow(), 0)
            await self._audit.log(job_id, req.queue_id, "worker", "dlq_entered")
            await self._job_repo.commit()
            # ponytail: nack with requeue=false so RabbitMQ routes to DLX→DLQ
            await msg.nack(requeue=False)
