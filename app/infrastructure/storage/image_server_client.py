import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.shared.config.settings import settings
from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ImageServerClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.IMAGE_SERVER_TIMEOUT_SECONDS),
            follow_redirects=False,
        )

    async def fetch(self, path_file: str) -> bytes:
        try:
            url = path_file
            response: httpx.Response | None = None
            for _ in range(4):
                await self._validate_url(url)
                response = await self._client.send(self._client.build_request("GET", url), stream=True)
                if response.is_redirect:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        raise DocumentError("Download redirect has no location", {"path_file": path_file})
                    url = urljoin(url, location)
                    continue
                break
            if response is None or response.is_redirect:
                raise DocumentError("Too many download redirects", {"path_file": path_file})
            try:
                response.raise_for_status()
                max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
                declared = int(response.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise DocumentError("File size exceeds maximum limit", {"size": declared, "max": max_bytes})
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise DocumentError("File size exceeds maximum limit", {"size": size, "max": max_bytes})
                    chunks.append(chunk)
            finally:
                await response.aclose()
            content = b"".join(chunks)
            if not content:
                raise DocumentError("Empty file", {"path_file": path_file})
            logger.info("file_downloaded", size_bytes=len(content))
            return content
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise DocumentError("Document is missing from server", {"path_file": path_file, "status": 404}) from e
            raise DocumentError(
                f"Download failed: HTTP {e.response.status_code}",
                {"path_file": path_file, "status": e.response.status_code},
            ) from e
        except httpx.TimeoutException as e:
            raise DocumentError("Download timeout", {"path_file": path_file}) from e
        except httpx.RequestError as e:
            raise DocumentError(f"Network error: {e}", {"path_file": path_file}) from e

    async def _validate_url(self, value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise DocumentError("Invalid document URL", {"url": value})
        configured = settings.IMAGE_SERVER_ALLOWED_HOSTS
        allowed = {host.strip().lower() for host in configured.split(",") if host.strip()}
        if settings.IMAGE_SERVER_BASE_URL:
            base_host = urlparse(settings.IMAGE_SERVER_BASE_URL).hostname
            if base_host:
                allowed.add(base_host.lower())
        host = parsed.hostname.lower()
        if allowed and host not in allowed:
            raise DocumentError("Document host is not allowed", {"host": host})
        if settings.APP_ENV == "production" and not allowed:
            raise DocumentError("IMAGE_SERVER_ALLOWED_HOSTS is required in production")
        if host in allowed:
            return
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                raise DocumentError("Document URL resolves to a restricted address", {"host": host})

    async def close(self) -> None:
        await self._client.aclose()
