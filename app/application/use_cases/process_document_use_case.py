from aio_pika.abc import AbstractIncomingMessage
from typing import Any

from app.application.services.ai_pipeline_orchestrator import AIPipelineOrchestrator


class ProcessDocumentUseCase:
    def __init__(self, orchestrator: AIPipelineOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(self, payload: dict[str, Any], message: AbstractIncomingMessage) -> None:
        await self._orchestrator.process(payload, message)
