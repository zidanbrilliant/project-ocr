import asyncio
import json
import uuid
from contextlib import suppress
from datetime import datetime, timedelta

from aio_pika import Message
from sqlalchemy import and_, or_, select, update

from app.infrastructure.database.models import AIOutboxEvent
from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.constants.statuses import (
    OUTBOX_DLQ,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OUTBOX_PUBLISHED,
)
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class OutboxPublisher:
    def __init__(self, rmq: RabbitMQConnection, session_factory) -> None:
        self._rmq = rmq
        self._session_factory = session_factory
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._worker_id = uuid.uuid4().hex[:8]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._publish_loop())
        logger.info("outbox_publisher_started", worker_id=self._worker_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        logger.info("outbox_publisher_stopped")

    async def _publish_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._publish_batch()
            except Exception:
                logger.exception("outbox_loop_error")
            await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL_SECONDS)

    async def _publish_batch(self) -> None:
        async with self._session_factory() as session:
            stale_before = datetime.utcnow() - timedelta(seconds=settings.OUTBOX_LOCK_TIMEOUT_SECONDS)
            stmt = (
                select(AIOutboxEvent)
                .where(
                    or_(
                        AIOutboxEvent.status.in_((OUTBOX_PENDING, OUTBOX_FAILED)),
                        and_(
                            AIOutboxEvent.status == OUTBOX_PROCESSING,
                            AIOutboxEvent.locked_at < stale_before,
                        ),
                    )
                )
                .where(AIOutboxEvent.available_at <= datetime.utcnow())
                .order_by(AIOutboxEvent.created_at)
                .limit(settings.OUTBOX_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()
            if not events:
                return

            event_ids = [e.id for e in events]
            await session.execute(
                update(AIOutboxEvent)
                .where(AIOutboxEvent.id.in_(event_ids))
                .values(
                    status=OUTBOX_PROCESSING,
                    locked_at=datetime.utcnow(),
                    locked_by=self._worker_id,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()

        for event in events:
            await self._publish_single(event)

    async def _publish_single(self, event: AIOutboxEvent) -> None:
        try:
            channel = await self._rmq.get_channel()
            exchange = await channel.declare_exchange(
                event.destination_exchange or settings.RABBITMQ_RESULT_EXCHANGE,
                type="direct",
                durable=True,
            )
            message = Message(
                body=json.dumps(event.payload or {}).encode(),
                delivery_mode=event.delivery_mode,
                content_type="application/json",
                message_id=event.message_id,
            )
            await exchange.publish(
                message,
                routing_key=event.routing_key or settings.RABBITMQ_RESULT_ROUTING_KEY,
                mandatory=True,
            )

            async with self._session_factory() as session:
                await session.execute(
                    update(AIOutboxEvent)
                    .where(AIOutboxEvent.id == event.id)
                    .values(
                        status=OUTBOX_PUBLISHED,
                        published_at=datetime.utcnow(),
                        attempt_count=AIOutboxEvent.attempt_count + 1,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            logger.info("outbox_published", event_id=str(event.id), job_id=str(event.job_id))

        except Exception as e:
            logger.warning("outbox_publish_failed", event_id=str(event.id), error=str(e))
            async with self._session_factory() as session:
                new_attempt = event.attempt_count + 1
                new_status = OUTBOX_DLQ if new_attempt >= event.max_attempts else OUTBOX_FAILED
                backoff = min(30 * (2 ** (new_attempt - 1)), 3600)
                await session.execute(
                    update(AIOutboxEvent)
                    .where(AIOutboxEvent.id == event.id)
                    .values(
                        status=new_status,
                        attempt_count=new_attempt,
                        available_at=datetime.utcnow()
                        if new_status == OUTBOX_DLQ
                        else datetime.utcnow() + timedelta(seconds=backoff),
                        last_error_code=type(e).__name__,
                        last_error_message=str(e)[:500],
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()
                logger.info("outbox_retry_scheduled", event_id=str(event.id), attempt=new_attempt)
