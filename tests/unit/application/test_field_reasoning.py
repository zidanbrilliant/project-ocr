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
