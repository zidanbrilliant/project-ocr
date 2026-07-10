from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ObjectStorageClient:
    def __init__(self, endpoint: str = "", access_key: str = "", secret_key: str = "") -> None:
        self._endpoint = endpoint

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        logger.info("object_uploaded", key=key)
        return key

    async def download(self, key: str) -> bytes | None:
        return None

    async def delete(self, key: str) -> None:
        pass
