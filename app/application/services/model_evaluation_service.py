"""Deterministic field metrics for local model evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CORE_FIELDS = ("document_number", "transaction_amount", "transaction_date")
YOLO_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def normalize_field_value(name: str, value: Any) -> str | Decimal | None:
    """Normalize one selected value without converting amounts through float."""
    if value is None:
        return None
    if name == "transaction_amount":
        if isinstance(value, Decimal):
            return value
        cleaned = str(value).strip().replace(",", "")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return cleaned.upper()
    if name == "transaction_date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value).strip()
    return str(value).strip().upper()


def evaluate_fields(document: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Compare selected canonical document fields with labeled values."""
    fields = _field_map(document)
    actual = {
        name: _actual_value(name, fields.get(name))
        for name in CORE_FIELDS
    }
    checks = {
        name: _field_matches(name, fields.get(name), expected[name])
        for name in CORE_FIELDS
        if name in expected
    }
    return {
        "actual": actual,
        "checks": checks,
        "all_core_fields_exact": bool(checks) and all(checks.values()),
    }


def evaluate_candidate_recall(
    document: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, bool]:
    """Report whether the labeled non-null value appeared before selection."""
    audit = document.get("field_candidate_audit", {})
    checks: dict[str, bool] = {}
    for name in CORE_FIELDS:
        if name not in expected:
            continue
        target = expected[name]
        target_value = _target_value(target)
        if target_value is None:
            continue
        checks[name] = any(
            _field_matches(name, candidate, target)
            for candidate in audit.get(name, [])
            if isinstance(candidate, dict)
        )
    return checks


