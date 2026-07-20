from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.domain.value_objects.money_amount import MoneyAmount

_NUMBER_RE = re.compile(r"(?<![A-Z0-9])(?=[A-Z0-9/.\-]*\d)[A-Z0-9][A-Z0-9/.\-]{2,}", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<![A-Z0-9])(?:Rp\.?\s*)?([0-9][0-9.,]*)", re.IGNORECASE)
_CURRENCY_RE = re.compile(
    r"(?i)(?:(?P<prefix>Rp\.?|IDR|USD|US\$|SGD|S\$|AUD|A\$|EUR|€|GBP|£|JPY|¥|\$)\s*(?P<prefix_amount>[0-9][0-9.,]*)|(?P<suffix_amount>[0-9][0-9.,]*)\s*(?P<suffix>IDR|USD|SGD|AUD|EUR|GBP|JPY))"
)
_DATE_RE = re.compile(
    r"(?i)\b(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{2,4}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{2,4})\b"
)
_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d.%m.%y",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%d %B %Y",
    "%d %b %Y",
    "%d %B %y",
    "%d %b %y",
    "%B %d %Y",
    "%b %d %Y",
)
_MONTHS = {
    "januari": "January",
    "februari": "February",
    "maret": "March",
    "mei": "May",
    "juni": "June",
    "juli": "July",
    "agustus": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "desember": "December",
}

_AMOUNT_ROLES: tuple[tuple[str, tuple[str, ...], float], ...] = (
    (
        "final_total",
        (
            "grand total",
            "invoice total",
            "total bayar",
            "jumlah bayar",
            "amount due",
            "balance due",
            "net payable",
            "total due",
            "nilai tagihan",
            "jumlah tagihan",
            "total amount",
            "net amount",
            "total",
        ),
        0.98,
    ),
    ("subtotal", ("jumlah harga jual", "subtotal", "sub total", "amount before tax"), 0.45),
    ("discount", ("dikurangi potongan harga", "potongan harga", "discount"), 0.35),
    ("tax_base", ("dasar pengenaan pajak", "taxable amount", "tax base", "dpp"), 0.25),
    ("tax", ("ppn", "vat", "tax", "pajak"), 0.2),
    ("service_charge", ("service charge", "biaya layanan", "handling fee", "admin fee", "administration fee"), 0.3),
    ("shipping", ("shipping", "freight", "ongkir", "delivery fee"), 0.3),
    ("withholding_tax", ("withholding tax", "pph", "pajak penghasilan"), 0.25),
    ("rounding", ("rounding", "pembulatan"), 0.2),
    ("paid", ("amount paid", "paid amount", "jumlah dibayar", "tunai", "cash received", "change"), 0.1),
)

_NON_PAYABLE_ROLES = {
    "subtotal",
    "discount",
    "tax_base",
    "tax",
    "service_charge",
    "shipping",
    "withholding_tax",
    "rounding",
    "paid",
}
_NON_ISSUE_DATE_ROLES = {"due_date", "payment_date", "print_date", "tax_period"}


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    )


def _bbox_center(value: list[float] | tuple[float, ...]) -> tuple[float, float]:
    return ((float(value[0]) + float(value[2])) / 2, (float(value[1]) + float(value[3])) / 2)


def _union_bbox(boxes: list[Any]) -> list[float]:
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]

# Order matters: the first matching amount label is the intended business role.
_LABELS: dict[str, tuple[tuple[str, float], ...]] = {
    "document_number": (
        ("invoice number", 1.0),
        ("invoice no", 1.0),
        ("inv no", 1.0),
        ("nomor invoice", 1.0),
        ("no invoice", 1.0),
        ("nomor faktur", 0.98),
        ("no faktur", 0.95),
        ("nomor nota", 0.95),
        ("no nota", 0.95),
        ("receipt no", 0.92),
        ("receipt number", 0.92),
        ("bill no", 0.9),
        ("document no", 0.9),
        ("doc no", 0.88),
        ("faktur penjualan", 0.9),
        ("invoice", 0.85),
        ("receipt", 0.82),
    ),
    "billing_number": (
        ("billing number", 1.0),
        ("billing no", 1.0),
        ("nomor billing", 1.0),
        ("no tagihan", 0.95),
        ("kode billing", 0.9),
        ("payment reference", 0.85),
    ),
    "transaction_amount": (
        ("grand total", 1.0),
        ("invoice total", 0.99),
        ("total bayar", 0.98),
        ("jumlah bayar", 0.98),
        ("amount due", 0.98),
        ("balance due", 0.98),
        ("net payable", 0.98),
        ("total due", 0.97),
        ("nilai tagihan", 0.96),
        ("jumlah tagihan", 0.96),
        ("total amount", 0.95),
        ("net amount", 0.95),
        ("total", 0.75),
    ),
    "transaction_date": (
        ("invoice date", 1.0),
        ("tanggal invoice", 1.0),
        ("tanggal faktur", 0.95),
        ("tanggal nota", 0.95),
        ("transaction date", 0.92),
        ("tanggal transaksi", 0.92),
        ("receipt date", 0.9),
        ("issued date", 0.9),
        ("date issued", 0.9),
        ("document date", 0.9),
        ("date", 0.75),
        ("tanggal", 0.75),
        ("tgl", 0.7),
    ),
    "vendor_name": (("vendor", 1.0), ("supplier", 1.0), ("pemasok", 1.0), ("penjual", 0.95), ("seller", 0.95)),
}


