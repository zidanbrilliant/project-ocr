import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.application.services import model_evaluation_service
from app.application.services.model_evaluation_service import (
    evaluate_candidate_recall,
    evaluate_fields,
    field_gate,
    normalize_field_value,
    summarize_field_evaluations,
)


def test_normalize_field_value_handles_document_amount_date_and_null() -> None:
    assert normalize_field_value("document_number", " inv-007 ") == "INV-007"
    assert normalize_field_value("transaction_amount", "1,110,000.00") == Decimal(
        "1110000.00"
    )
    assert normalize_field_value("transaction_date", date(2026, 7, 20)) == "2026-07-20"
    assert normalize_field_value("document_number", None) is None


def test_evaluate_fields_compares_amount_with_decimal_and_currency() -> None:
    document = {
        "fields": [
            {"field_name": "document_number", "value": " inv-007 "},
            {
                "field_name": "transaction_amount",
                "value": Decimal("9999999999999999.01"),
                "currency": " idr ",
            },
            {"field_name": "transaction_date", "value": "2026-07-20"},
        ]
    }
    expected = {
        "document_number": "INV-007",
        "transaction_amount": {
            "value": "9,999,999,999,999,999.01",
            "currency": "IDR",
        },
        "transaction_date": "2026-07-20",
    }

    evaluation = evaluate_fields(document, expected)

    assert evaluation["checks"] == {
        "document_number": True,
        "transaction_amount": True,
        "transaction_date": True,
    }
    assert evaluation["all_core_fields_exact"] is True


def test_evaluate_fields_treats_null_as_an_exact_value() -> None:
    evaluation = evaluate_fields(
        {"fields": [{"field_name": "document_number", "value": None}]},
        {"document_number": None},
    )

    assert evaluation["checks"] == {"document_number": True}
    assert evaluation["all_core_fields_exact"] is True


def test_candidate_recall_requires_amount_currency_and_skips_null_target() -> None:
    document = {
        "field_candidate_audit": {
            "document_number": [{"value": " inv-007 "}],
            "transaction_amount": [
                {"value": "1,110,000", "currency": "USD"},
                {"value": Decimal("1110000.00"), "currency": "idr"},
            ],
        }
    }
    expected = {
        "document_number": "INV-007",
        "transaction_amount": {"value": 1_110_000, "currency": "IDR"},
        "transaction_date": None,
    }

    assert evaluate_candidate_recall(document, expected) == {
        "document_number": True,
        "transaction_amount": True,
    }


def test_summary_reports_mismatch_reasons_and_candidate_recall() -> None:
    rows = [
        {
            "file_name": "wrong.png",
            "expected": {
                "document_number": "INV-1",
                "transaction_amount": {"value": 10, "currency": "IDR"},
                "transaction_date": None,
            },
            "actual": {
                "document_number": {"value": "INV-2"},
                "transaction_amount": {"value": None, "currency": None},
                "transaction_date": {"value": "2026-07-20"},
            },
            "checks": {
                "document_number": False,
                "transaction_amount": False,
                "transaction_date": False,
            },
            "candidate_recall": {
                "document_number": True,
                "transaction_amount": False,
            },
        }
    ]

    report = summarize_field_evaluations(rows, threshold=0.85)

    assert report["mismatch_examples"] == [
        {
            "file_name": "wrong.png",
            "field": "document_number",
            "expected": "INV-1",
            "actual": {"value": "INV-2"},
            "reason": "mismatched",
        },
        {
            "file_name": "wrong.png",
            "field": "transaction_amount",
            "expected": {"value": 10, "currency": "IDR"},
            "actual": {"value": None, "currency": None},
            "reason": "missing_prediction",
        },
        {
            "file_name": "wrong.png",
            "field": "transaction_date",
            "expected": None,
            "actual": {"value": "2026-07-20"},
            "reason": "unexpected_prediction",
        },
    ]
    assert report["candidate_metrics"]["document_number"] == {
        "evaluated": 1,
        "correct_candidates": 1,
        "recall": 1.0,
    }
    assert report["candidate_metrics"]["transaction_date"] == {
        "evaluated": 0,
        "correct_candidates": 0,
        "recall": None,
    }


