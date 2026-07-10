import aio_pika

from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.shared.config.settings import settings
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


async def declare_topology(connection: RabbitMQConnection) -> None:
    channel = await connection.get_channel()

    request_exchange = await channel.declare_exchange(
        settings.RABBITMQ_INPUT_EXCHANGE,
        type="direct",
        durable=True,
    )
    request_queue = await channel.declare_queue(
        settings.RABBITMQ_INPUT_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.RABBITMQ_DLX,
            "x-dead-letter-routing-key": settings.RABBITMQ_DLQ,
        },
    )
    await request_queue.bind(request_exchange, routing_key=settings.RABBITMQ_INPUT_ROUTING_KEY)

    result_exchange = await channel.declare_exchange(
        settings.RABBITMQ_RESULT_EXCHANGE,
        type="direct",
        durable=True,
    )
    result_queue = await channel.declare_queue(
        settings.RABBITMQ_RESULT_QUEUE,
        durable=True,
    )
    await result_queue.bind(result_exchange, routing_key=settings.RABBITMQ_RESULT_ROUTING_KEY)

    retry_exchange = await channel.declare_exchange(
        settings.RABBITMQ_RETRY_EXCHANGE,
        type="direct",
        durable=True,
    )
    retry_queue = await channel.declare_queue(
        settings.RABBITMQ_RETRY_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.RABBITMQ_INPUT_EXCHANGE,
            "x-dead-letter-routing-key": settings.RABBITMQ_INPUT_ROUTING_KEY,
            "x-message-ttl": 30000,
        },
    )
    await retry_queue.bind(retry_exchange, routing_key=settings.RABBITMQ_RETRY_ROUTING_KEY)

    dlx = await channel.declare_exchange(
        settings.RABBITMQ_DLX,
        type="direct",
        durable=True,
    )
    dlq = await channel.declare_queue(
        settings.RABBITMQ_DLQ,
        durable=True,
    )
    await dlq.bind(dlx, routing_key=settings.RABBITMQ_DLQ)

    logger.info("rabbitmq_topology_declared")
