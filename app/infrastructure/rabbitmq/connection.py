import aio_pika

from app.shared.config.settings import settings


class RabbitMQConnection:
    def __init__(self) -> None:
        self._connection: aio_pika.Connection | None = None
        self._channel: aio_pika.Channel | None = None
        self._closed = False

    async def connect(self) -> aio_pika.Channel:
        if self._channel and not self._channel.is_closed:
            return self._channel
        self._connection = await aio_pika.connect_robust(
            settings.RABBITMQ_URL,
            timeout=30,
        )
        self._channel = await self._connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        self._channel.default_exchange = aio_pika.Exchange(
            channel=self._channel,
            name="",
            type=aio_pika.ExchangeType.DIRECT,
        )
        return self._channel

    async def get_channel(self) -> aio_pika.Channel:
        if self._channel is None or self._channel.is_closed:
            return await self.connect()
        return self._channel

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()

    @property
    def is_closed(self) -> bool:
        return self._closed


_connection = RabbitMQConnection()


async def get_connection() -> RabbitMQConnection:
    return _connection
