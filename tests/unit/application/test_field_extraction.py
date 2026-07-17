from app.application.services.field_extraction_service import FieldExtractionService


def test_extracts_common_invoice_fields_with_evidence() -> None:
    text = """Inv No. INV/123/2026
Tanggal: 20/06/2026
Vendor: PT Toyota Example
Total Bayar: Rp 7,500,000"""

    fields = FieldExtractionService().extract_from_ocr({"raw_text": text, "tokens_json": []})

    assert fields["document_number"]["value"] == "INV/123/2026"
    assert fields["transaction_amount"]["value"] == 7500000.0
    assert fields["transaction_date"]["value"] == "20/06/2026"
    assert fields["vendor_name"]["source_text"] == "PT Toyota Example"


def test_resolves_multi_page_fields_with_page_provenance() -> None:
    pages = [
        {"raw_text": "Invoice No: INV-77", "tokens_json": []},
        {"raw_text": "Grand Total: Rp 8.000.000", "tokens_json": []},
    ]

    fields = FieldExtractionService().extract_document_pages(pages)

    assert fields["document_number"]["source_page_number"] == 1
    assert fields["transaction_amount"]["value"] == 8000000.0
    assert fields["transaction_amount"]["source_page_number"] == 2
