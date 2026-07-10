from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog


def bind_context(**kwargs) -> None:
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


@asynccontextmanager
async def log_context(
    **kwargs,
) -> AsyncGenerator[None]:
    bind_context(**kwargs)
    try:
        yield
    finally:
        unbind_context(*kwargs.keys())
