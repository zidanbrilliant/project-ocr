from typing import Protocol


class DocumentConverterPort(Protocol):
    async def convert_to_images(self, content: bytes, extension: str) -> list[bytes]: ...
