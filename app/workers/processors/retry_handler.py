from app.infrastructure.rabbitmq.retry import RetryHandler
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class WorkerRetryHandler:
    def __init__(self, retry_handler: RetryHandler) -> None:
        self._handler = retry_handler

    async def handle_retry(self, payload: dict, retry_count: int) -> None:
        if self._handler.should_retry(retry_count):
            await self._handler.send_to_retry(payload, retry_count)
            logger.info("retry_scheduled", retry_count=retry_count)
