from typing import Any, Protocol


class BarcodeReaderPort(Protocol):
    async def read(self, image_bytes: bytes) -> dict[str, Any]: ...
