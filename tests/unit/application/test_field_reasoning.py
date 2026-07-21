import asyncio

from app.application.services.field_reasoning_service import FieldReasoningService


class VisualAdapter:
    is_available = True
    load_error = None

    def __init__(self, decisions=None) -> None:
        self.decisions = decisions or []
        self.request = None

    async def select(self, request):
        self.request = request
        return {"decisions": self.decisions}


def _invoice_candidates() -> dict:
    return {
        "document_number": [
            {
                "value": "INV-22",
                "confidence": 0.95,
                "score": 0.95,
                "source_page_number": 1,
                "source_text": "Invoice Number: INV-22",
            },
            {
                "value": "PO-22",
                "confidence": 0.8,
                "score": 0.8,
                "source_page_number": 1,
                "source_text": "PO Number: PO-22",
            },
        ]
    }


def test_strong_single_source_field_is_not_sent_to_visual_model(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter()
    candidates = {
        "document_number": [{"value": "INV-1", "confidence": 0.99, "score": 0.99}],
        "transaction_amount": [{"value": 110.0, "confidence": 0.99, "score": 0.99, "amount_role": "final_total"}],
        "transaction_date": [{"value": "2026-01-01", "confidence": 0.9, "score": 0.9, "date_role": "issue_date"}],
    }

    resolved, audit = asyncio.run(FieldReasoningService(adapter).resolve(candidates, "INV"))

    assert resolved["document_number"]["verification_status"] == "SINGLE_SOURCE"
    assert resolved["transaction_amount"]["status"] == "FOUND"
    assert adapter.request is None
    assert audit["engine"] == "deterministic"


def test_visual_model_verifies_ambiguous_invoice_with_page_image(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "document_number",
                "candidate_id": "document_number-0",
                "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
            }
        ]
    )
    candidates = _invoice_candidates()
    pages = [{"raw_text": "Invoice Number: INV-22\nPO Number: PO-22"}]

    resolved, audit = asyncio.run(FieldReasoningService(adapter).resolve(candidates, "INV", pages, [b"page-image"]))

    assert resolved["document_number"]["value"] == "INV-22"
    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert resolved["document_number"]["independent_evidence_count"] == 2
    assert audit["engine"] == "qwen3-vl-8b"
    assert audit["visual_pages"] == [1]
    assert adapter.request["requested_fields"] == ["document_number", "transaction_date"]
    assert adapter.request["images"][0]["page_number"] == 1


def test_visual_conflict_never_overwrites_a_strong_invoice(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "document_number",
                "candidate_id": "document_number-1",
                "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
            }
        ]
    )
    candidates = _invoice_candidates()

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve(candidates, "INV", [{"raw_text": "x"}], [b"page-image"])
    )

    assert resolved["document_number"]["status"] == "NOT_FOUND"
    assert resolved["document_number"]["reason_code"] == "DETERMINISTIC_VISUAL_CONFLICT"
    assert audit["conflicts"] == ["document_number"]


def test_generic_date_is_not_sent_as_an_issue_date_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [{
            "field_name": "transaction_date",
            "page_number": 1,
            "raw_value": "31/10/2023",
            "evidence_quote": "Date: 31/10/2023",
        }]
    )

    resolved, _ = asyncio.run(
        FieldReasoningService(adapter).resolve(
            {
                "transaction_date": [
                    {"value": "2023-10-31", "confidence": 0.9, "score": 0.9, "date_role": "generic_date"}
                ]
            },
            "INV",
            [{"raw_text": "Date: 31/10/2023"}],
            [b"page-image"],
        )
    )

    assert resolved["transaction_date"]["status"] == "NOT_FOUND"


def test_visual_model_can_verify_an_unlabelled_date(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "transaction_date",
                "candidate_id": "transaction_date-0",
                "reason_code": "DOCUMENT_ISSUE_DATE",
            }
        ]
    )
    candidates = {
        "transaction_date": [
            {
                "value": "2026-04-01",
                "confidence": 0.45,
                "score": 0.45,
                "date_role": "unlabelled",
                "source_page_number": 1,
                "source_text": "Cibitung,\n01 April 2026",
            }
        ]
    }

    resolved, _ = asyncio.run(
        FieldReasoningService(adapter).resolve(candidates, "INV", [{"raw_text": "Cibitung,\n01 April 2026"}], [b"page"])
    )

    assert adapter.request["candidates"]["transaction_date"][0]["value"] == "2026-04-01"
    assert resolved["transaction_date"]["value"] == "2026-04-01"
    assert resolved["transaction_date"]["verification_status"] == "VERIFIED"


def test_invalid_visual_response_keeps_strong_deterministic_evidence(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class InvalidAdapter(VisualAdapter):
        async def select(self, request):
            return {"error": "invalid_model_json", "decisions": []}

    candidates = _invoice_candidates()
    resolved, audit = asyncio.run(
        FieldReasoningService(InvalidAdapter()).resolve(candidates, "INV", [{"raw_text": "x"}], [b"page-image"])
    )

    assert resolved["document_number"]["value"] == "INV-22"
    assert resolved["document_number"]["verification_status"] == "SINGLE_SOURCE"
    assert audit["error"] == "invalid_model_json"


def test_summary_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    summary = asyncio.run(
        FieldReasoningService(VisualAdapter()).summarize("NG", {}, [{"rule_name": "Amount required"}])
    )

    assert summary == {
        "result": "NG",
        "failed_items": ["Amount required"],
        "reason": "Amount required",
        "recommendations": [],
        "engine": "deterministic",
    }
