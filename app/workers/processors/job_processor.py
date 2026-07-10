from aio_pika.abc import AbstractIncomingMessage
from typing import Any

from app.application.services.ai_pipeline_orchestrator import AIPipelineOrchestrator
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class JobProcessor:
    def __init__(self, orchestrator: AIPipelineOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def handle(self, payload: dict[str, Any], message: AbstractIncomingMessage) -> None:
        logger.info("job_processing_started", doc_no=payload.get("DOC_NO"))
        await self._orchestrator.process(payload, message)
