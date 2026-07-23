from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BBoxCoordinates = Annotated[list[float], Field(min_length=4, max_length=4)]


class BoundingBox(BaseModel):
    """Coordinate variants emitted by the local OCR and detection pipelines."""

    model_config = ConfigDict(extra="allow")

    pixel_xyxy: BBoxCoordinates | None = None
    normalized_xyxy: BBoxCoordinates | None = None
    pdf_points_xyxy: BBoxCoordinates | None = None


class DetectionResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    bounding_box: BoundingBox | None = None


class PageResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    page_number: int = Field(ge=1)
    page_result: Literal["OK", "NG"] | None = None
    detections: list[DetectionResult] = Field(default_factory=list)


class DocumentResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_id: str = Field(min_length=1)
    document_name: str = Field(min_length=1)
    document_result: Literal["OK", "NG"]
    pages: list[PageResult] = Field(default_factory=list)
    detections: list[DetectionResult] = Field(default_factory=list)


class ResultHeader(BaseModel):
    model_config = ConfigDict(extra="allow")

    correlation_id: str = Field(min_length=1)
    overall_result: Literal["OK", "NG"]
    processing_status: str


class ResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.1.0"]
    header: ResultHeader
    documents: list[DocumentResult]


def validate_local_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and JSON-normalize the local result envelope without dropping additive fields."""
    return ResultEnvelope.model_validate(payload).model_dump(mode="json")
