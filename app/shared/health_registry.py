from __future__ import annotations

from typing import Any


# ponytail: module-level registry so /health can report model state
_models: dict[str, dict[str, Any]] = {}


def register(name: str, available: bool = False, error: str | None = None, **extra: Any) -> None:
    _models[name] = {"available": available, "error": error, **extra}


def all_status() -> dict[str, Any]:
    return dict(_models)
