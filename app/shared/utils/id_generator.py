import uuid
from datetime import datetime


def generate_queue_id() -> str:
    now = datetime.utcnow()
    date_part = now.strftime("%Y%m%d")
    seq = uuid.uuid4().int % 1_000_000
    return f"AIQ-{date_part}-{seq:06d}"


def generate_job_id() -> str:
    return str(uuid.uuid4())
