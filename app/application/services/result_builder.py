from __future__ import annotations

from typing import Any

RESULT_SCHEMA_VERSION = "0.2.0"


def build_result_envelope(
    documents: list[dict[str, Any]],
    duration_ms: int,
    status: str = "COMPLETED",
    errors: list[Any] | None = None,
) -> dict[str, Any]:
    """Canonical additive envelope shared by Streamlit and RabbitMQ output."""
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "processing": {"status": status, "duration_ms": duration_ms},
        "documents": documents,
        "summary": {
            "total_documents": len(documents),
            "total_pages": sum(len(document.get("pages", [])) for document in documents),
        },
        "errors": errors or [],
    }


def build_result_payload(
    raw_result: dict[str, Any],
    file_name: str,
    content_type: str,
    file_size_bytes: int,
    processing_time_ms: int,
) -> dict[str, Any]:
    """Build the one JSON result used by Streamlit today and RabbitMQ later."""
    page_images = raw_result.get("pages", [])
    page_ocrs = raw_result.get("_page_ocrs", [])
    page_barcodes = raw_result.get("_page_bcs", [])
    fields = raw_result.get("fields", {})
    detections = raw_result.get("detections", [])
    pages = []

    for index, image in enumerate(page_images):
        page_number = index + 1
        height, width = image.shape[:2] if hasattr(image, "shape") else (None, None)
        ocr = page_ocrs[index] if index < len(page_ocrs) else {}
        page_fields = _field_entries(fields, page_number)
        pages.append(
            {
                "page_index": index,
                "page_number": page_number,
                "processing_status": "FAILED" if ocr.get("error") else "COMPLETED",
                "processing_result": "INTERNAL_ERROR" if ocr.get("error") else "SUCCESS",
                "image": {"width": width, "height": height},
                "ocr": {
                    "status": "FAILED" if ocr.get("error") else "SUCCESS",
                    "engine": ocr.get("engine_name", raw_result.get("ocr", {}).get("engine_name", "unknown")),
                    "raw_text": ocr.get("raw_text", ""),
                    "average_confidence": _confidence(ocr.get("average_confidence")),
                    "duration_ms": ocr.get("processing_time_ms"),
                    "text_blocks": _text_blocks(ocr.get("tokens_json", []), width, height),
                    "error": ocr.get("error"),
                },
                "detections": [
                    _detection_entry(d, index, width, height) for d in detections if d.get("page_number") == page_number
                ],
                "barcodes": [page_barcodes[index]] if index < len(page_barcodes) else [],
                "extracted_fields": page_fields,
                "document_quality": raw_result.get("quality_scores", {}) if index == 0 else {},
                "errors": [{"stage": "OCR", "message": ocr["error"]}] if ocr.get("error") else [],
            }
        )

    document = {
        "document_id": "TEST-DOC-001",
        "document_name": file_name,
        "document_type": raw_result.get("doc_type", "UNKNOWN"),
        "processing_status": "COMPLETED" if raw_result.get("status") != "error" else "FAILED",
        "processing_result": raw_result.get("status", "FAILED"),
        "processing_time_ms": processing_time_ms or raw_result.get("processing_time_ms", 0),
        "file_information": {
            "file_name": file_name,
            "content_type": content_type,
            "file_size_bytes": file_size_bytes,
            "file_extension": raw_result.get("document_info", {}).get("extension", ""),
        },
        "ocr": {
            "engine": raw_result.get("ocr", {}).get("engine_name", "unknown"),
            "raw_text": raw_result.get("ocr", {}).get("raw_text", ""),
            "average_confidence": _confidence(raw_result.get("ocr", {}).get("average_confidence")),
        },
        "fields": _field_entries(fields, None),
        "detections": [_detection_entry(d, d.get("page_number", 1) - 1, None, None) for d in detections],
        "validation": raw_result.get("validation", {}),
        "confidence": raw_result.get("confidence", {}),
        "reasoning": raw_result.get("reasoning", {"enabled": False}),
        "pages": pages,
        "errors": [error for error in (raw_result.get("error"), raw_result.get("detection_error")) if error],
    }
    return build_result_envelope(
        [document],
        processing_time_ms,
        raw_result.get("status", "FAILED"),
        document["errors"],
    )


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return round(value / 100 if value > 1 else value, 4)


def _text_blocks(tokens: list[dict[str, Any]], width: int | None, height: int | None) -> list[dict[str, Any]]:
    blocks = []
    for index, token in enumerate(tokens or []):
        bbox = token.get("bbox")
        blocks.append(
            {
                "block_index": index,
                "text": token.get("text", ""),
                "confidence": _confidence(token.get("confidence")),
                "label": token.get("label"),
                "reading_order": token.get("reading_order"),
                "bounding_box": _bbox(bbox, token.get("normalized_bbox"), width, height),
            }
        )
    return blocks


def _detection_entry(
    detection: dict[str, Any], page_index: int, width: int | None, height: int | None
) -> dict[str, Any]:
    return {
        "class_id": detection.get("class_id"),
        "label": detection.get("object_type", detection.get("label", "unknown")),
        "confidence": _confidence(detection.get("confidence")),
        "page_index": page_index,
        "page_number": detection.get("page_number", page_index + 1),
        "bounding_box": _bbox(
            detection.get("bounding_box"),
            detection.get("normalized_bounding_box"),
            width or detection.get("page_width"),
            height or detection.get("page_height"),
        ),
        "model_name": detection.get("model_name"),
        "model_version": detection.get("model_version"),
        "threshold_used": detection.get("threshold_used"),
    }


def _bbox(pixel: Any, normalized: Any, width: int | None, height: int | None) -> dict[str, Any] | None:
    if not pixel:
        return None
    values = _flat_box(pixel)
    if len(values) != 4:
        return None
    if normalized is None and width and height:
        normalized = [
            round(values[0] / width, 6),
            round(values[1] / height, 6),
            round(values[2] / width, 6),
            round(values[3] / height, 6),
        ]
    return {"pixel_xyxy": values, "normalized_xyxy": normalized}


def _flat_box(value: Any) -> list[int]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)) and len(value) == 4 and not isinstance(value[0], (list, tuple)):
        return [int(item) for item in value]
    if isinstance(value, (list, tuple)) and len(value) == 4:
        xs = [point[0] for point in value]
        ys = [point[1] for point in value]
        return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
    return []


def _field_entries(fields: dict[str, Any], page_number: int | None) -> list[dict[str, Any]]:
    entries = []
    for name, field in fields.items():
        source_page = field.get("source_page_number", 1)
        if page_number is not None and source_page != page_number:
            continue
        entries.append(
            {
                "field_name": name,
                "value": field.get("value"),
                "raw_value": field.get("raw_value"),
                "data_type": "number" if isinstance(field.get("value"), (int, float)) else "string",
                "confidence": _confidence(field.get("confidence")),
                "source_page_number": source_page,
                "source_text": field.get("source_text"),
                "extraction_method": field.get("extraction_method", field.get("method")),
            }
        )
    return entries
