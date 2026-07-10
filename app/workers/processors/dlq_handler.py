from aio_pika import IncomingMessage

from app.infrastructure.rabbitmq.dlq import DLQHandler
from app.infrastructure.rabbitmq.publisher import ResultPublisher
from app.shared.constants import return_codes, statuses
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class WorkerDLQHandler:
    def __init__(self, dlq: DLQHandler, publisher: ResultPublisher) -> None:
        self._dlq = dlq
        self._publisher = publisher

    async def handle_dlq(self, msg: IncomingMessage, payload: dict, reason: str) -> None:
        await self._dlq.move_to_dlq(msg, "INTERNAL_ERROR", reason)
        dlq_payload = {
            "QUEUE_ID": payload.get("QUEUE_ID", ""),
            "DOC_NO": payload.get("DOC_NO", ""),
            "DOC_TYPE": payload.get("DOC_TYPE", ""),
            "DOC_SEQ": payload.get("DOC_SEQ", 0),
            "TRANS_TYPE_CD": payload.get("TRANS_TYPE_CD", ""),
            "FILE_NM": payload.get("FILE_NM", ""),
            "AI_SCAN_APP": payload.get("AI_SCAN_APP", "VISION"),
            "AI_RETURN_STATUS": statuses.NG,
            "AI_RETURN_REMARK": "Document could not be processed, please contact support.",
            "AI_RETURN_CD": return_codes.DLQ_ERROR,
            "AI_RETURN_CONFIDENCE": None,
        }
        await self._publisher.publish(dlq_payload)
        logger.info("dlq_handled")
