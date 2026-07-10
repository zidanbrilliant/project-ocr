import time
import uuid
from datetime import datetime
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from app.application.dto.input_payload_dto import InputPayloadDTO
from app.application.services.ai_notes_service import AINotesService
from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.document_error_builder import build_document_error_result
from app.application.services.field_extraction_service import FieldExtractionService
from app.domain.entities.business_validation_result import BusinessValidationResult, FailedRule
from app.domain.entities.final_result import FinalResult
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.domain.services.remark_policy import RemarkPolicy
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.audit_log_postgres_repository import AuditLogPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.detection.detection_fallback import DetectionFallback
from app.infrastructure.detection.detection_mapper import aggregate_per_object_type, map_to_entity
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.document_converter.word_converter import WordConverter
from app.infrastructure.ocr.ocr_fallback_chain import OCRFallbackChain
from app.infrastructure.ocr.paddleocr_vl_adapter import PaddleOCRVLAdapter
from app.infrastructure.rabbitmq.publisher import ResultPublisher
from app.infrastructure.rabbitmq.retry import RetryHandler
from app.infrastructure.storage.image_server_client import ImageServerClient
from app.infrastructure.storage.temp_file_manager import TempFileManager
from app.shared.config.settings import settings
from app.shared.constants import return_codes, statuses
from app.shared.exceptions.base import DocumentError, InternalProcessingError
from app.shared.logging.log_context import log_context
from app.shared.logging.logger import get_logger
from app.shared.utils.hash import build_idempotency_key
from app.shared.utils.id_generator import generate_job_id, generate_queue_id

logger = get_logger(__name__)


