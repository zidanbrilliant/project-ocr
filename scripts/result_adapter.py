from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.application.services.result_builder import build_result_payload


def normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        if v > 1:
            v = v / 100
        return max(0.0, min(v, 1.0))
    except (ValueError, TypeError):
        return None


def normalize_pipeline_result_for_ui(
    raw_result: dict[str, Any],
    file_name: str | None = None,
    content_type: str | None = None,
    file_size_bytes: int = 0,
    processing_time_ms: int = 0,
) -> dict[str, Any]:
    """Convert pipeline raw result into stable UI-friendly structure."""
    if raw_result is None:
        raw_result = {}

    ext = Path(file_name).suffix.lower() if file_name else ""
    payload = build_result_payload(raw_result, file_name or "", content_type or "", file_size_bytes, processing_time_ms)

    document_info = {
        "file_name": file_name or "",
        "extension": ext,
        "size_bytes": file_size_bytes,
        "size_kb": round(file_size_bytes / 1024, 1),
        "content_type": content_type or "",
    }

    pages_raw = raw_result.get("pages", [])
    payload_pages = payload["documents"][0]["pages"]
    ui_pages: list[dict[str, Any]] = []

    for pi, page_obj in enumerate(pages_raw):
        if isinstance(page_obj, dict):
            page_number = page_obj.get("page_number", pi + 1)
        else:
            page_number = pi + 1

        payload_page = payload_pages[pi]
        ocr = payload_page["ocr"]
        ocr_text = ocr.get("raw_text") or ""
        ocr_engine = ocr.get("engine", "?")
        ocr_conf = normalize_confidence(ocr.get("average_confidence"))

        agg = raw_result.get("detection_aggregated", {})

        preview_bytes = make_page_preview(page_obj)
        page_ui = {
            "page_index": pi,
            "page_number": page_number,
            "status": "SUCCESS",
            "preview": {
                "image_bytes": preview_bytes,
                "mime_type": "image/png",
                "width": page_obj.shape[1] if hasattr(page_obj, "shape") else 0,
                "height": page_obj.shape[0] if hasattr(page_obj, "shape") else 0,
            } if preview_bytes is not None else None,
            "ocr": {
                "status": ocr.get("status", "FAILED"),
                "engine": ocr_engine,
                "raw_text": ocr_text or "(empty)",
                "avg_confidence": round(ocr_conf * 100, 1) if ocr_conf is not None else 0,
                "blocks": ocr.get("text_blocks", []),
                "error": ocr.get("error"),
            },
            "detections": [
                {
                    "label": d.get("label", "?"),
                    "confidence": (d.get("confidence") or 0) * 100,
                    "page_number": d.get("page_number", page_number),
                    "bbox": (d.get("bounding_box") or {}).get("pixel_xyxy", []),
                }
                for d in payload_page["detections"]
            ],
            "fields": {field["field_name"]: field for field in payload_page["extracted_fields"]},
            "detection_aggregated": agg,
        }
        ui_pages.append(page_ui)

    page_count = len(ui_pages) or raw_result.get("document_info", {}).get("page_count", 0)

    # Determine overall status
    has_ocr = any(p["ocr"]["status"] == "SUCCESS" for p in ui_pages)
    has_detection = any(p["detections"] for p in ui_pages)
    pipeline_status = raw_result.get("status", "FAILED")

    if pipeline_status in ("OK", "SUCCESS") and (has_ocr or has_detection):
        overall = "SUCCESS"
    elif has_ocr or has_detection:
        overall = "PARTIAL_SUCCESS"
    else:
        overall = "FAILED"

    conf = raw_result.get("confidence", {})
    total_conf = conf.get("total") if isinstance(conf, dict) else raw_result.get("total_confidence")

    ui_result: dict[str, Any] = {
        "status": overall,
        "processing_time_ms": processing_time_ms or raw_result.get("processing_time_ms", 0),
        "document": {
            **document_info,
            "page_count": page_count,
        },
        "pages": ui_pages,
        "errors": [err for err in (raw_result.get("error"), raw_result.get("detection_error")) if err],
        "pipeline_raw": {
            "total_confidence": total_conf,
            "has_ocr": has_ocr,
            "has_detection": has_detection,
        },
        "rabbitmq_preview": payload,
    }
    return ui_result


def make_page_preview(page_obj: Any) -> bytes | None:
    if page_obj is None:
        return None
    if isinstance(page_obj, bytes):
        return page_obj
    if isinstance(page_obj, np.ndarray):
        _, encoded = cv2.imencode(".png", page_obj)
        return encoded.tobytes()
    if hasattr(page_obj, "tobytes"):
        return page_obj.tobytes()
    return None
