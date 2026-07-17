import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from app.application.dto.request_normalizer import normalize_request
from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.field_extraction_service import FieldExtractionService
from app.domain.entities.final_result import FinalResult
from app.domain.entities.ai_job import AIJob as AIJobEntity
from app.domain.entities.normalized_request import (
    DocumentProcessingResult,
    NormalizedDocumentRequest,
    NormalizedJobRequest,
    PageProcessingResult,
)
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.audit_log_postgres_repository import AuditLogPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.detection.detection_mapper import aggregate_per_object_type, map_to_entity
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.document_converter.word_converter import WordConverter
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
        word_converter: WordConverter,
        preprocessor: ImagePreprocessor,
        ocr_engine: DocumentOCR,
        yolo: YOLOAdapter,
        barcode_chain: BarcodeFallbackChain,
        validator: DocumentValidator,
        field_extractor: FieldExtractionService,
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
        self._word_converter = word_converter
        self._preprocessor = preprocessor
        self._ocr_engine = ocr_engine
        self._yolo = yolo
        self._barcode_chain = barcode_chain
        self._validator = validator
        self._field_extractor = field_extractor
        self._rule_evaluator = rule_evaluator
        self._confidence_scorer = confidence_scorer

    async def process(self, payload: dict[str, Any], msg: AbstractIncomingMessage) -> None:
        normalized = normalize_request(payload)
        job_id = uuid.uuid4()
        async with log_context(
            job_id=str(job_id), queue_id=normalized.queue_id,
            message_id=normalized.message_id, source=normalized.source_system,
        ):
            try:
                await self._process_job(normalized, job_id, msg)
            except Exception as e:
                logger.exception("pipeline_unhandled_error")
                await self._handle_job_error(normalized, job_id, msg, str(e))

    async def _process_job(self, req: NormalizedJobRequest, job_id: uuid.UUID, msg: AbstractIncomingMessage) -> None:
        start_dt = datetime.utcnow()
        first_doc = req.documents[0] if req.documents else None
        await self._job_repo.save(AIJobEntity(
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
            original_payload={key: value for key, value in (req.raw_payload or {}).items() if key != "_raw_body"},
            request_datetime=start_dt,
            start_datetime=start_dt,
        ))
        await self._audit.log(job_id, req.queue_id, "worker", "job_accepted", after={"doc_count": len(req.documents)})

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
                doc_results.append(DocumentProcessingResult(
                    document_index=-1, external_document_id="unknown",
                    document_type="unknown", processing_status=statuses.FAILED,
                    processing_result=statuses.INTERNAL_ERROR,
                ))

        # Sort by document_index for deterministic output
        doc_results.sort(key=lambda r: r.document_index)

        # Aggregate job results
        ok_count = sum(1 for d in doc_results if d.document_result == statuses.OK)
        ng_count = sum(1 for d in doc_results if d.document_result == statuses.NG)
        error_count = sum(
            1
            for d in doc_results
            if d.processing_result in (statuses.INTERNAL_ERROR, statuses.DOCUMENT_ERROR)
        )
        overall = statuses.OK if ok_count == len(doc_results) and error_count == 0 else statuses.NG

        finish_dt = datetime.utcnow()
        duration_ms = int((finish_dt - start_dt).total_seconds() * 1000)

        # Build result payload
        result_payload: dict[str, Any] = {
            "schema_version": "0.2.0",
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
            "AI_RETURN_CONFIDENCE": None,
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
                "confidence": dr.confidence,
                "fields": dr.extracted_fields,
                "detections": dr.detections,
                "validation": dr.validations,
                "pages": [
                    {
                        "page_index": p.page_index,
                        "page_number": p.page_number,
                        "processing_status": p.processing_status,
                        "processing_result": p.processing_result,
                        "ocr_raw_text": p.ocr_raw_text,
                        "ocr_engine": p.ocr_engine,
                        "ocr_confidence": p.ocr_confidence,
                        "text_blocks": p.text_blocks,
                        "detections": p.detections,
                        "barcodes": p.barcodes,
                        "extracted_fields": p.extracted_fields,
                        "errors": p.errors,
                    }
                    for p in dr.pages
                ],
                "errors": dr.errors,
            }
            result_payload["documents"].append(doc_entry)

        # Save final result
        final_result = FinalResult(
            job_id=job_id, queue_id=req.queue_id,
            overall_result=overall, processing_status=statuses.COMPLETED,
            ai_confidence=None, ai_confidence_level=None, ai_note=f"Processed {len(doc_results)} documents",
            ai_return_status=overall, ai_return_cd=result_payload["AI_RETURN_CD"],
            ai_return_remark=(
                f"{ok_count} OK, {ng_count} NG, {error_count} errors"
                if error_count
                else "All documents processed"
            ),
            ai_return_confidence=None,
            internal_result_json={
                "documents": result_payload["documents"],
                "summary": {
                    "total": len(doc_results),
                    "ok": ok_count,
                    "ng": ng_count,
                    "errors": error_count,
                },
            },
            processing_time_ms=duration_ms, published_at=finish_dt,
        )
        await self._result_repo.save_final(final_result)
        await self._job_repo.update_result(job_id, overall, statuses.COMPLETED, finish_dt, duration_ms)
        await self._result_repo.save_outbox_event(
            job_id=job_id, event_type="FINAL_RESULT",
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
            document_index=di, external_document_id=doc_id,
            document_type=doc.document_type, processing_status=statuses.PROCESSING,
        )
        start = time.monotonic()
        try:
            # Download
            async with download_sem:
                file_content = await self._file_client.fetch(doc.file_url)

            # Validate
            doc_info = self._validator.validate(file_content, doc.file_name)
            ext = doc_info.get("extension", "")

            native_text_result: dict[str, Any] = {}
            if ext == ".pdf":
                native_text_result = await self._ocr_engine.run(file_content, extension=".pdf")

            # Render
            page_images: list[bytes] = []
            if ext == ".pdf":
                page_images = self._pdf_renderer.render(file_content)
            elif ext in (".doc", ".docx"):
                pdf_content = await self._word_converter.convert_to_pdf(file_content, doc.file_name)
                page_images = self._pdf_renderer.render(pdf_content)
            else:
                page_images = [file_content]

            preprocessed = [self._preprocessor.preprocess(img) for img in page_images]

            # ponytail: local input_size override, not mutating global settings
            raw_detections = await self._yolo.detect_batch(page_images)
            if not raw_detections and page_images:
                raw_detections = await self._yolo.detect_batch(page_images, input_size=960)

            # Page processing: OCR + barcode with concurrency limit
            page_sem = asyncio.Semaphore(settings.MAX_PARALLEL_PAGES)

            async def process_one_page(image: bytes, pp_img: bytes, idx: int) -> tuple[dict, dict]:
                async with page_sem:
                    ocr = await self._ocr_engine.run(image, extension=_page_ocr_extension(ext))
                    if not (ocr.get("raw_text") or "").strip() and pp_img != image:
                        fallback = await self._ocr_engine.run(pp_img, extension=_page_ocr_extension(ext))
                        if (fallback.get("raw_text") or "").strip():
                            ocr = fallback
                    bc = await self._barcode_chain.read(pp_img)
                    return ocr, bc

            page_tasks = [process_one_page(page_images[i], pp, i) for i, pp in enumerate(preprocessed)]
            page_results = await asyncio.gather(*page_tasks, return_exceptions=True)

            page_results_list: list[PageProcessingResult] = []
            ocr_results: list[dict] = []
            barcode_results: list[dict] = []

            for i, pr in enumerate(page_results):
                if isinstance(pr, Exception):
                    page_results_list.append(PageProcessingResult(
                        page_index=i, page_number=i + 1,
                        processing_status=statuses.FAILED,
                        processing_result=statuses.INTERNAL_ERROR,
                        errors=[{"stage": "PAGE", "error": str(pr)}],
                    ))
                    ocr_results.append({
                        "engine_name": settings.OCR_PROVIDER,
                        "raw_text": "",
                        "average_confidence": 0.0,
                    })
                    barcode_results.append({"barcode_found": False, "barcode_decoded": False})
                else:
                    ocr_res, bc_res = pr
                    ocr_results.append(ocr_res)
                    barcode_results.append(bc_res)
                    ocr_err = _ocr_error(ocr_res)
                    page_results_list.append(PageProcessingResult(
                        page_index=i, page_number=i + 1,
                        processing_status=statuses.FAILED if ocr_err else statuses.COMPLETED,
                        processing_result=statuses.INTERNAL_ERROR if ocr_err else statuses.SUCCESS,
                        ocr_raw_text=ocr_res.get("raw_text"),
                        ocr_engine=ocr_res.get("engine_name", settings.OCR_PROVIDER),
                        ocr_confidence=ocr_res.get("average_confidence"),
                        text_blocks=ocr_res.get("tokens_json", []),
                        detections=[
                            d for d in raw_detections if d.get("page_number", 1) == i + 1
                        ],
                        barcodes=[bc_res],
                        errors=[{"stage": "OCR", "error": ocr_err}] if ocr_err else [],
                    ))

            result.pages = page_results_list

            # Aggregate OCR for field extraction
            visual_text = "\n".join(r.get("raw_text", "") or "" for r in ocr_results if r.get("raw_text"))
            all_text = _merge_ocr_text(native_text_result.get("raw_text", "") or "", visual_text)
            ocr_errors = [] if native_text_result.get("raw_text", "").strip() else [err for err in (_ocr_error(r) for r in ocr_results) if err]
            ocr_aggregated = {
                "engine_name": (
                    ocr_results[0].get("engine_name", settings.OCR_PROVIDER)
                    if ocr_results
                    else settings.OCR_PROVIDER
                ),
                "raw_text": all_text,
                "tokens_json": [token for item in ocr_results for token in item.get("tokens_json", []) or []],
                "average_confidence": (
                    sum(r.get("average_confidence", 0) or 0 for r in ocr_results)
                    / max(len(ocr_results), 1)
                ),
            }
            if ocr_errors:
                ocr_aggregated["error"] = ocr_errors[0]

            # Extract fields
            fields = ocr_aggregated.get("fields_json") or self._field_extractor.extract_from_ocr(ocr_aggregated)
            for field in fields.values():
                field.setdefault("source_page_number", 1)
            result.extracted_fields = [
                {"field_name": name, **field} for name, field in fields.items()
            ]
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
                fields.get("transaction_amount", {}).get("value")
                if fields.get("transaction_amount")
                else None
            )

            det_entities = [map_to_entity(d) for d in raw_detections]
            aggregated = aggregate_per_object_type(det_entities)

            amount = (
                fields.get("transaction_amount", {}).get("value")
                if fields.get("transaction_amount")
                else None
            )

            if doc.document_type in {DN, "DELIVERY_NOTE"}:
                validation = self._rule_evaluator.validate_delivery_note(detections=det_entities)
            else:
                validation = self._rule_evaluator.validate_invoice(
                    ocr=ocr_entity, detections=list(aggregated.values()),
                    amount=amount, confidence=ocr_aggregated.get("average_confidence"),
                )

            # Take first barcode
            bc_final = {"barcode_found": False, "barcode_decoded": False}
            for bc in barcode_results:
                if bc.get("barcode_decoded"):
                    bc_final = bc
                    break
                if bc.get("barcode_found") and not bc_final.get("barcode_found"):
                    bc_final = bc
            result.barcode_result = bc_final

            # Confidence
            total_conf = self._confidence_scorer.calculate(
                ocr_result=ocr_aggregated, detections=raw_detections,
                barcode_result=bc_final, document_info=doc_info,
                image_bytes=preprocessed[0] if preprocessed else None,
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
            await self._publisher.publish({
                "QUEUE_ID": req.queue_id,
                "AI_RETURN_STATUS": statuses.NG,
                "AI_RETURN_CD": return_codes.DLQ_ERROR,
                "AI_RETURN_REMARK": "Processing failed after retries.",
                "AI_RETURN_CONFIDENCE": None,
                "AI_SCAN_APP": req.source_system,
            })
            await self._job_repo.update_result(job_id, statuses.NG, statuses.DLQ, datetime.utcnow(), 0)
            await self._audit.log(job_id, req.queue_id, "worker", "dlq_entered")
            await self._job_repo.commit()
            # ponytail: nack with requeue=false so RabbitMQ routes to DLX→DLQ
            await msg.nack(requeue=False)


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
