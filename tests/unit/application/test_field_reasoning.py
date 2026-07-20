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
    fields = {"transaction_amount": {"value": 100.0, "status": "FOUND", "confidence": 0.99}}
    candidates = {
        "transaction_amount": [
            {"value": 100.0, "confidence": 0.9, "source_text": "DPP: 100"},
            {"value": 110.0, "confidence": 0.9, "source_text": "Grand Total: 110"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(fields, candidates, "INV"))

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
    fields = {"transaction_date": {"value": None, "status": "NOT_FOUND", "confidence": 0.0}}
    candidates = {
        "transaction_date": [
            {"value": "2026-08-20", "confidence": 0.25, "source_text": "Due Date", "date_role": "due_date"},
            {"value": "2026-08-25", "confidence": 0.25, "source_text": "Due Date", "date_role": "due_date"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(fields, candidates, "INV"))

    assert resolved == fields
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
    fields = {"document_number": {"value": "INV-1", "status": "FOUND", "confidence": 0.8}}
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

    _, audit = asyncio.run(FieldReasoningService(adapter).resolve(fields, candidates, "INV", pages))

    assert adapter.request["document_context"] == [
        {"page_number": 1, "raw_text": "cover page"},
        {"page_number": 2, "raw_text": "Invoice No: INV-1"},
        {"page_number": 3, "raw_text": "Reference: INV-2"},
    ]
    assert audit["context_pages"] == [1, 2, 3]


def test_reasoning_does_not_replace_reconciled_final_total(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    fields = {
        "transaction_amount": {
            "value": 110.0,
            "status": "FOUND",
            "confidence": 0.99,
            "amount_role": "final_total",
            "validation": "RECONCILED_DPP_PLUS_TAX",
        }
    }
    candidates = {
        "transaction_amount": [
            {"value": 110.0, "confidence": 0.99, "score": 0.99, "amount_role": "final_total"},
            {"value": 125.0, "confidence": 0.7, "score": 0.7, "amount_role": "unlabelled_currency"},
        ]
    }

    resolved, audit = asyncio.run(FieldReasoningService(_Adapter()).resolve(fields, candidates, "INV"))

    assert resolved["transaction_amount"]["value"] == 110.0
    assert audit["used"] is False
