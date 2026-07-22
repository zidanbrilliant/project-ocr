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


class DelayedReadyAdapter(VisualAdapter):
    is_available = False

    async def select(self, request):
        self.is_available = True
        return await super().select(request)


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


def test_deterministic_fallback_remains_visible_when_ocr_context_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter()
    candidates = {
        "document_number": [{"value": "INV-1", "confidence": 0.99, "score": 0.99}],
        "transaction_amount": [{"value": 110.0, "confidence": 0.99, "score": 0.99, "amount_role": "final_total"}],
        "transaction_date": [{"value": "2026-01-01", "confidence": 0.9, "score": 0.9, "date_role": "issue_date"}],
    }

    resolved, audit = asyncio.run(FieldReasoningService(adapter).resolve(candidates, "INV"))

    assert resolved["document_number"]["verification_status"] == "FALLBACK_UNVERIFIED"
    assert resolved["document_number"]["confidence"] == 0.99
    assert resolved["document_number"]["manual_review_required"] is True
    assert resolved["transaction_amount"]["status"] == "FOUND"
    assert adapter.request is None
    assert audit["engine"] == "deterministic"


def test_text_model_receives_candidates_but_can_extract_invoice_directly(monkeypatch) -> None:
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

    resolved, audit = asyncio.run(FieldReasoningService(adapter).resolve({}, "INV", pages))

    assert resolved["document_number"]["value"] == "INV-22"
    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert resolved["document_number"]["independent_evidence_count"] == 1
    assert resolved["document_number"]["confidence"] == 0.85
    assert resolved["document_number"]["confidence_calibrated"] is False
    assert audit["engine"] == "qwen3.5-9b"
    assert audit["visual_pages"] == []
    assert adapter.request["requested_fields"] == ["document_number", "transaction_amount", "transaction_date"]
    assert "images" not in adapter.request
    assert adapter.request["candidates"] == []


def test_reasoning_retries_an_adapter_that_is_not_ready_at_request_start(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = DelayedReadyAdapter(
        [{
            "field_name": "document_number",
            "page_number": 1,
            "raw_value": "INV-22",
            "evidence_quote": "Invoice Number: INV-22",
        }]
    )

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve({}, "INV", [{"raw_text": "Invoice Number: INV-22"}])
    )

    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert audit["adapter_available"] is True


def test_grounded_text_value_overrides_a_wrong_deterministic_invoice(monkeypatch) -> None:
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
        )
    )

    assert resolved["document_number"]["value"] == "INV-999"
    assert resolved["document_number"]["verification_status"] == "VERIFIED"
    assert audit["overrides"] == ["document_number"]


def test_text_model_can_confirm_a_generic_date_as_the_issue_date(monkeypatch) -> None:
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
        )
    )

    assert resolved["transaction_date"]["value"] == "2023-10-31"
    assert resolved["transaction_date"]["verification_status"] == "VERIFIED"


def test_text_model_can_verify_an_unlabelled_date(monkeypatch) -> None:
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
        FieldReasoningService(adapter).resolve(candidates, "INV", [{"raw_text": "Cibitung,\n01 April 2026"}])
    )

    assert adapter.request["candidates"][0]["field_name"] == "transaction_date"
    assert resolved["transaction_date"]["value"] == "2026-04-01"
    assert resolved["transaction_date"]["verification_status"] == "VERIFIED"


def test_text_model_resolves_realistic_spaced_invoice_and_city_date(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [
            {
                "field_name": "document_number",
                "page_number": 1,
                "raw_value": "030 NTC0426",
                "evidence_quote": "No. Invoice : 030 NTC0426",
                "reason_code": "COMMERCIAL_DOCUMENT_NUMBER",
            },
            {
                "field_name": "transaction_date",
                "page_number": 1,
                "raw_value": "01 April 2026",
                "evidence_quote": "Cibitung,\n01 April 2026",
                "reason_code": "DOCUMENT_ISSUE_DATE",
            },
        ]
    )
    pages = [{"raw_text": "No. Invoice : 030 NTC0426\nCibitung,\n01 April 2026"}]

    resolved, _ = asyncio.run(FieldReasoningService(adapter).resolve({}, "INV", pages))

    assert resolved["document_number"]["value"] == "030 NTC0426"
    assert resolved["transaction_date"]["value"] == "2026-04-01"


def test_text_model_cannot_relabel_due_date_as_issue_date(monkeypatch) -> None:
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
        FieldReasoningService(adapter).resolve({}, "INV", [{"raw_text": "Due Date: 31/10/2023"}])
    )

    assert resolved["transaction_date"]["status"] == "NOT_FOUND"
    assert not audit["used"]


