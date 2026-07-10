import json
from collections.abc import Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)

MessageHandler = Callable[[dict[str, Any], AbstractIncomingMessage], Any]


class InvoiceRequestConsumer:
    def __init__(self, connection: RabbitMQConnection) -> None:
        self._connection = connection
        self._consumer_tag: str | None = None

    async def start(self, handler: MessageHandler) -> None:
        channel = await self._connection.get_channel()
        await channel.set_qos(prefetch_count=settings.WORKER_PREFETCH_COUNT)

        queue = await channel.declare_queue(
            settings.RABBITMQ_INPUT_QUEUE,
            durable=True,
        )

        async def on_message(message: AbstractIncomingMessage) -> None:
            async with message.process(ignore_processed=True):
                try:
                    payload = json.loads(message.body.decode())
                    logger.info("message_received", queue_id=payload.get("QUEUE_ID", "unknown"))
                    await handler(payload, message)
                except json.JSONDecodeError:
                    logger.error("invalid_json_payload", body=message.body[:500])
                    await message.reject(requeue=False)
                except Exception:
                    logger.exception("consumer_handler_error")
                    await message.reject(requeue=True)

        self._consumer_tag = await queue.consume(on_message)
        logger.info("consumer_started", queue=settings.RABBITMQ_INPUT_QUEUE)

    async def stop(self) -> None:
        if self._consumer_tag:
            channel = await self._connection.get_channel()
            await channel.cancel(self._consumer_tag)
            logger.info("consumer_stopped")
