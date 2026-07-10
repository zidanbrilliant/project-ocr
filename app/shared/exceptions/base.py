from typing import Any


class AIBaseError(Exception):
    def __init__(self, message: str = "", context: dict[str, Any] | None = None) -> None:
        self.message = message
        self.context = context or {}
        super().__init__(message)

    def __str__(self) -> str:
        return f"{self.__class__.__name__}: {self.message}"


class DocumentError(AIBaseError):
    pass


class InternalProcessingError(AIBaseError):
    pass


class BusinessValidationError(AIBaseError):
    pass


class DLQError(AIBaseError):
    pass


class PayloadValidationError(AIBaseError):
    pass