def test_invalid_text_response_keeps_deterministic_evidence_visible(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)

    class InvalidAdapter(VisualAdapter):
        async def select(self, request):
            return {"error": "invalid_model_json", "decisions": []}

    candidates = _invoice_candidates()
    resolved, audit = asyncio.run(
        FieldReasoningService(InvalidAdapter()).resolve(candidates, "INV", [{"raw_text": "x"}])
    )

    assert resolved["document_number"]["value"] == "INV-22"
    assert resolved["document_number"]["verification_status"] == "FALLBACK_UNVERIFIED"
    assert audit["error"] == "invalid_model_json"


def test_reasoning_audit_records_rejected_ungrounded_model_output(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [{
            "field_name": "document_number",
            "page_number": 1,
            "raw_value": "INV-HALLUCINATED",
            "evidence_quote": "Invoice Number: INV-HALLUCINATED",
        }]
    )

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve({}, "INV", [{"raw_text": "Invoice Number: INV-22"}])
    )

    assert resolved["document_number"]["status"] == "NOT_FOUND"
    assert audit["used"] is False
    assert audit["grounding_rejections"] == [
        {"field": "document_number", "reason": "ungrounded_or_invalid_value"}
    ]


def test_text_model_receives_all_pages_in_document_order(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter()
    pages = [{"raw_text": "first"}, {"raw_text": "second" * 4_000}, {"raw_text": "third"}]

    asyncio.run(FieldReasoningService(adapter).resolve(_invoice_candidates(), "INV", pages))

    assert adapter.request["page_ocr"] == [
        {"page_number": 1, "raw_text": "first"},
        {"page_number": 2, "raw_text": "second" * 4_000},
        {"page_number": 3, "raw_text": "third"},
    ]


def test_text_model_accepts_spacing_and_punctuation_variation_in_grounding(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [{
            "field_name": "document_number",
            "page_number": 1,
            "raw_value": "INV - 22",
            "evidence_quote": "Invoice Number : INV - 22",
        }]
    )

    resolved, _ = asyncio.run(
        FieldReasoningService(adapter).resolve({}, "INV", [{"raw_text": "Invoice Number:\nINV-22"}])
    )

    assert resolved["document_number"]["value"] == "INV-22"


def test_text_model_can_select_a_grounded_final_total_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [{"field_name": "transaction_amount", "action": "SELECT", "candidate_id": "transaction_amount-1"}]
    )
    candidates = {
        "transaction_amount": [
            {
                "value": 1_110_000.0,
                "raw_value": "1.110.000",
                "confidence": 0.9,
                "score": 0.9,
                "amount_role": "final_total",
                "currency": "IDR",
                "source_page_number": 1,
                "source_text": "Grand Total: Rp 1.110.000",
                "source_label": "Grand Total",
            },
            {
                "value": 110_000.0,
                "raw_value": "110.000",
                "confidence": 0.8,
                "score": 0.8,
                "amount_role": "tax",
                "currency": "IDR",
                "source_page_number": 1,
                "source_text": "PPN: Rp 110.000",
                "source_label": "PPN",
            },
        ]
    }

    resolved, _ = asyncio.run(
        FieldReasoningService(adapter).resolve(candidates, "INV", [{"raw_text": "Grand Total: Rp 1.110.000"}])
    )

    assert resolved["transaction_amount"]["value"] == 1_110_000.0
    assert resolved["transaction_amount"]["verification_status"] == "VERIFIED"
    assert resolved["transaction_amount"]["candidate_id"] == "transaction_amount-1"


def test_text_model_cannot_select_a_purchase_order_candidate(monkeypatch) -> None:
    monkeypatch.setattr("app.application.services.field_reasoning_service.settings.REASONING_ENABLED", True)
    adapter = VisualAdapter(
        [{"field_name": "document_number", "action": "SELECT", "candidate_id": "document_number-1"}]
    )
    candidates = {
        "document_number": [
            {
                "value": "PO-123456",
                "confidence": 0.9,
                "score": 0.9,
                "source_page_number": 1,
                "source_text": "PO Number: PO-123456",
                "source_label": "PO Number",
            }
        ]
    }

    resolved, audit = asyncio.run(
        FieldReasoningService(adapter).resolve(candidates, "INV", [{"raw_text": "PO Number: PO-123456"}])
    )

    assert resolved["document_number"]["verification_status"] == "FALLBACK_UNVERIFIED"
    assert audit["grounding_rejections"] == [
        {"field": "document_number", "reason": "ungrounded_or_invalid_value"}
    ]


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
