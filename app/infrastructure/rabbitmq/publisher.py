import json
from typing import Any

from aio_pika import Message

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ResultPublisher:
    def __init__(self, connection: RabbitMQConnection) -> None:
        self._connection = connection

    async def publish(self, payload: dict[str, Any]) -> None:
        channel = await self._connection.get_channel()
        exchange = await channel.declare_exchange(
            settings.RABBITMQ_RESULT_EXCHANGE,
            type="direct",
            durable=True,
        )
        message = Message(
            body=json.dumps(payload).encode(),
            delivery_mode=2,
            content_type="application/json",
        )
        await exchange.publish(
            message,
            routing_key=settings.RABBITMQ_RESULT_ROUTING_KEY,
        )
        logger.info("result_published", queue_id=payload.get("QUEUE_ID", "unknown"))
