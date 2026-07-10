from typing import Any, Protocol


class OCREnginePort(Protocol):
    async def run(self, image_bytes: bytes) -> dict[str, Any]: ...
