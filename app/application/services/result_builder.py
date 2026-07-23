from __future__ import annotations

from typing import Any

RESULT_SCHEMA_VERSION = "1.1.0"

DEFAULT_MODEL_INFO = {
    "model_name": "Vision-AI",
    "model_version": "v2.6.0",
    "trained_date": "2026-06-15",
}
DEFAULT_MODELS_INFO = {
    "object_detection": {
        "engine": "Ultralytics YOLO",
        "framework": "ultralytics",
        "model_name": "best-v5.pt",
        "model_version": "sesi_4",
        "device": "cuda:0",
        "input_size": 640,
        "confidence_threshold": 0.25,
        "nms_threshold": 0.45,
        "classes": {"0": "barcode", "1": "materai", "2": "signature", "3": "stamp"},
    },
    "ocr": {
        "engine": "NVIDIA Nemotron Parse v1.2",
        "provider": "nemotron-parse",
        "version": "1.2",
        "device": "cuda:0",
        "languages": ["en", "id"],
    },
    "barcode": {
        "primary": "zxing-cpp",
        "fallback": ["pyzbar", "opencv"],
        "decoders": ["zxing-cpp", "pyzbar", "opencv"],
    },
}


def build_result_envelope(
    documents: list[dict[str, Any]],
    duration_ms: int,
    status: str = "COMPLETED",
    errors: list[Any] | None = None,
    *,
    queue_id: str = "",
    pv_no: str = "",
    pv_year: str = "",
    source_system: str = "",
    overall_confidence: float | None = None,
    confidence_level: str = "",
    confidence_threshold: int = 85,
    ai_note_override: str | None = None,
    correlation_id: str = "",
    job_id: str = "",
) -> dict[str, Any]:
    """Canonical contract-shaped envelope shared by Streamlit and RabbitMQ output."""
    documents = _with_page_ai_notes(documents)
    total = len(documents)
    ok = sum(
        1
        for document in documents
        if document.get("document_result", document.get("processing_result")) in {"OK", "SUCCESS"}
    )
    ng = total - ok
    overall = "OK" if total and ng == 0 and not errors else "NG"

    header = {
        "message_version": "1.0",
        "queue_no": queue_id,
        "correlation_id": correlation_id,
        "response_schema_version": RESULT_SCHEMA_VERSION,
        "pv_no": pv_no,
        "pv_year": pv_year,
        "request_source": source_system,
        "response_source": "AI Verification Service",
        "overall_result": overall,
        "processing_status": status,
        "processing_result": "SUCCESS" if not errors else "PARTIAL_SUCCESS",
        "ai_confidence": overall_confidence,
        "ai_confidence_level": confidence_level,
        "confidence_threshold": confidence_threshold,
        "model": DEFAULT_MODEL_INFO,
        "models": DEFAULT_MODELS_INFO,
        "ai_note": ai_note_override or f"{ok} OK, {ng} NG document(s)",
    }

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "header": header,
        "processing": {"status": status, "duration_ms": duration_ms, "job_id": job_id},
        "documents": documents,
        "summary": {
            "total_documents": total,
            "ok_documents": ok,
            "ng_documents": ng,
            "total_pages": sum(len(document.get("pages", [])) for document in documents),
            "main_document": total,
            "second_document": 0,
        },
        "errors": errors or [],
    }


def apply_result_envelope(payload: dict[str, Any], envelope: dict[str, Any]) -> None:
    """Merge the canonical envelope while retaining request-specific payload fields."""
    payload.update({key: value for key, value in envelope.items() if key != "documents"})
    payload["documents"] = envelope["documents"]


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
    quality_pages = raw_result.get("quality_pages", [])
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
                    "provider": "nemotron-parse",
                    "version": "1.2",
                    "device": "cuda:0",
                    "languages": ["en", "id"],
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
                "document_quality": (
                    quality_pages[index]
                    if index < len(quality_pages)
                    else raw_result.get("quality_scores", {})
                ),
                "errors": [{"stage": "OCR", "message": ocr["error"]}] if ocr.get("error") else [],
            }
        )

    confidence = raw_result.get("confidence", {})
    document = {
        "document_id": raw_result.get("document_id", "TEST-DOC-001"),
        "document_index": raw_result.get("document_index", 0),
        "document_name": file_name,
        "document_type": raw_result.get("doc_type", "UNKNOWN"),
        "document_category": raw_result.get("document_category", "MAIN_DOCUMENT"),
        "page_count": len(pages),
        "processing_status": "FAILED" if raw_result.get("error") else "COMPLETED",
        "processing_result": raw_result.get("status", "FAILED"),
        "document_result": (
            "OK" if confidence.get("overall_result") == "OK" and raw_result.get("validation", {}).get("passed")
            else "NG"
        ),
        "processing_time_ms": processing_time_ms or raw_result.get("processing_time_ms", 0),
        "file_information": {
            "file_name": file_name,
            "content_type": content_type,
            "file_size_bytes": file_size_bytes,
            "file_extension": raw_result.get("document_info", {}).get("extension", ""),
        },
        "ocr": {
            "engine": raw_result.get("ocr", {}).get("engine_name", "unknown"),
            "provider": "nemotron-parse",
            "version": "1.2",
            "device": "cuda:0",
            "languages": ["en", "id"],
            "raw_text": raw_result.get("ocr", {}).get("raw_text", ""),
            "average_confidence": _confidence(raw_result.get("ocr", {}).get("average_confidence")),
        },
        "fields": _field_entries(fields, None),
        "field_candidate_audit": raw_result.get("field_candidate_audit", {}),
        "financials": raw_result.get("financials", {}),
        "barcode": raw_result.get("barcode", {}),
        "document_color": raw_result.get("document_color", {}),
        "detections": [_detection_entry(d, d.get("page_number", 1) - 1, None, None) for d in detections],
        "validation": raw_result.get("validation", {}),
        "confidence": confidence,
        "reasoning": raw_result.get("reasoning", {"enabled": False}),
        "business_rule": _business_rule(raw_result.get("validation", {})),
        "document_summary": raw_result.get("document_summary", {}),
        "verification": _verification(detections),
        "duplicate_check": raw_result.get("duplicate_check", {"result": "NOT_APPLICABLE", "confidence": None}),
        "pages": pages,
        "errors": [error for error in (raw_result.get("error"), raw_result.get("detection_error")) if error],
    }
    conf = document.get("confidence", {})
    return build_result_envelope(
        [document],
        processing_time_ms,
        raw_result.get("status", "FAILED"),
        document["errors"],
        overall_confidence=conf.get("total"),
        confidence_level=conf.get("level", ""),
    )


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return round(value / 100 if value > 1 else value, 4)