class AIPipelineOrchestrator:
    def __init__(
        self,
        job_repo: AIJobPostgresRepository,
        result_repo: ResultPostgresRepository,
        audit: AuditLogPostgresRepository,
        publisher: ResultPublisher,
        retry_handler: RetryHandler,
        file_client: ImageServerClient,
        temp_mgr: TempFileManager,
        pdf_renderer: PDFRenderer,
        word_converter: WordConverter,
        preprocessor: ImagePreprocessor,
        ocr_chain: OCRFallbackChain,
        yolo: YOLOAdapter,
        detection_fallback: DetectionFallback,
        barcode_chain: BarcodeFallbackChain,
        validator: DocumentValidator,
        field_extractor: FieldExtractionService,
        rule_evaluator: BusinessRuleEvaluator,
        confidence_scorer: ConfidenceScoringService,
        notes_service: AINotesService,
        remark_policy: RemarkPolicy,
    ) -> None:
        self._job_repo = job_repo
        self._result_repo = result_repo
        self._audit = audit
        self._publisher = publisher
        self._retry = retry_handler
        self._file_client = file_client
        self._temp_mgr = temp_mgr
        self._pdf_renderer = pdf_renderer
        self._word_converter = word_converter
        self._preprocessor = preprocessor
        self._ocr_chain = ocr_chain
        self._yolo = yolo
        self._detection_fallback = detection_fallback
        self._barcode_chain = barcode_chain
        self._validator = validator
        self._field_extractor = field_extractor
        self._rule_evaluator = rule_evaluator
        self._confidence_scorer = confidence_scorer
        self._notes_service = notes_service
        self._remark_policy = remark_policy

    async def process(self, payload: dict[str, Any], msg: AbstractIncomingMessage) -> None:
        job_id = uuid.uuid4()
        queue_id = payload.get("QUEUE_ID") or generate_queue_id()
        doc_no = payload.get("DOC_NO", "unknown")

        async with log_context(job_id=str(job_id), queue_id=queue_id, doc_no=doc_no):
            try:
                await self._process_internal(payload, job_id, queue_id, msg)
            except Exception as e:
                logger.exception("pipeline_unhandled_error")
                await self._handle_internal_error(payload, job_id, queue_id, msg, str(e))

    async def _process_internal(
        self, payload: dict[str, Any], job_id: uuid.UUID, queue_id: str, msg: AbstractIncomingMessage
    ) -> None:
        dto = InputPayloadDTO(**payload)
        idempotency_key = build_idempotency_key(dto.DOC_NO, dto.DOC_TYPE, dto.DOC_SEQ, dto.FILE_NM, dto.PATH_FILE)

        existing = await self._job_repo.get_by_idempotency_key(idempotency_key)
        if existing and existing.processing_status in (statuses.COMPLETED, statuses.DLQ):
            existing_result = await self._result_repo.get_by_job_id(existing.job_id)
            if existing_result and existing_result.rabbitmq_result_payload:
                await self._publisher.publish(existing_result.rabbitmq_result_payload)
            await msg.ack()
            return

        job = self._create_job(job_id, queue_id, dto, idempotency_key, payload)
        await self._job_repo.save(job)
        await self._audit.log(job_id, queue_id, "worker", "job_created")

        start_dt = datetime.utcnow()
        try:
            file_content = await self._file_client.fetch(dto.PATH_FILE)
            await self._audit.log(job_id, queue_id, "worker", "document_downloaded")

            doc_info = self._validator.validate(file_content, dto.FILE_NM)

            ext = doc_info.get("extension", "")
            page_images: list[bytes] = []
            if ext == ".pdf":
                page_images = self._pdf_renderer.render(file_content)
            elif ext in (".doc", ".docx"):
                pdf_content = await self._word_converter.convert_to_pdf(file_content, dto.FILE_NM)
                page_images = self._pdf_renderer.render(pdf_content)
            else:
                page_images = [file_content]

            preprocessed = [self._preprocessor.preprocess(img) for img in page_images]

            best_page = preprocessed[0] if preprocessed else b""
            ocr_result = await self._ocr_chain.run(preprocessed[0] if preprocessed else file_content, preprocessed[0] if preprocessed else None)
            await self._audit.log(job_id, queue_id, "worker", "ocr_completed", after={"engine": ocr_result.get("engine_name")})

            raw_detections = await self._detection_fallback.run_with_fallback(best_page or page_images[0])
            detections = [map_to_entity(d) for d in raw_detections]
            aggregated = aggregate_per_object_type(detections)
            await self._audit.log(job_id, queue_id, "worker", "detection_completed")

            barcode_result = await self._barcode_chain.read(best_page or page_images[0])
            await self._audit.log(job_id, queue_id, "worker", "barcode_completed")

            doc_pk = await self._result_repo.save_document(job_id, {
                "document_id": "DOC-001",
                "document_name": dto.FILE_NM,
                "document_type": dto.DOC_TYPE,
                "file_extension": ext,
                "file_size_bytes": doc_info.get("size_bytes"),
                "page_count": doc_info.get("page_count"),
                "readable": True,
                "validation_status": "VALID",
            })

            await self._job_repo.update_status(job_id, statuses.RUNNING_BUSINESS_VALIDATION)

            fields = ocr_result.get("fields_json") or self._field_extractor.extract_from_ocr(ocr_result)

            amount = None
            if fields.get("transaction_amount"):
                amount = fields["transaction_amount"].get("value")

            validation = self._rule_evaluator.validate_invoice(
                ocr=self._ocr_entity(ocr_result),
                detections=list(aggregated.values()),
                amount=amount,
                confidence=ocr_result.get("average_confidence"),
            )

            barcode_decoded = barcode_result.get("barcode_decoded", False)
            barcode_found = barcode_result.get("barcode_found", False)
            barcode_conf = 100.0 if barcode_decoded else (70.0 if barcode_found else 0.0)

            total_confidence = self._confidence_scorer.calculate(
                ocr_result=ocr_result,
                detections=raw_detections,
                barcode_result=barcode_result,
                document_info=doc_info,
                image_bytes=best_page or page_images[0] if page_images else None,
            )

            passed = validation.passed and total_confidence >= settings.CONFIDENCE_THRESHOLD
            overall = statuses.OK if passed else statuses.NG
            remark = self._notes_service.generate_remark(validation)

            finish_dt = datetime.utcnow()
            duration_ms = int((finish_dt - start_dt).total_seconds() * 1000)

            final_result = FinalResult(
                job_id=job_id,
                queue_id=queue_id,
                overall_result=overall,
                processing_status=statuses.COMPLETED,
                ai_confidence=total_confidence,
                ai_confidence_level=self._confidence_scorer.confidence_level(total_confidence),
                ai_note=remark,
                ai_return_status=overall,
                ai_return_cd=return_codes.SUCCESS,
                ai_return_remark=remark,
                ai_return_confidence=self._confidence_scorer.confidence_to_int(total_confidence),
                processing_time_ms=duration_ms,
                published_at=finish_dt,
            )

            rabbit_payload = {
                "QUEUE_ID": queue_id,
                "DOC_NO": dto.DOC_NO,
                "DOC_TYPE": dto.DOC_TYPE,
                "DOC_SEQ": dto.DOC_SEQ,
                "TRANS_TYPE_CD": dto.TRANS_TYPE_CD,
                "FILE_NM": dto.FILE_NM,
                "AI_SCAN_APP": dto.AI_SCAN_APP,
                "AI_RETURN_STATUS": overall,
                "AI_RETURN_REMARK": remark,
                "AI_RETURN_CD": return_codes.SUCCESS,
                "AI_RETURN_CONFIDENCE": self._confidence_scorer.confidence_to_int(total_confidence),
            }
            final_result.rabbitmq_result_payload = rabbit_payload

            await self._result_repo.save_final(final_result)
            await self._job_repo.update_result(job_id, overall, statuses.COMPLETED, finish_dt, duration_ms)
            await self._result_repo.save_ocr(job_id, doc_pk, ocr_result)
            for d in raw_detections:
                await self._result_repo.save_detection(job_id, doc_pk, d)
            await self._result_repo.save_barcode(job_id, doc_pk, barcode_result)

            await self._publisher.publish(rabbit_payload)
            await self._audit.log(job_id, queue_id, "worker", "result_published")

            await msg.ack()
            logger.info("job_completed", overall_result=overall, confidence=total_confidence, ms=duration_ms)

        except DocumentError as e:
            await self._handle_document_error(payload, job_id, queue_id, msg, str(e))
        except InternalProcessingError as e:
            await self._handle_internal_error(payload, job_id, queue_id, msg, str(e))

    async def _handle_document_error(
        self, payload: dict[str, Any], job_id: uuid.UUID, queue_id: str, msg: AbstractIncomingMessage, reason: str
    ) -> None:
        result = build_document_error_result(payload, reason)
        await self._result_repo.save_final(FinalResult(
            job_id=job_id, queue_id=queue_id,
            overall_result=statuses.NG, processing_status=statuses.FAILED_DOCUMENT_ERROR,
            ai_confidence=None, ai_confidence_level=None, ai_note=reason,
            ai_return_status=statuses.NG, ai_return_cd=return_codes.DOCUMENT_ERROR,
            ai_return_remark=reason, ai_return_confidence=None,
        ))
        await self._job_repo.update_result(job_id, statuses.NG, statuses.FAILED_DOCUMENT_ERROR, datetime.utcnow(), 0)
        await self._publisher.publish(result)
        await self._audit.log(job_id, queue_id, "worker", "document_error", after={"reason": reason})
        await msg.ack()

    async def _handle_internal_error(
        self, payload: dict[str, Any], job_id: uuid.UUID, queue_id: str, msg: AbstractIncomingMessage, reason: str
    ) -> None:
        retry_count = 0
        existing = await self._job_repo.get_by_id(job_id)
        if existing:
            retry_count = existing.retry_count

        if self._retry.should_retry(retry_count):
            await self._retry.send_to_retry(payload, retry_count + 1)
            await self._job_repo.increment_retry(job_id)
            await self._job_repo.update_status(job_id, statuses.FAILED_INTERNAL_ERROR)
            await self._audit.log(job_id, queue_id, "worker", "retry_scheduled", after={"retry": retry_count + 1})
            await msg.ack()
        else:
            dlq_result = {
                "QUEUE_ID": queue_id, "DOC_NO": payload.get("DOC_NO", ""),
                "DOC_TYPE": payload.get("DOC_TYPE", ""), "DOC_SEQ": payload.get("DOC_SEQ", 0),
                "TRANS_TYPE_CD": payload.get("TRANS_TYPE_CD", ""), "FILE_NM": payload.get("FILE_NM", ""),
                "AI_SCAN_APP": payload.get("AI_SCAN_APP", "VISION"),
                "AI_RETURN_STATUS": statuses.NG,
                "AI_RETURN_REMARK": "Document could not be processed, please contact support.",
                "AI_RETURN_CD": return_codes.DLQ_ERROR, "AI_RETURN_CONFIDENCE": None,
            }
            await self._result_repo.save_final(FinalResult(
                job_id=job_id, queue_id=queue_id,
                overall_result=statuses.NG, processing_status=statuses.DLQ,
                ai_confidence=None, ai_confidence_level=None, ai_note=reason,
                ai_return_status=statuses.NG, ai_return_cd=return_codes.DLQ_ERROR,
                ai_return_remark=dlq_result["AI_RETURN_REMARK"], ai_return_confidence=None,
            ))
            await self._job_repo.update_result(job_id, statuses.NG, statuses.DLQ, datetime.utcnow(), 0)
            await self._publisher.publish(dlq_result)
            await self._audit.log(job_id, queue_id, "worker", "dlq_entered")
            await msg.ack()

    def _create_job(
        self, job_id: uuid.UUID, queue_id: str, dto: InputPayloadDTO, idempotency_key: str, raw_payload: dict[str, Any]
    ) -> Any:
        from app.domain.entities.ai_job import AIJob
        return AIJob(
            job_id=job_id,
            queue_id=queue_id,
            idempotency_key=idempotency_key,
            doc_no=dto.DOC_NO,
            doc_type=dto.DOC_TYPE,
            doc_seq=dto.DOC_SEQ,
            trans_type_cd=dto.TRANS_TYPE_CD,
            file_nm=dto.FILE_NM,
            ai_scan_app=dto.AI_SCAN_APP,
            path_file=dto.PATH_FILE,
            original_payload=raw_payload,
            request_datetime=datetime.utcnow(),
            start_datetime=datetime.utcnow(),
            processing_status=statuses.RECEIVED,
        )

    def _ocr_entity(self, ocr_result: dict[str, Any]) -> Any:
        from app.domain.entities.ocr_result import OCRResult
        r = OCRResult()
        r.raw_text = ocr_result.get("raw_text")
        r.average_confidence = ocr_result.get("average_confidence")
        r.invoice_number = ocr_result.get("invoice_number")
        r.billing_number = ocr_result.get("billing_number")
        r.transaction_amount = ocr_result.get("transaction_amount")
        r.invoice_confidence = ocr_result.get("invoice_confidence")
        r.billing_confidence = ocr_result.get("billing_confidence")
        r.amount_confidence = ocr_result.get("amount_confidence")
        r.engine_name = ocr_result.get("engine_name", "paddleocr_vl")
        return r
