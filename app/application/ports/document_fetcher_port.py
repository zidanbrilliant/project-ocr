from typing import Protocol


class DocumentFetcherPort(Protocol):
    async def fetch(self, path_file: str) -> bytes: ...
