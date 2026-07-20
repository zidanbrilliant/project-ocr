import asyncio

from app.application.services.field_reasoning_service import FieldReasoningService


class _Adapter:
    is_available = True
    load_error = None

    async def warmup(self) -> None:
        return None

    async def select(self, request):
        assert request["candidates"]["transaction_amount"][1]["candidate_id"] == "transaction_amount-1"
        return {
            "decisions": [
                {
                    "field_name": "transaction_amount",
                    "candidate_id": "transaction_amount-1",
                    "confidence": 0.97,
                    "reason_code": "FINAL_PAYABLE_TOTAL",
                }
            ]
        }

    async def summarize(self, request):
        return {"summary": "Amount must match PV amount.", "rule_ids": ["INV-R009"]}


def test_reasoning_can_only_select_existing_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    candidates = {
        "transaction_amount": [
            {"value": 100.0, "confidence": 0.9, "score": 0.9, "source_text": "DPP: 100"},
            {"value": 110.0, "confidence": 0.9, "score": 0.9, "source_text": "Grand Total: 110"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(candidates, "INV"))

    assert resolved["transaction_amount"]["value"] == 110.0
    assert resolved["transaction_amount"]["reasoning_engine"] == "qwen3.5-9b"
    assert audit["resolved_fields"] == ["transaction_amount"]


def test_summary_accepts_only_known_rule_ids(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    service = FieldReasoningService(_Adapter())
    summary = asyncio.run(
        service.summarize("NG", {}, [{"rule_id": "INV-R009", "rule_name": "Amount must match PV amount"}])
    )

    assert summary["engine"] == "qwen3.5-9b"
    assert summary["result"] == "NG"


def test_reasoning_never_receives_due_date_candidates(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    candidates = {
        "transaction_date": [
            {"value": "2026-08-20", "confidence": 0.25, "source_text": "Due Date", "date_role": "due_date"},
            {"value": "2026-08-25", "confidence": 0.25, "source_text": "Due Date", "date_role": "due_date"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(candidates, "INV"))

    assert resolved["transaction_date"]["status"] == "NOT_FOUND"
    assert audit["used"] is False
    assert audit["engine"] == "deterministic"


def test_reasoning_sends_relevant_ocr_pages_to_model(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class ContextAdapter(_Adapter):
        def __init__(self) -> None:
            self.request = None

        async def select(self, request):
            self.request = request
            return {"decisions": []}

    adapter = ContextAdapter()
    candidates = {
        "document_number": [
            {"value": "INV-1", "confidence": 0.8, "score": 0.8, "source_page_number": 2},
            {"value": "INV-2", "confidence": 0.7, "score": 0.7, "source_page_number": 3},
        ]
    }
    pages = [
        {"raw_text": "cover page"},
        {"raw_text": "Invoice No: INV-1"},
        {"raw_text": "Reference: INV-2"},
    ]

    _, audit = asyncio.run(FieldReasoningService(adapter).resolve(candidates, "INV", pages))

    assert adapter.request["document_context"] == [
        {"page_number": 1, "raw_text": "cover page"},
        {"page_number": 2, "raw_text": "Invoice No: INV-1"},
        {"page_number": 3, "raw_text": "Reference: INV-2"},
    ]
    assert audit["context_pages"] == [1, 2, 3]


def test_reasoning_context_keeps_all_pages_within_the_budget() -> None:
    pages = [{"raw_text": f"page {page_number}"} for page_number in range(1, 6)]

    context = FieldReasoningService._document_context(pages, {})

    assert [page["page_number"] for page in context] == [1, 2, 3, 4, 5]


def test_reasoning_does_not_replace_reconciled_final_total(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    candidates = {
        "transaction_amount": [
            {"value": 110.0, "confidence": 0.99, "score": 0.99, "amount_role": "final_total"},
            {"value": 125.0, "confidence": 0.7, "score": 0.7, "amount_role": "unlabelled_currency"},
            {"value": 100.0, "confidence": 0.7, "score": 0.7, "amount_role": "tax_base"},
            {"value": 10.0, "confidence": 0.7, "score": 0.7, "amount_role": "tax"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(candidates, "INV"))

    assert resolved["transaction_amount"]["value"] == 110.0
    assert audit["used"] is False


def test_reasoning_preserves_reconciled_evidence_for_the_same_value(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class SameValueAdapter(_Adapter):
        async def select(self, request):
            return {
                "decisions": [
                    {
                        "field_name": "transaction_amount",
                        "candidate_id": "transaction_amount-0",
                        "reason_code": "FINAL_PAYABLE_TOTAL",
                    }
                ]
            }

    candidates = {
        "transaction_amount": [
            {"value": 110.0, "confidence": 0.75, "score": 0.75, "amount_role": "final_total"},
            {"value": 100.0, "confidence": 0.2, "score": 0.2, "amount_role": "tax_base"},
            {"value": 10.0, "confidence": 0.2, "score": 0.2, "amount_role": "tax"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(SameValueAdapter()).resolve(candidates, "INV"))

    assert resolved["transaction_amount"]["validation"] == "RECONCILED_DPP_PLUS_TAX"
    assert resolved["transaction_amount"]["confidence"] == 0.995
    assert audit["used"] is False


def test_reasoning_checks_a_single_weak_core_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class RejectingAdapter(_Adapter):
        async def select(self, request):
            assert request["candidates"]["transaction_amount"][0]["value"] == 999.0
            return {"decisions": []}

    candidates = {
        "transaction_amount": [
            {
                "value": 999.0,
                "confidence": 0.62,
                "score": 0.62,
                "source_text": "USD 999",
                "candidate_only": True,
            }
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(RejectingAdapter()).resolve(candidates, "INV"))

    assert resolved["transaction_amount"]["status"] == "NOT_FOUND"
    assert audit["used"] is False
    assert audit["engine"] == "qwen3.5-9b"


def test_reasoning_receives_candidate_label_relation(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class RelationAdapter(_Adapter):
        async def select(self, request):
            candidate = request["candidates"]["transaction_amount"][0]
            assert candidate["label_relation"] == "before_label"
            assert candidate["label_distance"] == 1
            return {"decisions": []}

    candidates = {
        "transaction_amount": [
            {
                "value": 1240.5,
                "confidence": 0.78,
                "score": 0.78,
                "source_text": "USD 1,240.50\nBalance Due",
                "label_relation": "before_label",
                "label_distance": 1,
                "candidate_only": True,
            }
        ]
    }

    _, audit = asyncio.run(FieldReasoningService(RelationAdapter()).resolve(candidates, "INV"))

    assert audit["engine"] == "qwen3.5-9b"


def test_reasoning_can_select_a_raw_identifier_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class IdentifierAdapter(_Adapter):
        async def select(self, request):
            assert request["candidates"]["document_number"][0]["value"] == "RI-23014073"
            return {
                "decisions": [
                    {
                        "field_name": "document_number",
                        "candidate_id": "document_number-0",
                        "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
                    }
                ]
            }

    candidates = {
        "document_number": [
            {
                "value": "RI-23014073",
                "confidence": 0.2,
                "score": 0.2,
                "source_text": "RI - 23014073\nInvoice Number",
                "candidate_only": True,
            }
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(IdentifierAdapter()).resolve(candidates, "INV"))

    assert resolved["document_number"]["value"] == "RI-23014073"
    assert audit["resolved_fields"] == ["document_number"]


def test_reasoning_deduplicates_values_before_selecting_candidates(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class UniqueAdapter(_Adapter):
        async def select(self, request):
            values = [item["value"] for item in request["candidates"]["transaction_amount"]]
            assert values == [110.0, 100.0]
            return {"decisions": []}

    candidates = {
        "transaction_amount": [
            {"value": 110.0, "confidence": 0.8, "score": 0.8, "source_text": "Total: 110"},
            {"value": 110.0, "confidence": 0.7, "score": 0.7, "source_text": "duplicate 110"},
            {"value": 100.0, "confidence": 0.6, "score": 0.6, "source_text": "Subtotal: 100"},
        ]
    }

    _, audit = asyncio.run(FieldReasoningService(UniqueAdapter()).resolve(candidates, "INV"))

    assert audit["engine"] == "qwen3.5-9b"


def test_reasoning_keeps_equal_values_in_different_currencies(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class CurrencyAdapter(_Adapter):
        async def select(self, request):
            currencies = [item["currency"] for item in request["candidates"]["transaction_amount"]]
            assert currencies == ["USD", "JPY"]
            return {"decisions": []}

    candidates = {
        "transaction_amount": [
            {"value": 100.0, "currency": "USD", "confidence": 0.2, "score": 0.2},
            {"value": 100.0, "currency": "JPY", "confidence": 0.2, "score": 0.2},
        ]
    }

    asyncio.run(FieldReasoningService(CurrencyAdapter()).resolve(candidates, "INV"))


def test_reasoning_can_rescue_exact_value_from_raw_ocr(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class GroundedAdapter(_Adapter):
        async def select(self, request):
            assert request["candidates"]["document_number"] == []
            return {
                "decisions": [
                    {
                        "field_name": "document_number",
                        "candidate_id": None,
                        "page_number": 1,
                        "raw_value": "RI - 23014073",
                        "evidence_quote": "Invoice Number: RI - 23014073",
                        "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
                    },
                    {
                        "field_name": "transaction_amount",
                        "candidate_id": None,
                        "page_number": 1,
                        "raw_value": "USD 1,240.50",
                        "evidence_quote": "Balance Due: USD 1,240.50",
                        "reason_code": "FINAL_PAYABLE_TOTAL",
                    },
                ]
            }

    pages = [{"raw_text": "Invoice Number: RI - 23014073\nBalance Due: USD 1,240.50"}]
    resolved, audit = asyncio.run(FieldReasoningService(GroundedAdapter()).resolve({}, "INV", pages))

    assert resolved["document_number"]["value"] == "RI-23014073"
    assert resolved["transaction_amount"]["value"] == 1240.5
    assert resolved["transaction_amount"]["currency"] == "USD"
    assert resolved["transaction_amount"]["extraction_method"] == "qwen_grounded_span"
    assert audit["resolved_fields"] == ["document_number", "transaction_amount"]


def test_reasoning_can_override_a_single_wrong_heuristic_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class CorrectingAdapter(_Adapter):
        async def select(self, request):
            assert request["candidates"]["document_number"][0]["value"] == "PO-7788"
            return {
                "decisions": [
                    {
                        "field_name": "document_number",
                        "page_number": 1,
                        "raw_value": "INV-2026-0042",
                        "evidence_quote": "Invoice Number: INV-2026-0042",
                        "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
                    }
                ]
            }

    candidates = {
        "document_number": [
            {
                "value": "PO-7788",
                "confidence": 0.95,
                "score": 0.95,
                "source_text": "Reference: PO-7788",
            }
        ]
    }
    pages = [{"raw_text": "Reference: PO-7788\nInvoice Number: INV-2026-0042"}]

    resolved, audit = asyncio.run(FieldReasoningService(CorrectingAdapter()).resolve(candidates, "INV", pages))

    assert resolved["document_number"]["value"] == "INV-2026-0042"
    assert audit["resolved_fields"] == ["document_number"]


def test_reasoning_rejects_model_value_not_present_in_ocr(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class HallucinatingAdapter(_Adapter):
        async def select(self, request):
            return {
                "decisions": [
                    {
                        "field_name": "document_number",
                        "page_number": 1,
                        "raw_value": "INV-999",
                        "evidence_quote": "Invoice Number: INV-999",
                        "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
                    }
                ]
            }

    resolved, audit = asyncio.run(
        FieldReasoningService(HallucinatingAdapter()).resolve({}, "INV", [{"raw_text": "Invoice Number: INV-123"}])
    )

    assert "document_number" not in resolved
    assert audit["used"] is False


def test_reasoning_rejects_non_payable_grounded_amount(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class SubtotalAdapter(_Adapter):
        async def select(self, request):
            return {
                "decisions": [
                    {
                        "field_name": "transaction_amount",
                        "page_number": 1,
                        "raw_value": "USD 100.00",
                        "evidence_quote": "Subtotal: USD 100.00",
                        "reason_code": "FINAL_PAYABLE_TOTAL",
                    }
                ]
            }

    resolved, audit = asyncio.run(
        FieldReasoningService(SubtotalAdapter()).resolve({}, "INV", [{"raw_text": "Subtotal: USD 100.00"}])
    )

    assert "transaction_amount" not in resolved
    assert audit["used"] is False


def test_reasoning_does_not_drop_candidates_after_twelve(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class CompleteAdapter(_Adapter):
        async def select(self, request):
            assert len(request["candidates"]["document_number"]) == 13
            return {"decisions": []}

    candidates = {
        "document_number": [
            {"value": f"INV-{index}", "confidence": 0.5, "score": 0.5, "source_text": f"INV-{index}"}
            for index in range(13)
        ]
    }

    _, audit = asyncio.run(FieldReasoningService(CompleteAdapter()).resolve(candidates, "INV"))

    assert audit["engine"] == "qwen3.5-9b"
