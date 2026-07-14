from typing import Any

from aio_pika import Message

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class RetryHandler:
    def __init__(self, connection: RabbitMQConnection) -> None:
        self._connection = connection

    async def send_to_retry(self, payload: dict[str, Any], retry_count: int) -> None:
        channel = await self._connection.get_channel()
        exchange = await channel.declare_exchange(
            settings.RABBITMQ_RETRY_EXCHANGE,
            type="direct",
            durable=True,
        )
        backoff = settings.RETRY_BACKOFF_SECONDS * (settings.RETRY_BACKOFF_MULTIPLIER ** (retry_count - 1))

        # ponytail: use saved raw_body if available, otherwise serialize inline
        raw = payload.get("_raw_body") or b""
        if isinstance(raw, str):
            raw = raw.encode()
        body = raw or str(payload).encode()

        message = Message(
            body=body,
            delivery_mode=2,
            expiration=str(int(backoff * 1000)),
            headers={"x-retry-count": retry_count, "x-original-routing-key": settings.RABBITMQ_INPUT_ROUTING_KEY},
        )
        await exchange.publish(
            message,
            routing_key=settings.RABBITMQ_RETRY_ROUTING_KEY,
        )
        logger.info("message_sent_to_retry", retry_count=retry_count, backoff_seconds=backoff)

    def should_retry(self, retry_count: int) -> bool:
        return retry_count < settings.MAX_RETRY