def field_gate(
    metrics: dict[str, dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """Require every core field to have examples and meet the threshold."""
    failed = []
    for field in CORE_FIELDS:
        metric = metrics.get(field, {})
        evaluated = metric.get("evaluated", 0)
        rate = (
            metric["exact_matches"] / evaluated
            if evaluated and "exact_matches" in metric
            else metric.get("exact_match_rate")
        )
        if not evaluated or rate is None or rate < threshold:
            failed.append(field)
    return {
        "passed": not failed,
        "failed_fields": failed,
        "threshold": threshold,
    }


def summarize_field_evaluations(
    rows: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """Aggregate per-file checks, recall, mismatches, and acceptance."""
    field_metrics = {
        name: {
            "evaluated": sum(name in row.get("checks", {}) for row in rows),
            "exact_matches": sum(
                row.get("checks", {}).get(name, False)
                for row in rows
            ),
        }
        for name in CORE_FIELDS
    }
    for metric in field_metrics.values():
        metric["exact_match_rate"] = (
            round(metric["exact_matches"] / metric["evaluated"], 4)
            if metric["evaluated"]
            else None
        )

    candidate_metrics = {
        name: {
            "evaluated": sum(
                name in row.get("candidate_recall", {})
                for row in rows
            ),
            "correct_candidates": sum(
                row.get("candidate_recall", {}).get(name, False)
                for row in rows
            ),
        }
        for name in CORE_FIELDS
    }
    for metric in candidate_metrics.values():
        metric["recall"] = (
            round(metric["correct_candidates"] / metric["evaluated"], 4)
            if metric["evaluated"]
            else None
        )

    exact_documents = sum(
        bool(row.get("checks")) and all(row["checks"].values())
        for row in rows
    )
    return {
        "labeled_documents": len(rows),
        "field_metrics": field_metrics,
        "candidate_metrics": candidate_metrics,
        "mismatch_examples": _mismatch_examples(rows),
        "all_core_fields_exact": exact_documents,
        "all_core_fields_exact_rate": (
            round(exact_documents / len(rows), 4) if rows else None
        ),
        "field_acceptance": field_gate(field_metrics, threshold),
    }


async def evaluate_yolo_validation(
    detector: Any,
    dataset_root: Path,
    required_labels: set[str],
) -> dict[str, Any]:
    """Evaluate normalized YOLO predictions against one images/labels split."""
    class_map = {int(key): str(value) for key, value in detector.class_map.items()}
    _required_class_ids(class_map, required_labels)
    targets = {
        label: {}
        for label in required_labels
    }
    predictions = {
        label: []
        for label in required_labels
    }
    images_dir = dataset_root / "images"
    labels_dir = dataset_root / "labels"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise FileNotFoundError(
            f"YOLO validation split requires images/ and labels/: {dataset_root}"
        )

    evaluated_images = 0
    skipped_images = 0
    for image_path in sorted(
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in YOLO_IMAGE_SUFFIXES
    ):
        label_path = labels_dir / f"{image_path.stem}.txt"
        if not label_path.is_file():
            skipped_images += 1
            continue

        image_targets = _read_yolo_labels(label_path)
        evaluated_images += 1
        for class_id, box in image_targets:
            label = class_map.get(class_id)
            if label in required_labels:
                targets[label].setdefault(image_path.name, []).append(box)

        for detection in await detector.detect(image_path.read_bytes()):
            label = class_map.get(_detection_class_id(detection))
            box = detection.get("normalized_bounding_box")
            if label not in required_labels or not _is_box(box):
                continue
            predictions[label].append(
                (
                    float(detection.get("confidence", 0.0)),
                    image_path.name,
                    [float(value) for value in box],
                )
            )

    raw_per_class = {
        label: _class_metrics(targets[label], predictions[label])
        for label in sorted(required_labels)
    }
    per_class = {
        label: {
            **metric,
            "ap50": round(metric["ap50"], 4),
        }
        for label, metric in raw_per_class.items()
    }
    raw_map50 = sum(
        metric["ap50"]
        for metric in raw_per_class.values()
    ) / len(raw_per_class)
    return {
        "class_map": class_map,
        "per_class": per_class,
        "aggregate_map50": round(raw_map50, 4),
        "evaluated_images": evaluated_images,
        "skipped_images": skipped_images,
        "acceptance": yolo_gate(raw_per_class, 0.90),
    }


def iou_xyxy(left: Sequence[float], right: Sequence[float]) -> float:
    """Return intersection-over-union for two xyxy boxes."""
    overlap_left = max(left[0], right[0])
    overlap_top = max(left[1], right[1])
    overlap_right = min(left[2], right[2])
    overlap_bottom = min(left[3], right[3])
    intersection = max(0.0, overlap_right - overlap_left) * max(
        0.0,
        overlap_bottom - overlap_top,
    )
    union = _box_area(left) + _box_area(right) - intersection
    return intersection / union if union else 0.0


def yolo_gate(
    metrics: dict[str, dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """Require every class AP and aggregate mAP to meet the threshold."""
    failed_classes = sorted(
        label
        for label, metric in metrics.items()
        if metric.get("ap50") is None or metric["ap50"] < threshold
    )
    aggregate_map50 = (
        sum(float(metric["ap50"]) for metric in metrics.values()) / len(metrics)
        if metrics
        else 0.0
    )
    aggregate_passed = bool(metrics) and aggregate_map50 >= threshold
    return {
        "passed": not failed_classes and aggregate_passed,
        "failed_classes": failed_classes,
        "aggregate_passed": aggregate_passed,
        "threshold": threshold,
    }


def _required_class_ids(
    class_map: dict[int, str],
    required_labels: set[str],
) -> dict[str, int]:
    matches = {
        label: [
            class_id
            for class_id, class_name in class_map.items()
            if class_name == label
        ]
        for label in required_labels
    }
    invalid = {
        label: ids
        for label, ids in matches.items()
        if len(ids) != 1
    }
    if invalid:
        details = ", ".join(
            f"{label}={len(ids)}"
            for label, ids in sorted(invalid.items())
        )
        raise ValueError(
            "required YOLO class mapping must contain each label exactly once: "
            + details
        )
    return {
        label: ids[0]
        for label, ids in matches.items()
    }


def _read_yolo_labels(path: Path) -> list[tuple[int, list[float]]]:
    labels = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"invalid YOLO label at {path}:{line_number}")
        try:
            class_id = int(parts[0])
            center_x, center_y, width, height = map(float, parts[1:])
        except ValueError as error:
            raise ValueError(
                f"invalid YOLO label at {path}:{line_number}"
            ) from error
        labels.append(
            (
                class_id,
                [
                    center_x - width / 2,
                    center_y - height / 2,
                    center_x + width / 2,
                    center_y + height / 2,
                ],
            )
        )
    return labels


def _class_metrics(
    targets_by_image: dict[str, list[list[float]]],
    predictions: list[tuple[float, str, list[float]]],
) -> dict[str, Any]:
    target_count = sum(len(boxes) for boxes in targets_by_image.values())
    matched: set[tuple[str, int]] = set()
    true_positive_flags = []
    for _, image_name, prediction_box in sorted(
        predictions,
        key=lambda item: item[0],
        reverse=True,
    ):
        candidates = [
            (iou_xyxy(prediction_box, target_box), index)
            for index, target_box in enumerate(targets_by_image.get(image_name, []))
            if (image_name, index) not in matched
        ]
        best_iou, best_index = max(candidates, default=(0.0, -1))
        is_true_positive = best_iou >= 0.50
        true_positive_flags.append(is_true_positive)
        if is_true_positive:
            matched.add((image_name, best_index))

    true_positives = sum(true_positive_flags)
    precision = true_positives / len(predictions) if predictions else 0.0
    recall = true_positives / target_count if target_count else 0.0
    return {
        "targets": target_count,
        "predictions": len(predictions),
        "true_positives": true_positives,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "ap50": _interpolated_ap(true_positive_flags, target_count),
    }


def _interpolated_ap(
    true_positive_flags: list[bool],
    target_count: int,
) -> float:
    if not target_count:
        return 0.0
    precisions = []
    recalls = []
    true_positives = 0
    for rank, is_true_positive in enumerate(true_positive_flags, start=1):
        true_positives += is_true_positive
        precisions.append(true_positives / rank)
        recalls.append(true_positives / target_count)
    return sum(
        max(
            (
                precision
                for precision, recall in zip(precisions, recalls, strict=True)
                if recall >= threshold / 100
            ),
            default=0.0,
        )
        for threshold in range(101)
    ) / 101


def _box_area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _is_box(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) == 4
    )


def _detection_class_id(detection: dict[str, Any]) -> int:
    try:
        return int(detection.get("class_id", -1))
    except (TypeError, ValueError):
        return -1


def _field_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = document.get("fields", {})
    if isinstance(fields, dict):
        return {
            name: value
            for name, value in fields.items()
            if isinstance(value, dict)
        }
    if isinstance(fields, list):
        return {
            str(field["field_name"]): field
            for field in fields
            if isinstance(field, dict) and field.get("field_name")
        }
    return {}


def _actual_value(
    name: str,
    field: dict[str, Any] | None,
) -> dict[str, Any]:
    field = field or {}
    actual = {"value": field.get("value")}
    if name == "transaction_amount" or "currency" in field:
        actual["currency"] = field.get("currency")
    return actual


def _target_value(target: Any) -> Any:
    return target.get("value") if isinstance(target, dict) else target


def _field_matches(
    name: str,
    field: dict[str, Any] | None,
    target: Any,
) -> bool:
    field = field or {}
    if normalize_field_value(name, field.get("value")) != normalize_field_value(
        name,
        _target_value(target),
    ):
        return False
    expected_currency = target.get("currency") if isinstance(target, dict) else None
    if expected_currency is None:
        return True
    return normalize_field_value("currency", field.get("currency")) == normalize_field_value(
        "currency",
        expected_currency,
    )


def _mismatch_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples = []
    for row in rows:
        for field in CORE_FIELDS:
            if row.get("checks", {}).get(field, True):
                continue
            expected = row.get("expected", {}).get(field)
            actual = row.get("actual", {}).get(field, {"value": None})
            expected_value = _target_value(expected)
            actual_value = actual.get("value") if isinstance(actual, dict) else actual
            reason = "mismatched"
            if expected_value is None and actual_value is not None:
                reason = "unexpected_prediction"
            elif expected_value is not None and actual_value is None:
                reason = "missing_prediction"
            examples.append(
                {
                    "file_name": row.get("file_name"),
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "reason": reason,
                }
            )
    return examples
