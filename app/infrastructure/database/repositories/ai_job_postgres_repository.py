import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.ai_job import AIJob as AIJobEntity
from app.infrastructure.database.models import AIJob as AIJobModel


class AIJobPostgresRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, job: AIJobEntity) -> None:
        model = AIJobModel(
            id=job.job_id,
            queue_id=job.queue_id,
            idempotency_key=job.idempotency_key,
            doc_no=job.doc_no,
            doc_type=job.doc_type,
            doc_seq=job.doc_seq,
            trans_type_cd=job.trans_type_cd,
            file_nm=job.file_nm,
            ai_scan_app=job.ai_scan_app,
            path_file=job.path_file,
            processing_status=job.processing_status,
            retry_count=job.retry_count,
            original_payload=job.original_payload,
            request_datetime=job.request_datetime,
            start_datetime=job.start_datetime,
        )
        self._session.add(model)

    async def get_by_id(self, job_id: uuid.UUID) -> AIJobEntity | None:
        stmt = select(AIJobModel).where(AIJobModel.id == job_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_queue_id(self, queue_id: str) -> AIJobEntity | None:
        stmt = select(AIJobModel).where(AIJobModel.queue_id == queue_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_idempotency_key(self, key: str) -> AIJobEntity | None:
        stmt = select(AIJobModel).where(AIJobModel.idempotency_key == key)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def update_status(self, job_id: uuid.UUID, status: str) -> None:
        stmt = (
            update(AIJobModel)
            .where(AIJobModel.id == job_id)
            .values(processing_status=status, updated_at=datetime.utcnow())
        )
        await self._session.execute(stmt)

    async def update_result(
        self,
        job_id: uuid.UUID,
        result: str | None,
        status: str,
        finish_dt: datetime,
        duration_ms: int,
    ) -> None:
        stmt = (
            update(AIJobModel)
            .where(AIJobModel.id == job_id)
            .values(
                overall_result=result,
                processing_status=status,
                finish_datetime=finish_dt,
                duration_ms=duration_ms,
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)

    async def increment_retry(self, job_id: uuid.UUID) -> None:
        stmt = (
            update(AIJobModel)
            .where(AIJobModel.id == job_id)
            .values(
                retry_count=AIJobModel.retry_count + 1,
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)

    def _to_entity(self, model: AIJobModel) -> AIJobEntity:
        return AIJobEntity(
            job_id=model.id,
            queue_id=model.queue_id,
            idempotency_key=model.idempotency_key,
            doc_no=model.doc_no,
            doc_type=model.doc_type,
            doc_seq=model.doc_seq,
            trans_type_cd=model.trans_type_cd,
            file_nm=model.file_nm,
            ai_scan_app=model.ai_scan_app,
            path_file=model.path_file,
            processing_status=model.processing_status,
            retry_count=model.retry_count,
            original_payload=model.original_payload,
            request_datetime=model.request_datetime,
            start_datetime=model.start_datetime,
        )