def test_field_gate_requires_each_core_field() -> None:
    report = field_gate(
        {
            "document_number": {"evaluated": 10, "exact_match_rate": 0.85},
            "transaction_amount": {"evaluated": 10, "exact_match_rate": 0.84},
            "transaction_date": {"evaluated": 10, "exact_match_rate": 1.00},
        },
        0.85,
    )

    assert report == {
        "passed": False,
        "failed_fields": ["transaction_amount"],
        "threshold": 0.85,
    }


def test_field_gate_fails_fields_without_evaluated_examples() -> None:
    report = field_gate(
        {
            "document_number": {"evaluated": 0, "exact_match_rate": None},
            "transaction_amount": {"evaluated": 1, "exact_match_rate": 1.0},
            "transaction_date": {"evaluated": 1, "exact_match_rate": 1.0},
        },
        0.85,
    )

    assert report["passed"] is False
    assert report["failed_fields"] == ["document_number"]


class FakeDetector:
    def __init__(
        self,
        class_map: dict[int, str],
        detections: dict[str, list[dict]] | None = None,
    ) -> None:
        self.class_map = class_map
        self._detections = detections or {}

    async def detect(self, image_bytes: bytes) -> list[dict]:
        return self._detections.get(image_bytes.decode(), [])


def _write_yolo_sample(
    root: Path,
    name: str,
    labels: str,
) -> None:
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "images" / f"{name}.png").write_bytes(name.encode())
    (root / "labels" / f"{name}.txt").write_text(labels, encoding="utf-8")


def _detection(
    box: list[float],
    confidence: float = 0.9,
) -> dict:
    return {
        "class_id": 0,
        "confidence": confidence,
        "normalized_bounding_box": box,
    }


def test_yolo_validation_reports_perfect_detection(tmp_path: Path) -> None:
    _write_yolo_sample(tmp_path, "perfect", "0 0.5 0.5 0.4 0.4\n")
    detector = FakeDetector(
        {0: "barcode"},
        {"perfect": [_detection([0.3, 0.3, 0.7, 0.7])]},
    )

    report = asyncio.run(
        model_evaluation_service.evaluate_yolo_validation(
            detector,
            tmp_path,
            {"barcode"},
        )
    )

    assert report == {
        "class_map": {0: "barcode"},
        "per_class": {
            "barcode": {
                "targets": 1,
                "predictions": 1,
                "true_positives": 1,
                "precision": 1.0,
                "recall": 1.0,
                "ap50": 1.0,
            }
        },
        "aggregate_map50": 1.0,
        "evaluated_images": 1,
        "skipped_images": 0,
        "acceptance": {
            "passed": True,
            "failed_classes": [],
            "aggregate_passed": True,
            "threshold": 0.9,
        },
    }


def test_yolo_validation_counts_a_lower_confidence_false_positive(
    tmp_path: Path,
) -> None:
    _write_yolo_sample(tmp_path, "false-positive", "0 0.5 0.5 0.4 0.4\n")
    detector = FakeDetector(
        {0: "barcode"},
        {
            "false-positive": [
                _detection([0.3, 0.3, 0.7, 0.7], 0.9),
                _detection([0.0, 0.0, 0.1, 0.1], 0.8),
            ]
        },
    )

    report = asyncio.run(
        model_evaluation_service.evaluate_yolo_validation(
            detector,
            tmp_path,
            {"barcode"},
        )
    )

    assert report["per_class"]["barcode"]["precision"] == 0.5
    assert report["per_class"]["barcode"]["recall"] == 1.0
    assert report["per_class"]["barcode"]["ap50"] == 1.0


