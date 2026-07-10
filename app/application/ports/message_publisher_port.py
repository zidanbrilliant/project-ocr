from typing import Any, Protocol


class MessagePublisherPort(Protocol):
    async def publish(self, payload: dict[str, Any]) -> None: ...
