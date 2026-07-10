import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.final_result import FinalResult
from app.infrastructure.database.models import (
    AIBarcodeResult,
    AIBusinessValidationResult,
    AIDetectionResult,
    AIDocument,
    AIDocumentSummary,
    AIDuplicateCheckResult,
    AIErrorLog,
    AIFinalResult,
    AIOCRResult,
)


class ResultPostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_final(self, result: FinalResult) -> None:
        model = AIFinalResult(
            job_id=result.job_id,
            queue_id=result.queue_id,
            overall_result=result.overall_result,
            processing_status=result.processing_status,
            ai_confidence=result.ai_confidence,
            ai_confidence_level=result.ai_confidence_level,
            ai_note=result.ai_note,
            ai_return_status=result.ai_return_status,
            ai_return_cd=result.ai_return_cd,
            ai_return_remark=result.ai_return_remark,
            ai_return_confidence=result.ai_return_confidence,
            internal_result_json=result.internal_result_json,
            rabbitmq_result_payload=result.rabbitmq_result_payload,
            processing_time_ms=result.processing_time_ms,
            published_at=result.published_at,
        )
        self._session.add(model)

    async def get_by_job_id(self, job_id: uuid.UUID) -> FinalResult | None:
        stmt = select(AIFinalResult).where(AIFinalResult.job_id == job_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_final_entity(model) if model else None

    async def get_by_queue_id(self, queue_id: str) -> FinalResult | None:
        stmt = select(AIFinalResult).where(AIFinalResult.queue_id == queue_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_final_entity(model) if model else None

    async def save_ocr(self, job_id: uuid.UUID, document_pk: uuid.UUID, data: dict[str, Any]) -> None:
        model = AIOCRResult(
            job_id=job_id,
            document_pk=document_pk,
            page_number=data.get("page_number", 1),
            engine_name=data.get("engine_name", "paddleocr_vl"),
            engine_version=data.get("engine_version"),
            raw_text=data.get("raw_text"),
            tokens_json=data.get("tokens_json"),
            fields_json=data.get("fields_json"),
            average_confidence=data.get("average_confidence"),
            processing_time_ms=data.get("processing_time_ms"),
        )
        self._session.add(model)

    async def save_detection(self, job_id: uuid.UUID, document_pk: uuid.UUID, data: dict[str, Any]) -> None:
        model = AIDetectionResult(
            job_id=job_id,
            document_pk=document_pk,
            page_number=data.get("page_number", 1),
            model_name=data.get("model_name", "toyota-document-yolo"),
            model_version=data.get("model_version", ""),
            object_type=data.get("object_type", ""),
            result=data.get("result", "NG"),
            required=data.get("required", False),
            confidence=data.get("confidence"),
            bounding_box=data.get("bounding_box"),
            crop_uri=data.get("crop_uri"),
            detected_colour=data.get("detected_colour"),
            reason=data.get("reason"),
            attributes=data.get("attributes"),
        )
        self._session.add(model)

    async def save_barcode(self, job_id: uuid.UUID, document_pk: uuid.UUID, data: dict[str, Any]) -> None:
        model = AIBarcodeResult(
            job_id=job_id,
            document_pk=document_pk,
            page_number=data.get("page_number", 1),
            required=data.get("required", False),
            barcode_found=data.get("barcode_found", False),
            barcode_decoded=data.get("barcode_decoded", False),
            result=data.get("result", "NG"),
            barcode_value=data.get("barcode_value"),
            barcode_type=data.get("barcode_type"),
            barcode_confidence=data.get("barcode_confidence"),
            bounding_box=data.get("bounding_box"),
            decoder_name=data.get("decoder_name"),
            reason=data.get("reason"),
        )
        self._session.add(model)

    async def save_validation(self, job_id: uuid.UUID, document_pk: uuid.UUID | None, data: dict[str, Any]) -> None:
        model = AIBusinessValidationResult(
            job_id=job_id,
            document_pk=document_pk,
            document_type=data.get("document_type"),
            rule_code=data.get("rule_code", ""),
            rule_name=data.get("rule_name", ""),
            rule_description=data.get("rule_description"),
            result=data.get("result", "NG"),
            required_evidence=data.get("required_evidence"),
            reason=data.get("reason"),
            rule_config_snapshot=data.get("rule_config_snapshot", {}),
        )
        self._session.add(model)

    async def save_document(self, job_id: uuid.UUID, data: dict[str, Any]) -> uuid.UUID:
        model = AIDocument(
            job_id=job_id,
            document_id=data.get("document_id", "DOC-001"),
            document_name=data.get("document_name", ""),
            document_type=data.get("document_type", "INVOICE"),
            document_category=data.get("document_category"),
            file_extension=data.get("file_extension", ""),
            content_type=data.get("content_type"),
            file_size_bytes=data.get("file_size_bytes"),
            page_count=data.get("page_count"),
            image_width=data.get("image_width"),
            image_height=data.get("image_height"),
            checksum_sha256=data.get("checksum_sha256"),
            readable=data.get("readable", False),
            validation_status=data.get("validation_status", "INVALID"),
            validation_errors=data.get("validation_errors"),
        )
        self._session.add(model)
        await self._session.flush()
        return model.id

    async def save_summary(self, job_id: uuid.UUID, document_pk: uuid.UUID, data: dict[str, Any]) -> None:
        model = AIDocumentSummary(
            job_id=job_id,
            document_pk=document_pk,
            result=data.get("result", "NG"),
            total_validation=data.get("total_validation", 0),
            passed_validation=data.get("passed_validation", 0),
            failed_validation=data.get("failed_validation", 0),
            failed_items=data.get("failed_items"),
            reason=data.get("reason", ""),
            recommendation=data.get("recommendation"),
            ai_note=data.get("ai_note"),
        )
        self._session.add(model)

    async def save_duplicate_check(self, job_id: uuid.UUID, document_pk: uuid.UUID, data: dict[str, Any]) -> None:
        model = AIDuplicateCheckResult(
            job_id=job_id,
            document_pk=document_pk,
            result=data.get("result", "OK"),
            confidence=data.get("confidence"),
            matched_document=data.get("matched_document"),
            matched_pv=data.get("matched_pv"),
            matched_date=data.get("matched_date"),
            reason=data.get("reason"),
            lookup_window_months=data.get("lookup_window_months"),
            evidence_json=data.get("evidence_json"),
        )
        self._session.add(model)

    def _to_final_entity(self, model: AIFinalResult) -> FinalResult:
        return FinalResult(
            job_id=model.job_id,
            queue_id=model.queue_id,
            overall_result=model.overall_result,
            processing_status=model.processing_status,
            ai_confidence=float(model.ai_confidence) if model.ai_confidence is not None else None,
            ai_confidence_level=model.ai_confidence_level,
            ai_note=model.ai_note,
            ai_return_status=model.ai_return_status,
            ai_return_cd=model.ai_return_cd,
            ai_return_remark=model.ai_return_remark,
            ai_return_confidence=model.ai_return_confidence,
            internal_result_json=model.internal_result_json,
            rabbitmq_result_payload=model.rabbitmq_result_payload,
            processing_time_ms=model.processing_time_ms,
            published_at=model.published_at,
        )
