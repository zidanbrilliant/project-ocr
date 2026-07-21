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


def test_strong_single_source_field_is_kept_when_visual_page_is_unavailable(monkeypatch) -> None:
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


def test_visual_model_extracts_invoice_directly_without_candidate_gating(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "document_number",
                "page_number": 1,
                "raw_value": "INV-22",
                "evidence_quote": "Invoice Number: INV-22",
                "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
            }
        ]
    )
    pages = [{"raw_text": "Invoice Number: INV-22\nPO Number: PO-22"}]

    resolved, audit = asyncio.run(FieldReasoningService(adapter).resolve({}, "INV", pages, [b"page-image"]))

    assert resolved["document_number"]["value"] == "INV-22"
    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert resolved["document_number"]["independent_evidence_count"] == 2
    assert audit["engine"] == "qwen3-vl-8b"
    assert audit["visual_pages"] == [1]
    assert adapter.request["requested_fields"] == ["document_number", "transaction_date"]
    assert adapter.request["images"][0]["page_number"] == 1
    assert "candidates" not in adapter.request


def test_grounded_visual_value_overrides_a_wrong_deterministic_invoice(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "document_number",
                "page_number": 1,
                "raw_value": "INV-999",
                "evidence_quote": "Invoice Number: INV-999",
                "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
            }
        ]
    )
    candidates = _invoice_candidates()

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve(
            candidates,
            "INV",
            [{"raw_text": "Invoice Number: INV-999\nPO Number: INV-22"}],
            [b"page-image"],
        )
    )

    assert resolved["document_number"]["value"] == "INV-999"
    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert audit["overrides"] == ["document_number"]


def test_visual_model_can_confirm_a_generic_date_as_the_issue_date(monkeypatch) -> None:
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

    assert resolved["transaction_date"]["value"] == "2023-10-31"
    assert resolved["transaction_date"]["verification_status"] == "VERIFIED"


def test_visual_model_can_verify_an_unlabelled_date(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "transaction_date",
                "page_number": 1,
                "raw_value": "01 April 2026",
                "evidence_quote": "Cibitung,\n01 April 2026",
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

    assert "candidates" not in adapter.request
    assert resolved["transaction_date"]["value"] == "2026-04-01"
    assert resolved["transaction_date"]["verification_status"] == "VERIFIED"


def test_visual_model_cannot_relabel_due_date_as_issue_date(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "transaction_date",
                "page_number": 1,
                "raw_value": "31/10/2023",
                "evidence_quote": "Due Date: 31/10/2023",
                "reason_code": "DOCUMENT_ISSUE_DATE",
            }
        ]
    )

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve({}, "INV", [{"raw_text": "Due Date: 31/10/2023"}], [b"page"])
    )

    assert resolved["transaction_date"]["status"] == "NOT_FOUND"
    assert not audit["used"]


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
