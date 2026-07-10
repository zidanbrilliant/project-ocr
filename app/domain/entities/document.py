import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    document_pk: uuid.UUID | None = None
    document_id: str = "DOC-001"
    document_name: str = ""
    document_type: str = "INVOICE"
    document_category: str | None = None
    file_extension: str = ""
    content_type: str | None = None
    file_size_bytes: int | None = None
    page_count: int | None = None
    image_width: int | None = None
    image_height: int | None = None
    checksum_sha256: str | None = None
    readable: bool = False
    validation_status: str = "INVALID"
    validation_errors: list[dict[str, Any]] | None = None