class FieldExtractionService:
    """Extract a small, evidence-backed field set from Nemotron OCR blocks."""

    def extract_document_pages(self, pages: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        candidates = self.collect_document_candidates(pages, doc_type)
        return self.resolve_document_candidates(candidates)

    def collect_document_candidates(
        self, pages: list[dict[str, Any]], doc_type: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return every evidence-backed candidate before a winner is selected."""
        candidates: dict[str, list[dict[str, Any]]] = {}
        for page_number, page in enumerate(pages, start=1):
            for name, items in self._candidates(page, doc_type).items():
                for item in items:
                    item["source_page_number"] = page_number
                    item["source_page_index"] = page_number - 1
                    candidates.setdefault(name, []).append(item)
        return candidates

    def resolve_document_candidates(self, candidates: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return {name: self._resolve(name, items) for name, items in candidates.items()}

    def build_financials(
        self, candidates: dict[str, list[dict[str, Any]]], fields: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Keep the payable total separate from tax components and their evidence."""
        amounts = candidates.get("transaction_amount", [])

        def best(role: str) -> dict[str, Any] | None:
            matches = [item for item in amounts if item.get("amount_role") == role]
            return dict(max(matches, key=lambda item: float(item["score"]))) if matches else None

        final_total = fields.get("transaction_amount")
        if final_total and final_total.get("amount_role") != "final_total":
            final_total = best("final_total") or final_total
        tax_base = best("tax_base")
        taxes = [dict(item) for item in amounts if item.get("amount_role") == "tax"]
        discounts = [dict(item) for item in amounts if item.get("amount_role") == "discount"]
        subtotal = best("subtotal")
        charges = [
            dict(item)
            for item in amounts
            if item.get("amount_role") in {"service_charge", "shipping", "withholding_tax", "rounding"}
        ]
        reconciliation = "NOT_APPLICABLE"
        if final_total:
            expected, reconciled_as = self._expected_payable(amounts, final_total.get("currency", "IDR"))
            if expected is not None:
                reconciliation = (
                    reconciled_as
                    if abs(float(final_total["value"]) - expected)
                    <= self._money_tolerance(final_total.get("currency", "IDR"))
                    else "UNRECONCILED"
                )
        return {
            "currency": (final_total or tax_base or subtotal or {}).get("currency", "UNKNOWN"),
            "final_total": final_total,
            "subtotal": subtotal,
            "discounts": discounts,
            "taxable_base": tax_base,
            "taxes": taxes,
            "adjustments": charges,
            "reconciliation": reconciliation,
        }

    def extract_from_ocr(self, ocr_result: dict[str, Any], doc_type: str | None = None) -> dict[str, Any]:
        return {name: self._resolve(name, items) for name, items in self._candidates(ocr_result, doc_type).items()}

    def extract_layout_aware(self, tokens: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        return self.extract_from_ocr({"tokens_json": tokens}, doc_type)

    def needs_visual_ocr(self, page: dict[str, Any], doc_type: str | None = None) -> bool:
        """Use visual OCR only when native text contains an unresolved core-field label."""
        token_text = [str(token.get("text", "")) for token in page.get("tokens_json", []) or []]
        text = "\n".join([str(page.get("raw_text", "")), *token_text])
        normalized = self._normal(text)
        fields = self.extract_from_ocr(page, doc_type)

        def unresolved(name: str) -> bool:
            return fields.get(name, {}).get("status") != "FOUND"

        has_document_label = any(label in normalized for label, score in _LABELS["document_number"] if score >= 0.9)
        has_total_label = any(label in normalized for label, _ in _LABELS["transaction_amount"])
        has_date_label = any(label in normalized for label, _ in _LABELS["transaction_date"])
        return (
            (has_document_label and unresolved("document_number"))
            or (has_total_label and unresolved("transaction_amount"))
            or (has_date_label and unresolved("transaction_date"))
        )

    def _candidates(self, page: dict[str, Any], doc_type: str | None) -> dict[str, list[dict[str, Any]]]:
        candidates: dict[str, list[dict[str, Any]]] = {}
        tokens = page.get("tokens_json", []) or []
        lines = self._lines_from_tokens(tokens)
        if not lines:
            raw_text = page.get("raw_text", "") or ""
            lines = [
                (line.strip(), None, f"line-{index + 1}")
                for index, line in enumerate(raw_text.splitlines())
                if line.strip()
            ]

        for line_index, (line, bbox, block_id) in enumerate(lines):
            label, value = self._split_label_value(line)
            if label and value:
                self._add_labeled(candidates, label, value, bbox, "label_value", doc_type, block_id)
            self._add_document_number(candidates, line, bbox, block_id, doc_type)
            self._add_financial_row(candidates, line, bbox, block_id)
            self._add_date_candidate(candidates, line, bbox, block_id, line_index, len(lines))

        # Nemotron may emit a label and its value in adjacent semantic blocks.
        for index, token in enumerate(tokens[:-1]):
            label = str(token.get("text", "")).strip()
            value = str(tokens[index + 1].get("text", "")).strip()
            if label and value and self._spatially_related(token.get("bbox"), tokens[index + 1].get("bbox")):
                self._add_labeled(
                    candidates,
                    label,
                    value,
                    tokens[index + 1].get("bbox"),
                    "spatial_label_value",
                    doc_type,
                    str(tokens[index + 1].get("block_id") or f"b{index + 2}"),
                )

        # When no explicit final-total label exists, currency-marked amounts are
        # safe candidates. The largest is the deterministic fallback; Qwen still
        # sees every candidate and may reject tax, subtotal, or unit-price rows.
        amounts = candidates.get("transaction_amount", [])
        if not any(item.get("amount_role") == "final_total" for item in amounts):
            currency_candidates = [
                (value, raw_value, currency, line, bbox, block_id, line_index)
                for line_index, (line, bbox, block_id) in enumerate(lines)
                if self._financial_role(line) is None
                for value, raw_value, currency in self._currency_amounts(line)
            ]
            currencies = {item[2] for item in currency_candidates}
            largest = max((item[0] for item in currency_candidates), default=None) if len(currencies) == 1 else None
            for value, raw_value, currency, line, bbox, block_id, line_index in currency_candidates:
                self._add(
                    candidates,
                    "transaction_amount",
                    value,
                    0.58 if value == largest else 0.4,
                    bbox,
                    "currency_largest_fallback" if value == largest else "currency_pattern",
                    line,
                    raw_value=raw_value,
                    source_block_id=block_id,
                    currency=currency,
                    amount_role="unlabelled_currency",
                    source_position=round((line_index + 1) / max(len(lines), 1), 4),
                )
        return candidates

    @staticmethod
    def _lines_from_tokens(tokens: list[dict[str, Any]]) -> list[tuple[str, Any, str]]:
        """Rebuild native PDF words into rows; Nemotron blocks are already semantic rows."""
        if not tokens:
            return []
        native = all(
            token.get("coordinate_space") == "pdf_points" and _valid_bbox(token.get("bbox")) for token in tokens
        )
        if not native:
            lines: list[tuple[str, Any, str]] = []
            for token_index, token in enumerate(tokens):
                block_id = str(token.get("block_id") or f"b{token_index + 1}")
                lines.extend(
                    (line.strip(), token.get("bbox"), block_id)
                    for line in str(token.get("text", "")).splitlines()
                    if line.strip()
                )
            return lines

        rows: list[list[dict[str, Any]]] = []
        for token in sorted(tokens, key=lambda item: ((_bbox_center(item["bbox"])[1]), float(item["bbox"][0]))):
            center_y = _bbox_center(token["bbox"])[1]
            height = float(token["bbox"][3]) - float(token["bbox"][1])
            for row in rows:
                row_box = _union_bbox([item["bbox"] for item in row])
                row_center_y = _bbox_center(row_box)[1]
                row_height = float(row_box[3]) - float(row_box[1])
                if abs(center_y - row_center_y) <= max(2.0, max(height, row_height) * 0.6):
                    row.append(token)
                    break
            else:
                rows.append([token])

        lines = []
        for row_index, row in enumerate(rows, start=1):
            ordered = sorted(row, key=lambda item: float(item["bbox"][0]))
            text = " ".join(str(item.get("text", "")).strip() for item in ordered).strip()
            lines.append((text, _union_bbox([item["bbox"] for item in ordered]), f"pdf-row-{row_index}"))
        return [line for line in lines if line[0]]

    def _add_document_number(
        self, candidates: dict[str, list[dict[str, Any]]], line: str, bbox: Any, block_id: str, doc_type: str | None
    ) -> None:
        normalized = self._normal(line)
        if ("tax invoice" in normalized or "faktur pajak" in normalized) and (doc_type or "").upper() not in {
            "TAX_INVOICE",
            "FAKTUR_PAJAK",
        }:
            return
        match = (
            re.search(
                r"(?i)\b(?:invoice|inv|faktur(?:\s+penjualan)?|nota|receipt|bill|document|doc)\b\s*[:#\-]?\s*(?:no\.?|number|nomor|#)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/.\-]*\d[A-Z0-9/.\-]*)",
                line,
            )
            or re.search(
                r"(?i)\b(?:invoice|inv|faktur(?:\s+penjualan)?|nota|receipt|bill|document|doc)\s*[:#\-]\s*([A-Z0-9][A-Z0-9/.\-]*\d[A-Z0-9/.\-]*)",
                line,
            )
            or re.search(
                r"(?i)\b(?:no\.?|number|nomor)\s*(?:invoice|inv|faktur|nota|receipt|bill)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/.\-]*\d[A-Z0-9/.\-]*)",
                line,
            )
            or re.search(r"(?i)\b((?:INV|FAK)[\s/\-]*[0-9][A-Z0-9/.\-]*)", line)
        )
        if match:
            self._add(
                candidates,
                "document_number",
                match.group(1),
                0.99,
                bbox,
                "document_number_pattern",
                line,
                source_label="document_number",
                raw_value=match.group(1),
                source_block_id=block_id,
            )

    def _add_financial_row(
        self, candidates: dict[str, list[dict[str, Any]]], line: str, bbox: Any, block_id: str
    ) -> None:
        role_data = self._financial_role(line)
        if role_data is None:
            return
        role, label, score = role_data
        value = self._rightmost_money(line)
        if value is None:
            return
        raw_value = list(_MONEY_RE.finditer(line))[-1].group(1)
        currency = self._currency(line) or "IDR"
        self._add(
            candidates,
            "transaction_amount",
            value,
            score,
            bbox,
            "financial_row",
            line,
            source_label=label,
            raw_value=raw_value,
            source_block_id=block_id,
            amount_role=role,
            currency=currency,
        )

    def _financial_role(self, line: str) -> tuple[str, str, float] | None:
        normalized = self._normal(line)
        for role, labels, score in _AMOUNT_ROLES:
            label = next((item for item in labels if normalized == item or normalized.startswith(f"{item} ")), None)
            if label is not None:
                return role, label, score
        return None

    def _add_date_candidate(
        self,
        candidates: dict[str, list[dict[str, Any]]],
        line: str,
        bbox: Any,
        block_id: str,
        line_index: int,
        line_count: int,
    ) -> None:
        value = self._date(line)
        if value is None:
            return
        normalized = self._normal(line)
        if any(label in normalized for label in ("due date", "jatuh tempo", "payment date", "tanggal bayar")):
            score, role = 0.25, "due_date"
        elif any(label in normalized for label in ("print date", "printed", "tanggal cetak")):
            score, role = 0.2, "print_date"
        elif any(label in normalized for label in ("tax period", "masa pajak", "periode pajak")):
            score, role = 0.2, "tax_period"
        elif any(
            label in normalized
            for label in (
                "invoice date",
                "tanggal invoice",
                "tanggal faktur",
                "tanggal nota",
                "transaction date",
                "tanggal transaksi",
                "issued date",
            )
        ):
            score, role = 0.9, "issue_date"
        else:
            score, role = 0.45, "unlabelled"
        self._add(
            candidates,
            "transaction_date",
            value,
            score,
            bbox,
            "date_pattern",
            line,
            source_block_id=block_id,
            source_position=round((line_index + 1) / max(line_count, 1), 4),
            date_role=role,
        )

    def _add_labeled(
        self,
        candidates: dict[str, list[dict[str, Any]]],
        label: str,
        value: str,
        bbox: Any,
        method: str,
        doc_type: str | None,
        block_id: str,
    ) -> None:
        normalized = self._normal(label)
        if len(normalized) > 80:
            return
        for name, options in _LABELS.items():
            for alias, score in options:
                if normalized == alias or normalized.startswith(f"{alias} "):
                    parsed = self._parse(name, value)
                    if parsed is not None and self._allowed(name, normalized, doc_type):
                        extra = (
                            {"amount_role": "final_total", "currency": self._currency(value) or "IDR"}
                            if name == "transaction_amount"
                            else {}
                        )
                        self._add(
                            candidates,
                            name,
                            parsed,
                            score,
                            bbox,
                            method,
                            f"{label}: {value}",
                            label,
                            value,
                            source_block_id=block_id,
                            **extra,
                        )
                    return

    @staticmethod
    def _allowed(name: str, label: str, doc_type: str | None) -> bool:
        # Tax invoice numbers are not the invoice number of an ordinary invoice.
        if (
            name == "document_number"
            and "pajak" in label
            and (doc_type or "").upper() not in {"TAX_INVOICE", "FAKTUR_PAJAK"}
        ):
            return False
        if name == "document_number" and any(word in label for word in ("date", "tanggal", "tempo", "tax")):
            return False
        return not (
            name == "transaction_amount"
            and any(word in label for word in ("subtotal", "sub total", "dpp", "ppn", "pajak"))
        )

    def _add(
        self,
        candidates: dict[str, list[dict[str, Any]]],
        name: str,
        value: Any,
        score: float,
        bbox: Any,
        method: str,
        source_text: str,
        source_label: str | None = None,
        raw_value: str | None = None,
        **extra: Any,
    ) -> None:
        candidates.setdefault(name, []).append(
            {
                "value": value,
                "raw_value": raw_value or str(value),
                "confidence": round(score, 4),
                "score": round(score, 4),
                "extraction_method": method,
                "source_text": source_text,
                "source_label": source_label,
                "source_bbox": bbox,
                **extra,
            }
        )

    def _resolve(self, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if name == "transaction_amount":
            items = self._validate_amount_candidates(items)
            eligible = [item for item in items if item.get("amount_role") not in _NON_PAYABLE_ROLES]
            if not eligible:
                return self._not_found(items)
            items = eligible
        elif name == "transaction_date":
            eligible = [item for item in items if item.get("date_role") not in _NON_ISSUE_DATE_ROLES]
            if not eligible:
                return self._not_found(items)
            items = eligible
        items = sorted(items, key=lambda item: float(item["score"]), reverse=True)
        winner = dict(items[0])
        runner_up = items[1] if len(items) > 1 else None
        ambiguous = bool(
            runner_up and winner["value"] != runner_up["value"] and winner["score"] - runner_up["score"] < 0.08
        )
        winner["status"] = "AMBIGUOUS" if ambiguous else "FOUND"
        winner["candidate_count"] = len(items)
        if ambiguous:
            winner["alternatives"] = [
                {"value": item["value"], "score": item["score"], "source_text": item["source_text"]}
                for item in items[:3]
            ]
            winner["confidence"] = min(winner["confidence"], 0.5)
        return winner

    @staticmethod
    def _not_found(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "value": None,
            "raw_value": None,
            "confidence": 0.0,
            "score": 0.0,
            "status": "NOT_FOUND",
            "candidate_count": len(items),
            "alternatives": [
                {"value": item.get("value"), "score": item.get("score"), "source_text": item.get("source_text")}
                for item in items[:3]
            ],
        }

    @staticmethod
    def _validate_amount_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checked = [dict(item) for item in items]
        final_totals = [item for item in checked if item.get("amount_role") == "final_total"]
        for item in final_totals:
            item["score"] = max(float(item["score"]), 0.98)
            item["confidence"] = item["score"]
            item["validation"] = "LABELLED_FINAL_TOTAL"
            expected, validation = FieldExtractionService._expected_payable(checked, item.get("currency", "IDR"))
            if expected is not None and abs(float(item["value"]) - expected) <= FieldExtractionService._money_tolerance(
                item.get("currency", "IDR")
            ):
                item["score"] = item["confidence"] = 0.995
                item["validation"] = validation
        return checked

    @staticmethod
    def _expected_payable(items: list[dict[str, Any]], currency: str) -> tuple[float | None, str]:
        def values(role: str) -> list[float]:
            seen: set[tuple[float, str]] = set()
            result: list[float] = []
            for item in items:
                if item.get("amount_role") != role or item.get("currency", "IDR") != currency:
                    continue
                key = (float(item["value"]), str(item.get("source_text", "")))
                if key not in seen:
                    seen.add(key)
                    result.append(key[0])
            return result

        taxes = values("tax")
        tax_bases = values("tax_base")
        if tax_bases and taxes:
            return tax_bases[-1] + sum(taxes), "RECONCILED_DPP_PLUS_TAX"
        subtotals = values("subtotal")
        if not subtotals:
            return None, "NOT_APPLICABLE"
        return (
            subtotals[-1]
            - sum(values("discount"))
            + sum(taxes)
            + sum(values("service_charge"))
            + sum(values("shipping"))
            - sum(values("withholding_tax"))
            + sum(values("rounding")),
            "RECONCILED_NET_TOTAL",
        )

    @staticmethod
    def _money_tolerance(currency: str) -> float:
        return 1.0 if currency in {"IDR", "JPY"} else 0.01

    @staticmethod
    def _split_label_value(line: str) -> tuple[str | None, str | None]:
        match = re.match(r"^\s*(.+?)\s*[:=]\s*(.+?)\s*$", line)
        return (match.group(1), match.group(2)) if match else (None, None)

    def _parse(self, name: str, value: str) -> Any | None:
        if name in {"document_number", "billing_number"}:
            matches = _NUMBER_RE.findall(value)
            return max(matches, key=len) if matches else None
        if name == "transaction_amount":
            return self._money(value)
        if name == "transaction_date":
            return self._date(value)
        if name == "vendor_name":
            return value.strip() if len(value.strip()) >= 3 else None
        return None

    @staticmethod
    def _money(value: str) -> float | None:
        match = _MONEY_RE.search(value)
        amount = MoneyAmount.parse_rupiah(match.group(1)) if match else None
        return amount.value if amount else None

    @staticmethod
    def _rightmost_money(value: str) -> float | None:
        matches = list(_MONEY_RE.finditer(value))
        amount = MoneyAmount.parse_rupiah(matches[-1].group(1)) if matches else None
        return amount.value if amount else None

    @staticmethod
    def _date(value: str) -> str | None:
        match = _DATE_RE.search(value)
        if match is None:
            return None
        cleaned = match.group(0).replace(",", "").strip()
        for indonesia, english in _MONTHS.items():
            cleaned = re.sub(indonesia, english, cleaned, flags=re.IGNORECASE)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _currency_amounts(value: str) -> list[tuple[float, str, str]]:
        amounts: list[tuple[float, str, str]] = []
        for match in _CURRENCY_RE.finditer(value):
            raw_amount = match.group("prefix_amount") or match.group("suffix_amount")
            raw_currency = match.group("prefix") or match.group("suffix")
            parsed = MoneyAmount.parse_rupiah(raw_amount)
            if parsed:
                amounts.append((parsed.value, raw_amount, FieldExtractionService._normalize_currency(raw_currency)))
        return amounts

    @staticmethod
    def _currency(value: str) -> str | None:
        match = _CURRENCY_RE.search(value)
        raw = (match.group("prefix") or match.group("suffix")) if match else None
        return FieldExtractionService._normalize_currency(raw) if raw else None

    @staticmethod
    def _normalize_currency(value: str) -> str:
        normalized = value.upper().replace(".", "")
        return {
            "RP": "IDR",
            "US$": "USD",
            "$": "USD",
            "S$": "SGD",
            "A$": "AUD",
            "€": "EUR",
            "£": "GBP",
            "¥": "JPY",
        }.get(normalized, normalized)

    @staticmethod
    def _normal(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()

    @staticmethod
    def _spatially_related(label_bbox: Any, value_bbox: Any) -> bool:
        if not label_bbox or not value_bbox or len(label_bbox) != 4 or len(value_bbox) != 4:
            return False
        lx1, ly1, lx2, ly2 = label_bbox
        vx1, vy1, vx2, vy2 = value_bbox
        same_row = abs(((ly1 + ly2) - (vy1 + vy2)) / 2) <= max(20, (ly2 - ly1) * 1.5)
        below = vy1 >= ly2 and abs(((lx1 + lx2) - (vx1 + vx2)) / 2) <= max(80, (lx2 - lx1) * 1.5)
        return (same_row and vx1 >= lx1) or below
