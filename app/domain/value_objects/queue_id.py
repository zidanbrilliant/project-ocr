import re
from dataclasses import dataclass

_QUEUE_ID_PATTERN = re.compile(r"^AIQ-\d{8}-\d{6}$")


@dataclass(frozen=True)
class QueueId:
    value: str

    def __post_init__(self) -> None:
        if not _QUEUE_ID_PATTERN.match(self.value):
            raise ValueError(f"Invalid queue_id format: {self.value}")

    def __str__(self) -> str:
        return self.value
