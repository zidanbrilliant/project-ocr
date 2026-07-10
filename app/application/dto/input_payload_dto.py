from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.shared.constants.doc_types import ALL_TYPES


class InputPayloadDTO(BaseModel):
    DOC_NO: str = Field(..., max_length=100)
    DOC_TYPE: str = Field(..., max_length=30)
    DOC_SEQ: int = Field(..., ge=1)
    TRANS_TYPE_CD: str = Field(..., max_length=50)
    FILE_NM: str = Field(..., max_length=255)
    AI_SCAN_APP: str = Field(default="VISION", max_length=50)
    PATH_FILE: str = Field(..., min_length=1)
    QUEUE_ID: str | None = Field(default=None, max_length=50)

    @field_validator("DOC_TYPE")
    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        if v not in ALL_TYPES:
            raise ValueError(f"Unsupported DOC_TYPE: {v}. Must be one of {ALL_TYPES}")
        return v

    @field_validator("FILE_NM")
    @classmethod
    def validate_extension(cls, v: str) -> str:
        SUPPORTED = (".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx")
        if not any(v.lower().endswith(ext) for ext in SUPPORTED):
            raise ValueError(f"Unsupported file extension in: {v}")
        return v

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
