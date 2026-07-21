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


def test_ignores_unlabelled_currency_amounts_when_total_label_is_missing() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates(
        [
            {
                "raw_text": "Harga Barang Rp 900.000\nPPN Rp 99.000\nRp 999.000",
            }
        ]
    )
    assert {item["value"] for item in candidates["transaction_amount"]} == {99_000.0}
    assert service.resolve_document_candidates(candidates)["transaction_amount"]["value"] is None


def test_extracts_invoice_reference_and_final_total() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "Invoice Reference: INV-REF/2026-77\nFinal Total: USD 1,240.50"}
    )

    assert fields["document_number"]["value"] == "INV-REF/2026-77"
    assert fields["transaction_amount"]["value"] == 1240.5
    assert fields["transaction_amount"]["currency"] == "USD"
    assert fields["transaction_amount"]["amount_role"] == "final_total"


def test_supports_jpy_currency_symbol_for_explicit_final_total() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Final Total: ¥ 24,000"})

    assert fields["transaction_amount"]["value"] == 24_000.0
    assert fields["transaction_amount"]["currency"] == "JPY"


def test_does_not_create_amount_field_from_unlabelled_currency_values() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "USD 120.00\nJPY 24,000"})

    assert "transaction_amount" not in fields


def test_extracts_issue_date_inside_text_and_rejects_due_date() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "Invoice Date: Jakarta, 20 Juli 2026 14:30\nDue Date: 20/08/2026"}
    )

    assert fields["transaction_date"]["value"] == "2026-07-20"
    assert "Invoice Date" in fields["transaction_date"]["source_text"]


def test_extracts_numeric_receipt_number_and_short_dot_date() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "No Nota: 00012345\nTanggal Nota: 21.07.26"})

    assert fields["document_number"]["value"] == "00012345"
    assert fields["transaction_date"]["value"] == "2026-07-21"


def test_preserves_letter_number_invoice_id_with_spaced_separators() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Invoice No: RI - 23014073"})

    assert fields["document_number"]["value"] == "RI-23014073"
    assert fields["document_number"]["raw_value"] == "RI - 23014073"


def test_extracts_spaced_invoice_id_without_colon() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Invoice Reference RI / 2301 - A77"})

    assert fields["document_number"]["value"] == "RI/2301-A77"


def test_recovers_invoice_number_and_total_split_across_three_ocr_lines() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates(
        [
        {
            "raw_text": """Invoice Serial Number
RI
-
23014073
Grand Amount
USD
1,240.50"""
        }
        ]
    )

    invoice = next(
        item
        for item in candidates["document_number"]
        if item["value"] == "RI-23014073" and item["extraction_method"] == "context_label_value"
    )
    total = next(
        item
        for item in candidates["transaction_amount"]
        if item["value"] == 1240.5 and item["extraction_method"] == "context_label_value"
    )
    assert invoice["candidate_only"] and invoice["label_relation"] == "after_label"
    assert total["candidate_only"] and total["extraction_method"] == "context_label_value"


def test_recovers_short_numeric_invoice_only_near_a_strong_label() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates([{"raw_text": "Invoice Number\n12345"}])

    assert any(item["value"] == "12345" and not item["candidate_only"] for item in candidates["document_number"])
    assert "document_number" not in service.collect_document_candidates([{"raw_text": "12345\nSupplier copy"}])


def test_harvests_invoice_and_balance_due_values_before_their_labels() -> None:
    candidates = FieldExtractionService().collect_document_candidates(
        [{"raw_text": "RI - 23014073\nInvoice Number\nUSD 1,240.50\nBalance Due"}]
    )

    invoice = next(
        item
        for item in candidates["document_number"]
        if item["value"] == "RI-23014073" and item["extraction_method"] == "context_label_value"
    )
    total = next(
        item
        for item in candidates["transaction_amount"]
        if item["value"] == 1240.5 and item["extraction_method"] == "context_label_value"
    )
    assert not invoice["candidate_only"] and invoice["label_relation"] == "before_label"
    assert not total["candidate_only"] and total["label_relation"] == "before_label"


def test_rejects_unlabelled_identifier_without_invoice_evidence() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates([{"raw_text": "RI - 23014073\nSupplier copy"}])
    fields = service.resolve_document_candidates(candidates)

    assert fields == {}
    assert "document_number" not in candidates


def test_collects_each_inline_core_value_once() -> None:
    candidates = FieldExtractionService().collect_document_candidates(
        [{"raw_text": "Invoice No: INV-77\nGrand Total: Rp 1.100.000"}]
    )

    assert [item["value"] for item in candidates["document_number"]] == ["INV-77"]
    assert [item["value"] for item in candidates["transaction_amount"]] == [1_100_000.0]


def test_resolves_value_before_a_strong_same_line_label() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "RI - 23014073 Invoice Number\nUSD 1,240.50 Balance Due"}
    )

    assert fields["document_number"]["value"] == "RI-23014073"
    assert fields["document_number"]["label_relation"] == "same_line"
    assert fields["transaction_amount"]["value"] == 1240.5
    assert fields["transaction_amount"]["label_relation"] == "same_line"


def test_generic_total_does_not_create_a_context_label_candidate() -> None:
    candidates = FieldExtractionService().collect_document_candidates([{"raw_text": "Total\nUSD 999.00"}])

    amounts = candidates.get("transaction_amount", [])
    assert not any(item["extraction_method"] == "context_label_value" for item in amounts)


def test_total_tax_is_not_misclassified_as_final_total() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "Total PPN: Rp 110.000\nGrand Total: Rp 1.110.000"}
    )

    assert fields["transaction_amount"]["value"] == 1_110_000.0
    assert fields["transaction_amount"]["amount_role"] == "final_total"


