from typing import Final

OK: Final[str] = "OK"
NG: Final[str] = "NG"
REVIEW: Final[str] = "REVIEW"
SKIPPED: Final[str] = "SKIPPED"
NOT_APPLICABLE: Final[str] = "NOT_APPLICABLE"
UNKNOWN: Final[str] = "UNKNOWN"

# Job statuses
RECEIVED: Final[str] = "RECEIVED"
ACCEPTED: Final[str] = "ACCEPTED"
QUEUED: Final[str] = "QUEUED"
RUNNING: Final[str] = "RUNNING"
PARTIAL_COMPLETED: Final[str] = "PARTIAL_COMPLETED"
COMPLETED: Final[str] = "COMPLETED"
FAILED: Final[str] = "FAILED"
RETRYING: Final[str] = "RETRYING"
CANCELLED: Final[str] = "CANCELLED"
DLQ: Final[str] = "DLQ"

# Document & page statuses
PENDING: Final[str] = "PENDING"
PROCESSING: Final[str] = "PROCESSING"

# Processing results
SUCCESS: Final[str] = "SUCCESS"
PARTIAL_SUCCESS: Final[str] = "PARTIAL_SUCCESS"
DOCUMENT_ERROR: Final[str] = "DOCUMENT_ERROR"
INTERNAL_ERROR: Final[str] = "INTERNAL_ERROR"
VALIDATION_ERROR: Final[str] = "VALIDATION_ERROR"
TIMEOUT: Final[str] = "TIMEOUT"
DLQ_ERROR: Final[str] = "DLQ_ERROR"

# Inbox statuses
INBOX_RECEIVED: Final[str] = "RECEIVED"
INBOX_PROCESSING: Final[str] = "PROCESSING"
INBOX_PROCESSED: Final[str] = "PROCESSED"
INBOX_DUPLICATE: Final[str] = "DUPLICATE"
INBOX_FAILED: Final[str] = "FAILED"

# Outbox statuses
OUTBOX_PENDING: Final[str] = "PENDING"
OUTBOX_PROCESSING: Final[str] = "PROCESSING"
OUTBOX_PUBLISHED: Final[str] = "PUBLISHED"
OUTBOX_FAILED: Final[str] = "FAILED"
OUTBOX_DLQ: Final[str] = "DLQ"

# Validation results
VALIDATION_PASSED: Final[str] = "PASSED"
VALIDATION_FAILED: Final[str] = "FAILED"
VALIDATION_REVIEW: Final[str] = "REVIEW"
VALIDATION_SKIPPED: Final[str] = "SKIPPED"
VALIDATION_NA: Final[str] = "NOT_APPLICABLE"
VALIDATION_ERROR: Final[str] = "ERROR"

# Error scopes
SCOPE_JOB: Final[str] = "JOB"
SCOPE_DOCUMENT: Final[str] = "DOCUMENT"
SCOPE_PAGE: Final[str] = "PAGE"
SCOPE_OCR: Final[str] = "OCR"
SCOPE_DETECTION: Final[str] = "DETECTION"
SCOPE_BARCODE: Final[str] = "BARCODE"
SCOPE_VALIDATION: Final[str] = "VALIDATION"
SCOPE_DUPLICATE_CHECK: Final[str] = "DUPLICATE_CHECK"
SCOPE_RESULT_PUBLISH: Final[str] = "RESULT_PUBLISH"
SCOPE_DATABASE: Final[str] = "DATABASE"
SCOPE_STORAGE: Final[str] = "STORAGE"

# Artifact types
ARTIFACT_ORIGINAL: Final[str] = "ORIGINAL_DOCUMENT"
ARTIFACT_RENDERED: Final[str] = "RENDERED_PAGE"
ARTIFACT_PREPROCESSED: Final[str] = "PREPROCESSED_PAGE"
ARTIFACT_DETECTION_CROP: Final[str] = "DETECTION_CROP"
ARTIFACT_DEBUG: Final[str] = "DEBUG_IMAGE"
ARTIFACT_OCR_OUTPUT: Final[str] = "OCR_OUTPUT"
ARTIFACT_FINAL_RESULT: Final[str] = "FINAL_RESULT_JSON"

# Extraction methods
EXTRACT_REGEX: Final[str] = "regex"
EXTRACT_LAYOUT: Final[str] = "layout_aware"
EXTRACT_LLM: Final[str] = "llm"
EXTRACT_RULE: Final[str] = "rule_based"
EXTRACT_OCR_KEYWORD: Final[str] = "ocr_keyword"

# Extraction sources
OCR_SOURCE_PYPDF: Final[str] = "pypdf"
OCR_SOURCE_EASYOCR: Final[str] = "easyocr"
