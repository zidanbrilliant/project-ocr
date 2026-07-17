from app.application.services.field_extraction_service import FieldExtractionService


def test_extracts_common_invoice_fields_with_evidence() -> None:
    text = """Inv No. INV/123/2026
Tanggal: 20/06/2026
Vendor: PT Toyota Example
Total Bayar: Rp 7,500,000"""

    fields = FieldExtractionService().extract_from_ocr({"raw_text": text, "tokens_json": []})

    assert fields["document_number"]["value"] == "INV/123/2026"
    assert fields["transaction_amount"]["value"] == 7500000.0
    assert fields["transaction_date"]["value"] == "2026-06-20"
    assert fields["vendor_name"]["source_text"] == "Vendor: PT Toyota Example"


def test_resolves_multi_page_fields_with_page_provenance() -> None:
    pages = [
        {"raw_text": "Invoice No: INV-77", "tokens_json": []},
        {"raw_text": "Grand Total: Rp 8.000.000", "tokens_json": []},
    ]

    fields = FieldExtractionService().extract_document_pages(pages)

    assert fields["document_number"]["source_page_number"] == 1
    assert fields["transaction_amount"]["value"] == 8000000.0
    assert fields["transaction_amount"]["source_page_number"] == 2


def test_prefers_grand_total_over_subtotal_and_tax_base() -> None:
    text = """DPP: Rp 9.000.000
PPN: Rp 990.000
Subtotal: Rp 9.000.000
Grand Total: Rp 9.990.000"""

    fields = FieldExtractionService().extract_from_ocr({"raw_text": text})

    assert fields["transaction_amount"]["value"] == 9_990_000.0
    assert fields["transaction_amount"]["source_label"] == "Grand Total"


def test_marks_equally_specific_conflicting_totals_ambiguous() -> None:
    text = """Grand Total: Rp 1.000.000
Grand Total: Rp 2.000.000"""

    fields = FieldExtractionService().extract_from_ocr({"raw_text": text})

    assert fields["transaction_amount"]["status"] == "AMBIGUOUS"


def test_reads_adjacent_nemotron_label_value_blocks() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {
            "tokens_json": [
                {"text": "Invoice No", "bbox": [10, 10, 100, 30]},
                {"text": "INV-2026-77", "bbox": [120, 10, 240, 30]},
            ]
        }
    )

    assert fields["document_number"]["value"] == "INV-2026-77"
    assert fields["document_number"]["extraction_method"] == "spatial_label_value"


def test_reads_inline_faktur_penjualan_number() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "FAKTUR PENJUALAN NO. 2023/AR-SAD000012678"})

    assert fields["document_number"]["value"] == "2023/AR-SAD000012678"
