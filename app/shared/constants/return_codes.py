from typing import Final

SUCCESS: Final[str] = "SUCCESS"
DOCUMENT_ERROR: Final[str] = "DOCUMENT_ERROR"
INTERNAL_ERROR: Final[str] = "INTERNAL_ERROR"
DLQ_ERROR: Final[str] = "DLQ_ERROR"

RETRYABLE_CODES: Final[frozenset[str]] = frozenset({INTERNAL_ERROR})
NON_RETRYABLE_CODES: Final[frozenset[str]] = frozenset({SUCCESS, DOCUMENT_ERROR, DLQ_ERROR})