def test_total_price_can_be_a_final_total_candidate() -> None:
    service = FieldExtractionService()
    candidates = service.collect_document_candidates([{"raw_text": "Total Price: USD 500.00"}])
    fields = service.resolve_document_candidates(candidates)

    assert fields["transaction_amount"]["status"] == "NOT_FOUND"
    assert any(item["value"] == 500.0 and item["candidate_only"] for item in candidates["transaction_amount"])


def test_generic_total_nouns_require_reasoning() -> None:
    service = FieldExtractionService()
    for text in ("Total Qty: 20", "Total Items: 20", "Total Hours: 8"):
        candidates = service.collect_document_candidates([{"raw_text": text}])
        fields = service.resolve_document_candidates(candidates)

        assert fields["transaction_amount"]["status"] == "NOT_FOUND"
        assert all(item["candidate_only"] for item in candidates["transaction_amount"])


def test_total_amount_ignores_percent_after_currency_value() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "Total Amount Due: USD 1,240.50 including VAT 11%"}
    )

    assert fields["transaction_amount"]["value"] == 1240.5
    assert fields["transaction_amount"]["raw_value"] == "1,240.50"


def test_handles_common_ocr_typos_in_invoice_and_total_labels() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {"raw_text": "Invoice N0: RI - 23014073\nGRAND T0TAL: USD 1,240.50"}
    )

    assert fields["document_number"]["value"] == "RI-23014073"
    assert fields["transaction_amount"]["value"] == 1240.5


def test_accepts_expanded_total_label_without_a_separator() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Grand Amount USD 1,240.50"})

    assert fields["transaction_amount"]["value"] == 1240.5
    assert fields["transaction_amount"]["amount_role"] == "final_total"


def test_invoice_label_does_not_accept_a_date_as_identifier() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Invoice Number: 20/07/2026"})

    assert "document_number" not in fields


def test_rebuilds_native_pdf_words_into_invoice_rows() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {
            "tokens_json": [
                {"text": "Invoice", "bbox": [10, 10, 45, 20], "coordinate_space": "pdf_points"},
                {"text": "No.", "bbox": [48, 10, 63, 20], "coordinate_space": "pdf_points"},
                {"text": "INV-2026-77", "bbox": [66, 10, 120, 20], "coordinate_space": "pdf_points"},
                {"text": "Invoice", "bbox": [10, 30, 45, 40], "coordinate_space": "pdf_points"},
                {"text": "Date:", "bbox": [48, 30, 75, 40], "coordinate_space": "pdf_points"},
                {"text": "20/07/2026", "bbox": [78, 30, 130, 40], "coordinate_space": "pdf_points"},
                {"text": "Grand", "bbox": [10, 50, 40, 60], "coordinate_space": "pdf_points"},
                {"text": "Total:", "bbox": [43, 50, 72, 60], "coordinate_space": "pdf_points"},
                {"text": "Rp", "bbox": [75, 50, 85, 60], "coordinate_space": "pdf_points"},
                {"text": "1.110.000", "bbox": [88, 50, 135, 60], "coordinate_space": "pdf_points"},
            ]
        }
    )

    assert fields["document_number"]["value"] == "INV-2026-77"
    assert fields["transaction_date"]["value"] == "2026-07-20"
    assert fields["transaction_amount"]["value"] == 1_110_000.0
    assert fields["transaction_amount"]["source_block_id"] == "pdf-row-3"


def test_reconciles_discount_tax_and_service_charge() -> None:
    fields = FieldExtractionService().extract_from_ocr(
        {
            "raw_text": """Subtotal: Rp 1.000.000
Discount: Rp 100.000
PPN: Rp 99.000
Service Charge: Rp 1.000
Grand Total: Rp 1.000.000"""
        }
    )

    assert fields["transaction_amount"]["value"] == 1_000_000.0
    assert fields["transaction_amount"]["validation"] == "RECONCILED_NET_TOTAL"


def test_does_not_fill_issue_date_with_due_date() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Due Date: 20/08/2026"})

    assert fields["transaction_date"]["value"] is None
    assert fields["transaction_date"]["status"] == "NOT_FOUND"


def test_does_not_fill_issue_date_with_an_unlabelled_city_date() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Karawang, October 31, 2023"})

    assert fields["transaction_date"]["value"] is None
    assert fields["transaction_date"]["status"] == "NOT_FOUND"


def test_date_role_follows_split_due_and_print_labels() -> None:
    service = FieldExtractionService()
    for text, expected_role in (
        ("Due Date\n20/08/2026", "due_date"),
        ("Print Date\n20/08/2026", "print_date"),
    ):
        candidates = service.collect_document_candidates([{"raw_text": text}])
        fields = service.resolve_document_candidates(candidates)

        assert fields["transaction_date"]["status"] == "NOT_FOUND"
        assert candidates["transaction_date"][0]["date_role"] == expected_role


def test_does_not_fill_total_with_an_adjustment() -> None:
    fields = FieldExtractionService().extract_from_ocr({"raw_text": "Service Charge: Rp 10.000"})

    assert fields["transaction_amount"]["value"] is None
    assert fields["transaction_amount"]["status"] == "NOT_FOUND"


def test_requests_visual_ocr_only_when_native_labeled_field_is_unresolved() -> None:
    service = FieldExtractionService()

    assert not service.needs_visual_ocr(
        {"raw_text": "Invoice No: INV-7\nInvoice Date: 20/07/2026\nGrand Total: Rp 1.000.000"}
    )
    assert service.needs_visual_ocr({"raw_text": "Grand Total:"})
