import contextvars
import uuid

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def generate_trace_id() -> str:
    return f"trc-{uuid.uuid4().hex[:12]}"


def set_trace_id() -> str:
    tid = generate_trace_id()
    trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    return trace_id_var.get()
