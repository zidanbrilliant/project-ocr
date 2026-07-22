from scripts.benchmark_pipeline import evaluate_candidate_recall, evaluate_fields


def test_evaluate_fields_requires_exact_core_values_and_currency() -> None:
    result = {
        "fields": {
            "document_number": {"value": "INV-7"},
            "transaction_amount": {"value": 1_110_000.0, "currency": "IDR"},
            "transaction_date": {"value": "2026-07-20"},
        }
    }
    expected = {
        "document_number": "INV-7",
        "transaction_amount": {"value": 1_110_000, "currency": "IDR"},
        "transaction_date": "2026-07-20",
    }

    evaluation = evaluate_fields(result, expected)

    assert evaluation["checks"] == {
        "document_number": True,
        "transaction_amount": True,
        "transaction_date": True,
    }
    assert evaluation["all_core_fields_exact"] is True


def test_candidate_recall_checks_value_and_currency_and_skips_null_targets() -> None:
    result = {
        "field_candidate_audit": {
            "document_number": [{"value": "INV-7"}],
            "transaction_amount": [
                {"value": 1_110_000.0, "currency": "USD"},
                {"value": 1_110_000.0, "currency": "IDR"},
            ],
        }
    }
    expected = {
        "document_number": "INV-7",
        "transaction_amount": {"value": 1_110_000, "currency": "IDR"},
        "transaction_date": None,
    }

    assert evaluate_candidate_recall(result, expected) == {
        "document_number": True,
        "transaction_amount": True,
    }
