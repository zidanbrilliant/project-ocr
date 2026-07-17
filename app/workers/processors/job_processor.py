import hashlib
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from app.application.dto.request_normalizer import normalize_request
from app.application.services.ai_pipeline_orchestrator import AIPipelineOrchestrator
from app.infrastructure.database.models import AIInboxMessage
from app.infrastructure.database.session import async_session_factory
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class JobProcessor:
    def __init__(self, orchestrator: AIPipelineOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def handle(self, payload: dict[str, Any], message: AbstractIncomingMessage) -> None:
        try:
            normalized = normalize_request(payload)
        except Exception as e:
            logger.error("request_normalization_failed", error=str(e))
            await message.reject(requeue=False)
            return

        # ponytail: inbox idempotency — insert or detect duplicate
        raw_body = message.body.decode() if hasattr(message.body, "decode") else str(message.body)
        payload_hash = hashlib.sha256(raw_body.encode()).hexdigest()

        async with async_session_factory() as session:
            existing = await session.execute(
                __import__("sqlalchemy")
                .select(AIInboxMessage)
                .where(
                    AIInboxMessage.source_system == normalized.source_system,
                    AIInboxMessage.message_id == normalized.message_id,
                )
            )
            inbox_row = existing.scalar_one_or_none()

            if inbox_row and inbox_row.processing_status == "PROCESSED":
                # ponytail: duplicate message, already processed
                logger.info("duplicate_message_skipped", message_id=normalized.message_id)
                await message.ack()
                return

            if not inbox_row:
                inbox_row = AIInboxMessage(
                    message_id=normalized.message_id,
                    correlation_id=normalized.correlation_id,
                    trace_id=normalized.trace_id,
                    source_system=normalized.source_system,
                    payload_hash=payload_hash,
                    payload=payload,
                    processing_status="PROCESSING",
                )
                session.add(inbox_row)
            else:
                inbox_row.processing_status = "PROCESSING"
            await session.commit()

        completed = await self._orchestrator.process(payload, message)

        async with async_session_factory() as session:
            row = await session.get(AIInboxMessage, inbox_row.id)
            if row:
                row.processing_status = "PROCESSED" if completed else "RETRY_SCHEDULED"
                await session.commit()