def _page_ai_note(
    ocr: dict[str, Any], detections: list[dict[str, Any]], barcode: Any, color_evidence: Any
) -> str:
    """Summarize page evidence deterministically for local review."""
    ocr_note = "OCR text found" if ocr.get("raw_text") else "OCR text not found"
    detection_note = f"{len(detections)} detection(s)"
    barcode_note = "barcode found" if barcode else "barcode not found"
    color_note = "color evidence found" if color_evidence else "color evidence not found"
    return f"{ocr_note}; {detection_note}; {barcode_note}; {color_note}."


def _with_page_ai_notes(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add page evidence summaries without changing caller-owned document structures."""
    enriched_documents = []
    for document in documents:
        enriched_document = document.copy()
        color_evidence = document.get("document_color", {})
        enriched_document["pages"] = [
            {
                **page,
                "ai_note": _page_ai_note(
                    page.get("ocr", {}),
                    page.get("detections", []),
                    page.get("barcodes", []),
                    page.get("document_color", color_evidence),
                ),
            }
            for page in document.get("pages", [])
        ]
        enriched_documents.append(enriched_document)
    return enriched_documents


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
    return {"pixel_xyxy": values, "normalized_xyxy": normalized, "pdf_points_xyxy": values}


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
                "status": field.get("status", "FOUND"),
                "source_page_index": field.get("source_page_index", source_page - 1),
                "source_page_number": source_page,
                "source_text": field.get("source_text"),
                "source_label": field.get("source_label"),
                "source_block_id": field.get("source_block_id"),
                "candidate_id": field.get("candidate_id"),
                "source_bbox": field.get("source_bbox"),
                "extraction_method": field.get("extraction_method", field.get("method")),
                "reason_code": field.get("reason_code"),
                "reasoning_engine": field.get("reasoning_engine"),
                "verification_status": field.get("verification_status"),
                "independent_evidence_count": field.get("independent_evidence_count"),
                "confidence_source": field.get("confidence_source"),
                "confidence_calibrated": field.get("confidence_calibrated"),
                "manual_review_required": field.get("manual_review_required", False),
                "amount_role": field.get("amount_role"),
                "currency": field.get("currency"),
                "validation": field.get("validation"),
                "candidate_count": field.get("candidate_count"),
                "alternatives": field.get("alternatives", []),
            }
        )
    return entries


def _business_rule(validation: Any) -> dict[str, Any]:
    validation = validation if isinstance(validation, dict) else {}
    failed = validation.get("failed_rules", []) or []
    return {
        "rule_version": "v1.0",
        "rules_passed": 0,
        "rules_failed": len(failed),
        "rules": [
            {
                "rule_id": item.get("rule_id"),
                "rule_name": item.get("rule_name"),
                "result": "FAILED",
                "reason": item.get("message", item.get("reason")),
            }
            for item in failed
            if isinstance(item, dict)
        ],
    }


def _verification(detections: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("signature", "stamp", "materai"):
        matches = [item for item in detections if item.get("object_type") == name]
        best = max(matches, key=lambda item: item.get("confidence") or 0, default={})
        result[name] = {
            "required": True,
            "result": "OK" if best else "NG",
            "confidence": _confidence(best.get("confidence")) if best else None,
            "count": len(matches),
            "bounding_box": (
                _bbox(best.get("bounding_box"), best.get("normalized_bounding_box"), None, None)
                if best
                else None
            ),
            "matches": [
                {
                    "page_number": item.get("page_number"),
                    "confidence": _confidence(item.get("confidence")),
                    "bounding_box": _bbox(
                        item.get("bounding_box"),
                        item.get("normalized_bounding_box"),
                        item.get("page_width"),
                        item.get("page_height"),
                    ),
                }
                for item in matches
            ],
        }
    return result
