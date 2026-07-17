import json
from pathlib import Path

from app.application.dto.request_normalizer import normalize_request


def test_normalizes_reference_request_without_losing_top_level_context() -> None:
    payload = json.loads(Path("AI_Verification_Request_Contract_v1.json").read_text(encoding="utf-8"))

    request = normalize_request(payload)

    assert request.business_entity_id == "000123456"
    assert request.business_entity_year == "2026"
    assert request.transaction_type == "REIMBURSEMENT_TOLL"
    assert request.business_context["vendor_name"] == "PT Example Vendor"
    assert request.business_context["total_amount"] == 5500000
    assert request.business_context["created_datetime"] == "2026-06-30T09:30:00"
    assert request.documents[0].file_name == "invoice.pdf"
    assert request.documents[0].mime_type == "application/pdf"
