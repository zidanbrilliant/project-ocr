import httpx

from app.shared.config.settings import settings
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ImageServerClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.IMAGE_SERVER_TIMEOUT_SECONDS),
            follow_redirects=True,
        )

    async def fetch(self, path_file: str) -> bytes:
        try:
            response = await self._client.get(path_file)
            response.raise_for_status()
            content = response.content
            if not content:
                raise DocumentError("Empty file", {"path_file": path_file})
            logger.info("file_downloaded", size_bytes=len(content))
            return content
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise DocumentError("Document is missing from server", {"path_file": path_file, "status": 404})
            raise DocumentError(f"Download failed: HTTP {e.response.status_code}", {"path_file": path_file, "status": e.response.status_code})
        except httpx.TimeoutException:
            raise DocumentError("Download timeout", {"path_file": path_file})
        except httpx.RequestError as e:
            raise DocumentError(f"Network error: {e}", {"path_file": path_file})

    async def close(self) -> None:
        await self._client.aclose()
