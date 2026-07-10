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
        retry_exchange = await channel.declare_exchange(
            settings.RABBITMQ_RETRY_EXCHANGE,
            type="direct",
            durable=True,
        )
        backoff = settings.RETRY_BACKOFF_SECONDS * (settings.RETRY_BACKOFF_MULTIPLIER ** (retry_count - 1))

        message = Message(
            body=payload.get("_raw_body", b"") or str(payload).encode(),
            delivery_mode=2,
            headers={"x-retry-count": retry_count, "x-original-routing-key": settings.RABBITMQ_INPUT_ROUTING_KEY},
        )
        await channel.declare_queue(
            settings.RABBITMQ_RETRY_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": int(backoff * 1000),
                "x-dead-letter-exchange": settings.RABBITMQ_INPUT_EXCHANGE,
                "x-dead-letter-routing-key": settings.RABBITMQ_INPUT_ROUTING_KEY,
            },
        )
        await retry_exchange.publish(
            message,
            routing_key=settings.RABBITMQ_RETRY_ROUTING_KEY,
        )
        logger.info("message_sent_to_retry", retry_count=retry_count, backoff_seconds=backoff)

    def should_retry(self, retry_count: int) -> bool:
        return retry_count < settings.MAX_RETRY