def test_yolo_validation_reports_a_missed_target(tmp_path: Path) -> None:
    _write_yolo_sample(tmp_path, "detected", "0 0.5 0.5 0.4 0.4\n")
    _write_yolo_sample(tmp_path, "missed", "0 0.5 0.5 0.4 0.4\n")
    detector = FakeDetector(
        {0: "barcode"},
        {"detected": [_detection([0.3, 0.3, 0.7, 0.7])]},
    )

    report = asyncio.run(
        model_evaluation_service.evaluate_yolo_validation(
            detector,
            tmp_path,
            {"barcode"},
        )
    )

    assert report["per_class"]["barcode"]["recall"] == 0.5
    assert report["per_class"]["barcode"]["ap50"] == 0.505


def test_yolo_validation_treats_iou_below_half_as_a_miss(
    tmp_path: Path,
) -> None:
    _write_yolo_sample(tmp_path, "low-iou", "0 0.5 0.5 0.4 0.4\n")
    detector = FakeDetector(
        {0: "barcode"},
        {
            "low-iou": [
                _detection([0.436913, 0.3, 0.836913, 0.7]),
            ]
        },
    )

    report = asyncio.run(
        model_evaluation_service.evaluate_yolo_validation(
            detector,
            tmp_path,
            {"barcode"},
        )
    )

    assert abs(
        model_evaluation_service.iou_xyxy(
            [0.3, 0.3, 0.7, 0.7],
            [0.436913, 0.3, 0.836913, 0.7],
        )
        - 0.49
    ) < 1e-6
    assert report["per_class"]["barcode"]["true_positives"] == 0
    assert report["per_class"]["barcode"]["ap50"] == 0.0


def test_yolo_validation_rejects_an_absent_required_class(
    tmp_path: Path,
) -> None:
    _write_yolo_sample(tmp_path, "sample", "0 0.5 0.5 0.4 0.4\n")

    with pytest.raises(ValueError, match="required YOLO class mapping"):
        asyncio.run(
            model_evaluation_service.evaluate_yolo_validation(
                FakeDetector({0: "barcode"}),
                tmp_path,
                {"stamp"},
            )
        )


def test_yolo_gate_fails_when_one_class_is_below_threshold() -> None:
    report = model_evaluation_service.yolo_gate(
        {
            "barcode": {"ap50": 0.99},
            "materai": {"ap50": 0.89},
            "signature": {"ap50": 0.95},
            "stamp": {"ap50": 0.96},
        },
        0.90,
    )

    assert report["failed_classes"] == ["materai"]
    assert report["aggregate_passed"] is True
    assert report["passed"] is False


def test_yolo_validation_gates_on_raw_ap_before_rounding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_yolo_sample(tmp_path, "boundary", "0 0.5 0.5 0.4 0.4\n")
    detector = FakeDetector(
        {0: "barcode"},
        {"boundary": [_detection([0.3, 0.3, 0.7, 0.7])]},
    )
    monkeypatch.setattr(
        model_evaluation_service,
        "_interpolated_ap",
        lambda flags, targets: 0.89996,
    )

    report = asyncio.run(
        model_evaluation_service.evaluate_yolo_validation(
            detector,
            tmp_path,
            {"barcode"},
        )
    )

    assert report["per_class"]["barcode"]["ap50"] == 0.9
    assert report["aggregate_map50"] == 0.9
    assert report["acceptance"]["passed"] is False
    assert report["acceptance"]["failed_classes"] == ["barcode"]
    assert report["acceptance"]["aggregate_passed"] is False


def test_field_gate_uses_raw_counts_instead_of_rounded_display_rate() -> None:
    report = field_gate(
        {
            "document_number": {
                "evaluated": 100_000,
                "exact_matches": 84_999,
                "exact_match_rate": 0.85,
            },
            "transaction_amount": {
                "evaluated": 100_000,
                "exact_matches": 85_000,
                "exact_match_rate": 0.85,
            },
            "transaction_date": {
                "evaluated": 100_000,
                "exact_matches": 100_000,
                "exact_match_rate": 1.0,
            },
        },
        0.85,
    )

    assert report["passed"] is False
    assert report["failed_fields"] == ["document_number"]
