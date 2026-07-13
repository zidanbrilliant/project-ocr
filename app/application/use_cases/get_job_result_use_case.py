from app.application.queries.get_job_result_query import JobResultResponse
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository


class GetJobResultUseCase:
    def __init__(self, result_repo: ResultPostgresRepository) -> None:
        self._result_repo = result_repo

    async def execute(self, queue_id: str) -> JobResultResponse | None:
        final = await self._result_repo.get_by_queue_id(queue_id)
        if not final:
            return None
        internal = final.internal_result_json or {}
        documents = internal.get("documents", [])
        # ponytail: support both legacy (pages[]) and new (documents[].pages[]) format
        pages = internal.get("pages", [])
        if not pages and documents:
            pages = documents[0].get("pages", []) if documents else []
        result_data = None
        if documents:
            doc = documents[0]
            result_data = {
                "documents": documents,
                "summary": internal.get("summary", {}),
            }
        return JobResultResponse(
            queue_id=final.queue_id,
            ai_return_status=final.ai_return_status,
            ai_return_cd=final.ai_return_cd,
            ai_return_confidence=final.ai_return_confidence,
            ai_return_remark=final.ai_return_remark,
            result=result_data,
            pages=pages,
        )
