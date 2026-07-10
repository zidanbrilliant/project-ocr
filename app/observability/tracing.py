import contextvars
import uuid

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def generate_trace_id() -> str:
    return uuid.uuid4().hex[:32]


def set_trace_id(tid: str | None = None) -> str:
    val = tid or generate_trace_id()
    _trace_id.set(val)
    return val


def get_trace_id() -> str:
    return _trace_id.get()
