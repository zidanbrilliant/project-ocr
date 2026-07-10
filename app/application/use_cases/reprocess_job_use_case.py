from app.application.commands.reprocess_job_command import ReprocessJobCommand
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ReprocessJobUseCase:
    def __init__(self, job_repo: AIJobPostgresRepository) -> None:
        self._job_repo = job_repo

    async def execute(self, command: ReprocessJobCommand) -> str:
        job = await self._job_repo.get_by_queue_id(command.queue_id)
        if not job:
            raise ValueError(f"Job not found: {command.queue_id}")
        logger.info("reprocess_requested", queue_id=command.queue_id, reason=command.reason)
        return "REPROCESS_QUEUED"
