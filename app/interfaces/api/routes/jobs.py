from fastapi import APIRouter, Depends, HTTPException, status

from app.application.queries.get_job_result_query import JobResultResponse as JobResultQuery
from app.application.queries.get_job_status_query import JobStatusResult
from app.application.use_cases.get_job_result_use_case import GetJobResultUseCase
from app.application.use_cases.get_job_status_use_case import GetJobStatusUseCase
from app.application.use_cases.reprocess_job_use_case import ReprocessJobUseCase
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.interfaces.api.dependencies import (
    get_job_repo,
    get_result_repo,
    verify_api_key,
)
from app.interfaces.schemas.request_schemas import ReprocessRequest
from app.interfaces.schemas.response_schemas import JobResultResponse, JobStatusResponse, ReprocessResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(verify_api_key)])


@router.get("/{queue_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    queue_id: str,
    job_repo: AIJobPostgresRepository = Depends(get_job_repo),
) -> JobStatusResponse:
    use_case = GetJobStatusUseCase(job_repo)
    result = await use_case.execute(queue_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobStatusResponse(
        queue_id=result.queue_id,
        job_id=result.job_id,
        status=result.status,
        doc_no=result.doc_no,
        doc_type=result.doc_type,
        retry_count=result.retry_count,
        created_at=result.created_at.isoformat() if result.created_at else None,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
    )


@router.get("/{queue_id}/result", response_model=JobResultResponse)
async def get_job_result(
    queue_id: str,
    result_repo: ResultPostgresRepository = Depends(get_result_repo),
) -> JobResultResponse:
    use_case = GetJobResultUseCase(result_repo)
    result = await use_case.execute(queue_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResultResponse(
        queue_id=result.queue_id,
        ai_return_status=result.ai_return_status,
        ai_return_cd=result.ai_return_cd,
        ai_return_confidence=result.ai_return_confidence,
        ai_return_remark=result.ai_return_remark,
        result=result.result,
    )


@router.post("/{queue_id}/reprocess", status_code=status.HTTP_202_ACCEPTED, response_model=ReprocessResponse)
async def reprocess_job(
    queue_id: str,
    body: ReprocessRequest,
    job_repo: AIJobPostgresRepository = Depends(get_job_repo),
) -> ReprocessResponse:
    use_case = ReprocessJobUseCase(job_repo)
    from app.application.commands.reprocess_job_command import ReprocessJobCommand
    cmd = ReprocessJobCommand(queue_id=queue_id, reason=body.reason, force=body.force)
    result_status = await use_case.execute(cmd)
    return ReprocessResponse(queue_id=queue_id, status=result_status)
