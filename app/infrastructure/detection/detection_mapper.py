from typing import Any

from app.domain.entities.detection_result import DetectionResult
from app.shared.constants.statuses import NG, OK


def map_to_entity(detection: dict[str, Any], required: bool = True) -> DetectionResult:
    conf = detection.get("confidence", 0)
    result = OK if conf is not None and conf >= 40 else NG

    return DetectionResult(
        page_number=detection.get("page_number", 1),
        model_name=detection.get("model_name", "toyota-document-yolo"),
        model_version=detection.get("model_version", "2026.07.01"),
        object_type=detection.get("object_type", ""),
        result=result,
        required=required,
        confidence=conf,
        bounding_box=detection.get("bounding_box"),
        crop_uri=detection.get("crop_uri"),
        detected_colour=detection.get("detected_colour"),
        reason=None if result == OK else f"{detection.get('object_type', 'object')} not detected with sufficient confidence.",
        attributes=detection.get("attributes"),
    )


def aggregate_per_object_type(detections: list[DetectionResult]) -> dict[str, DetectionResult]:
    by_type: dict[str, list[DetectionResult]] = {}
    for d in detections:
        by_type.setdefault(d.object_type, []).append(d)

    aggregated: dict[str, DetectionResult] = {}
    for obj_type, items in by_type.items():
        max_conf = max((d.confidence for d in items if d.confidence is not None), default=0)
        any_ok = any(d.result == OK for d in items)
        best = max(items, key=lambda x: x.confidence or 0)
        aggregated[obj_type] = DetectionResult(
            page_number=best.page_number,
            model_name=best.model_name,
            model_version=best.model_version,
            object_type=obj_type,
            result=OK if any_ok else NG,
            required=best.required,
            confidence=max_conf,
            bounding_box=best.bounding_box,
        )

    return aggregated
