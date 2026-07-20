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


def test_financials_keep_final_total_and_tax_details_separate() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates(
        [{"raw_text": "DPP: Rp 9.000.000\nPPN: Rp 990.000\nPotongan Harga: Rp 500.000\nGrand Total: Rp 9.990.000"}]
    )

    financials = service.build_financials(candidates, service.resolve_document_candidates(candidates))

    assert financials["final_total"]["value"] == 9_990_000.0
    assert financials["taxable_base"]["value"] == 9_000_000.0
    assert financials["taxes"][0]["value"] == 990_000.0
    assert financials["discounts"][0]["value"] == 500_000.0


def test_invoice_date_does_not_become_invoice_number() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Invoice Date: 20/06/2026"})
    assert "document_number" not in fields


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


def test_extracts_invoice_total_from_nemotron_table_text() -> None:
    text = """FAKTUR PENJUALAN: NO. 2023/AR-SAD000012678
No\tKode Barang\tHarga Jual
1\tA-TYI06-PK020.0\t1.366.800,00
Jumlah Harga Jual\t60.334.000,00
Dikurangi Potongan Harga\t0,00
Dasar Pengenaan Pajak\t60.334.000,00
PPN ( 11 %)\t6.636.740,00
TOTAL\t66.970.740,00"""

    fields = FieldExtractionService().extract_from_ocr({"raw_text": text})

    assert fields["document_number"]["value"] == "2023/AR-SAD000012678"
    assert fields["transaction_amount"]["value"] == 66_970_740.0
    assert fields["transaction_amount"]["raw_value"] == "66.970.740,00"
    assert fields["transaction_amount"]["source_label"] == "total"
    assert fields["transaction_amount"]["validation"] == "RECONCILED_DPP_PLUS_TAX"


def test_preserves_block_evidence_for_each_field() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"tokens_json": [{"text": "Grand Total: Rp 7.500.000", "bbox": [1, 1, 40, 10], "block_id": "p1-b7"}]}
    )

    assert fields["transaction_amount"]["source_block_id"] == "p1-b7"


def test_does_not_pair_adjacent_blocks_without_geometry() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"tokens_json": [{"text": "Vendor"}, {"text": "PT Example Vendor"}]}
    )

    assert "vendor_name" not in fields
