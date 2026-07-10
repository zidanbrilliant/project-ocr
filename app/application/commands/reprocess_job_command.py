from dataclasses import dataclass


@dataclass
class ReprocessJobCommand:
    queue_id: str
    reason: str = ""
    force: bool = False
