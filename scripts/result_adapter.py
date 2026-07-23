from pathlib import Path
from typing import Any


def normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
        if normalized > 1:
            normalized /= 100
        return max(0.0, min(normalized, 1.0))
    except (ValueError, TypeError):
        return None


def normalize_result_envelope_for_ui(
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project the canonical result envelope for display without rebuilding it."""
    results = []
    for document_index, document in enumerate(envelope.get("documents", [])):
        file_info = document.get("file_information") or {}
        file_name = file_info.get("file_name") or document.get("document_name", "")
        file_size = file_info.get("file_size_bytes", 0)
        pages = [
            _normalize_page(page, index)
            for index, page in enumerate(document.get("pages", []))
        ]
        confidence = document.get("confidence") or {}

        results.append(
            {
                "status": document.get("processing_status", document.get("processing_result", "FAILED")),
                "processing_time_ms": document.get(
                    "processing_time_ms",
                    envelope.get("processing", {}).get("duration_ms", 0),
                ),
                "document_index": document_index,
                "document": {
                    "file_name": file_name,
                    "extension": file_info.get("file_extension") or Path(file_name).suffix.lower(),
                    "size_bytes": file_size,
                    "size_kb": round(file_size / 1024, 1),
                    "content_type": file_info.get("content_type", ""),
                    "page_count": document.get("page_count", len(pages)),
                },
                "pages": pages,
                "errors": document.get("errors", []),
                "pipeline_raw": {
                    "total_confidence": confidence.get("total"),
                    "has_ocr": any(page["ocr"]["status"] == "SUCCESS" for page in pages),
                    "has_detection": any(page["detections"] for page in pages),
                },
                "rabbitmq_preview": envelope,
            }
        )
    return results


def _normalize_page(page: dict[str, Any], index: int) -> dict[str, Any]:
    ocr = page.get("ocr") or {}
    confidence = normalize_confidence(ocr.get("average_confidence"))
    page_number = page.get("page_number", index + 1)
    return {
        "page_index": page.get("page_index", index),
        "page_number": page_number,
        "status": page.get("processing_status", page.get("processing_result", "FAILED")),
        "preview": None,
        "ocr": {
            "status": ocr.get("status", "FAILED"),
            "engine": ocr.get("engine", "?"),
            "raw_text": ocr.get("raw_text") or "(empty)",
            "avg_confidence": round(confidence * 100, 1) if confidence is not None else 0,
            "blocks": ocr.get("text_blocks", []),
            "error": ocr.get("error"),
        },
        "detections": [
            {
                "label": detection.get("label", "?"),
                "confidence": (normalize_confidence(detection.get("confidence")) or 0) * 100,
                "page_number": detection.get("page_number", page_number),
                "bbox": (detection.get("bounding_box") or {}).get("pixel_xyxy", []),
            }
            for detection in page.get("detections", [])
        ],
        "fields": {
            field["field_name"]: field
            for field in page.get("extracted_fields", [])
            if field.get("field_name")
        },
        "detection_aggregated": {},
    }
