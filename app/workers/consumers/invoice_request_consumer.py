import json
from collections.abc import Callable

from aio_pika.abc import AbstractIncomingMessage

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)
MessageHandler = Callable[[dict, AbstractIncomingMessage], None]


class InvoiceRequestConsumer:
    def __init__(self, connection: RabbitMQConnection) -> None:
        self._connection = connection
        self._consumer_tag: str | None = None

    async def start(self, handler: MessageHandler) -> None:
        channel = await self._connection.get_channel()
        await channel.set_qos(prefetch_count=settings.WORKER_PREFETCH_COUNT)
        queue = await channel.declare_queue(settings.RABBITMQ_INPUT_QUEUE, durable=True)

        async def on_message(msg: AbstractIncomingMessage) -> None:
            async with msg.process(ignore_processed=True):
                try:
                    payload = json.loads(msg.body.decode())
                    await handler(payload, msg)
                except json.JSONDecodeError:
                    logger.error("invalid_json", body=msg.body[:200])
                    await msg.reject(requeue=False)

        self._consumer_tag = await queue.consume(on_message)
        logger.info("worker_consumer_started", queue=settings.RABBITMQ_INPUT_QUEUE)

    async def stop(self) -> None:
        if self._consumer_tag:
            ch = await self._connection.get_channel()
            await ch.cancel(self._consumer_tag)
            logger.info("worker_consumer_stopped")
