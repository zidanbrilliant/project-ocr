import json
from typing import Any

from aio_pika import IncomingMessage, Message

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class DLQHandler:
    def __init__(self, connection: RabbitMQConnection) -> None:
        self._connection = connection

    async def move_to_dlq(self, original_message: IncomingMessage, error_category: str, reason: str) -> None:
        channel = await self._connection.get_channel()
        dlq = await channel.declare_queue(
            settings.RABBITMQ_DLQ,
            durable=True,
        )
        dlx = await channel.declare_exchange(
            settings.RABBITMQ_DLX,
            type="direct",
            durable=True,
        )
        await dlq.bind(dlx, routing_key=settings.RABBITMQ_DLQ)

        dlq_message = Message(
            body=original_message.body,
            delivery_mode=2,
            headers={
                "x-error-category": error_category,
                "x-error-reason": reason,
                "x-original-routing-key": settings.RABBITMQ_INPUT_ROUTING_KEY,
                "x-dlq-timestamp": json.dumps({"timestamp": __import__("datetime").datetime.utcnow().isoformat()}),
            },
        )
        await dlx.publish(dlq_message, routing_key=settings.RABBITMQ_DLQ)
        logger.info("message_moved_to_dlq", error_category=error_category)
