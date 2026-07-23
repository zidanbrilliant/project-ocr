from datetime import date
from decimal import Decimal

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
