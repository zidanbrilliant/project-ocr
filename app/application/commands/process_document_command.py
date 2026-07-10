from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessDocumentCommand:
    payload: dict[str, Any]
    raw_body: bytes = field(default=b"")
