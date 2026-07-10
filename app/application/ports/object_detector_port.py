from typing import Any, Protocol


class ObjectDetectorPort(Protocol):
    async def detect(self, image_bytes: bytes) -> list[dict[str, Any]]: ...
