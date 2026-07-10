from app.application.queries.get_job_status_query import JobStatusResult
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository


class GetJobStatusUseCase:
    def __init__(self, job_repo: AIJobPostgresRepository) -> None:
        self._job_repo = job_repo

    async def execute(self, queue_id: str) -> JobStatusResult | None:
        job = await self._job_repo.get_by_queue_id(queue_id)
        if not job:
            return None
        return JobStatusResult(
            queue_id=job.queue_id,
            job_id=str(job.job_id),
            status=job.processing_status,
            doc_no=job.doc_no,
            doc_type=job.doc_type,
            retry_count=job.retry_count,
            created_at=job.created_at,
            completed_at=job.finish_datetime,
        )
