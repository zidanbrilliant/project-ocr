"""Deterministic field metrics for local model evaluation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CORE_FIELDS = ("document_number", "transaction_amount", "transaction_date")


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
