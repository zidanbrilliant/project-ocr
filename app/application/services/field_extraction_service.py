from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.domain.value_objects.money_amount import MoneyAmount

_NUMBER_RE = re.compile(r"(?<![A-Z0-9])(?=[A-Z0-9/.\-]*\d)[A-Z0-9][A-Z0-9/.\-]{2,}", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<![A-Z0-9])(?:Rp\.?\s*)?([0-9][0-9.,]*)", re.IGNORECASE)
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d", "%d %B %Y", "%d %b %Y")
_MONTHS = {
    "januari": "January", "februari": "February", "maret": "March", "mei": "May", "juni": "June",
    "juli": "July", "agustus": "August", "september": "September", "oktober": "October",
    "november": "November", "desember": "December",
}

# Order matters: the first matching amount label is the intended business role.
_LABELS: dict[str, tuple[tuple[str, float], ...]] = {
    "document_number": (("invoice number", 1.0), ("invoice no", 1.0), ("nomor invoice", 1.0), ("no invoice", 1.0), ("nomor faktur", 0.98), ("no faktur", 0.95), ("faktur penjualan", 0.9)),
    "billing_number": (("billing number", 1.0), ("billing no", 1.0), ("nomor billing", 1.0), ("no tagihan", 0.95), ("kode billing", 0.9), ("payment reference", 0.85)),
    "transaction_amount": (("grand total", 1.0), ("total bayar", 0.98), ("amount due", 0.98), ("nilai tagihan", 0.96), ("total amount", 0.95), ("total", 0.75)),
    "transaction_date": (("invoice date", 1.0), ("tanggal invoice", 1.0), ("tanggal faktur", 0.95), ("document date", 0.9), ("date", 0.75), ("tanggal", 0.75), ("tgl", 0.7)),
    "vendor_name": (("vendor", 1.0), ("supplier", 1.0), ("pemasok", 1.0), ("penjual", 0.95), ("seller", 0.95)),
}


class FieldExtractionService:
    """Extract a small, evidence-backed field set from Nemotron OCR blocks."""

    def extract_document_pages(self, pages: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        candidates = self.collect_document_candidates(pages, doc_type)
        return self.resolve_document_candidates(candidates)

    def collect_document_candidates(self, pages: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, list[dict[str, Any]]]:
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
        expected = None
        if tax_base and taxes:
            expected = float(tax_base["value"]) + sum(float(item["value"]) for item in taxes)
        reconciliation = "NOT_APPLICABLE"
        if final_total and expected is not None:
            reconciliation = "RECONCILED_DPP_PLUS_TAX" if abs(float(final_total["value"]) - expected) < 0.01 else "UNRECONCILED"
        return {
            "currency": "IDR",
            "final_total": final_total,
            "subtotal": subtotal,
            "discounts": discounts,
            "taxable_base": tax_base,
            "taxes": taxes,
            "reconciliation": reconciliation,
        }

    def extract_from_ocr(self, ocr_result: dict[str, Any], doc_type: str | None = None) -> dict[str, Any]:
        return {name: self._resolve(name, items) for name, items in self._candidates(ocr_result, doc_type).items()}

    def extract_layout_aware(self, tokens: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        return self.extract_from_ocr({"tokens_json": tokens}, doc_type)

    def _candidates(self, page: dict[str, Any], doc_type: str | None) -> dict[str, list[dict[str, Any]]]:
        candidates: dict[str, list[dict[str, Any]]] = {}
        tokens = page.get("tokens_json", []) or []
        lines: list[tuple[str, Any, str]] = []
        for token_index, token in enumerate(tokens):
            block_id = str(token.get("block_id") or f"b{token_index + 1}")
            lines.extend(
                (line.strip(), token.get("bbox"), block_id)
                for line in str(token.get("text", "")).splitlines()
                if line.strip()
            )
        if not lines:
            raw_text = page.get("raw_text", "") or ""
            lines = [(line.strip(), None, f"line-{index + 1}") for index, line in enumerate(raw_text.splitlines()) if line.strip()]

        for line, bbox, block_id in lines:
            label, value = self._split_label_value(line)
            if label and value:
                self._add_labeled(candidates, label, value, bbox, "label_value", doc_type, block_id)
            self._add_document_number(candidates, line, bbox, block_id)
            self._add_financial_row(candidates, line, bbox, block_id)

        # Nemotron may emit a label and its value in adjacent semantic blocks.
        for index, token in enumerate(tokens[:-1]):
            label = str(token.get("text", "")).strip()
            value = str(tokens[index + 1].get("text", "")).strip()
            if label and value and self._spatially_related(token.get("bbox"), tokens[index + 1].get("bbox")):
                self._add_labeled(
                    candidates, label, value, tokens[index + 1].get("bbox"), "spatial_label_value", doc_type,
                    str(tokens[index + 1].get("block_id") or f"b{index + 2}"),
                )

        # Conservative fallback: money must carry an Rp marker. Bare numbers are
        # never guessed as totals; _add_financial_row handles labelled totals.
        for line, bbox, block_id in lines:
            if "transaction_amount" not in candidates and re.search(r"(?i)\brp\.?\s*\d", line):
                value = self._money(line)
                if value is not None:
                    self._add(candidates, "transaction_amount", value, 0.4, bbox, "currency_pattern", line, source_block_id=block_id, currency="IDR")
        return candidates

    def _add_document_number(self, candidates: dict[str, list[dict[str, Any]]], line: str, bbox: Any, block_id: str) -> None:
        match = re.search(
            r"(?i)\b(?:invoice|faktur(?:\s+penjualan)?)\b(?:\s+(?:no\.?|number|nomor))?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/.\-]*\d[A-Z0-9/.\-]*)",
            line,
        ) or re.search(r"(?i)\b((?:INV|FAK)[\s/\-]*[0-9][A-Z0-9/.\-]*)", line)
        if match:
            self._add(
                candidates, "document_number", match.group(1), 0.99, bbox, "document_number_pattern", line,
                source_label="document_number", raw_value=match.group(1), source_block_id=block_id,
            )

    def _add_financial_row(self, candidates: dict[str, list[dict[str, Any]]], line: str, bbox: Any, block_id: str) -> None:
        normalized = self._normal(line)
        roles = (
            ("final_total", ("grand total", "total bayar", "amount due", "nilai tagihan", "total amount", "total"), 0.98),
            ("subtotal", ("jumlah harga jual", "subtotal", "sub total"), 0.45),
            ("discount", ("dikurangi potongan harga", "potongan harga", "discount"), 0.35),
            ("tax_base", ("dasar pengenaan pajak", "dpp"), 0.25),
            ("tax", ("ppn",), 0.2),
        )
        for role, labels, score in roles:
            label = next((item for item in labels if normalized == item or normalized.startswith(f"{item} ")), None)
            if label is None:
                continue
            value = self._rightmost_money(line)
            if value is not None:
                raw_value = list(_MONEY_RE.finditer(line))[-1].group(1)
                self._add(
                    candidates, "transaction_amount", value, score, bbox, "financial_row", line,
                    source_label=label, raw_value=raw_value, source_block_id=block_id, amount_role=role, currency="IDR",
                )
            return

    def _add_labeled(
        self, candidates: dict[str, list[dict[str, Any]]], label: str, value: str, bbox: Any, method: str,
        doc_type: str | None, block_id: str,
    ) -> None:
        normalized = self._normal(label)
        if len(normalized) > 80:
            return
        for name, options in _LABELS.items():
            for alias, score in options:
                if normalized == alias or normalized.startswith(f"{alias} "):
                    parsed = self._parse(name, value)
                    if parsed is not None and self._allowed(name, normalized, doc_type):
                        extra = {"amount_role": "final_total", "currency": "IDR"} if name == "transaction_amount" else {}
                        self._add(candidates, name, parsed, score, bbox, method, f"{label}: {value}", label, value, source_block_id=block_id, **extra)
                    return

    @staticmethod
    def _allowed(name: str, label: str, doc_type: str | None) -> bool:
        # Tax invoice numbers are not the invoice number of an ordinary invoice.
        if name == "document_number" and "pajak" in label and (doc_type or "").upper() not in {"TAX_INVOICE", "FAKTUR_PAJAK"}:
            return False
        return not (name == "transaction_amount" and any(word in label for word in ("subtotal", "sub total", "dpp", "ppn", "pajak")))

    def _add(
        self, candidates: dict[str, list[dict[str, Any]]], name: str, value: Any, score: float, bbox: Any,
        method: str, source_text: str, source_label: str | None = None, raw_value: str | None = None, **extra: Any,
    ) -> None:
        candidates.setdefault(name, []).append({
            "value": value, "raw_value": raw_value or str(value), "confidence": round(score, 4),
            "score": round(score, 4), "extraction_method": method, "source_text": source_text,
            "source_label": source_label, "source_bbox": bbox, **extra,
        })

    def _resolve(self, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if name == "transaction_amount":
            items = self._validate_amount_candidates(items)
        items = sorted(items, key=lambda item: float(item["score"]), reverse=True)
        winner = dict(items[0])
        runner_up = items[1] if len(items) > 1 else None
        ambiguous = bool(runner_up and winner["value"] != runner_up["value"] and winner["score"] - runner_up["score"] < 0.08)
        winner["status"] = "AMBIGUOUS" if ambiguous else "FOUND"
        winner["candidate_count"] = len(items)
        if ambiguous:
            winner["alternatives"] = [{"value": item["value"], "score": item["score"], "source_text": item["source_text"]} for item in items[:3]]
            winner["confidence"] = min(winner["confidence"], 0.5)
        return winner

    @staticmethod
    def _validate_amount_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checked = [dict(item) for item in items]
        final_totals = [item for item in checked if item.get("amount_role") == "final_total"]
        tax_bases = [item for item in checked if item.get("amount_role") == "tax_base"]
        taxes = [item for item in checked if item.get("amount_role") == "tax"]
        discounts = [item for item in checked if item.get("amount_role") == "discount"]
        for item in final_totals:
            item["score"] = max(float(item["score"]), 0.98)
            item["confidence"] = item["score"]
            item["validation"] = "LABELLED_FINAL_TOTAL"
            if tax_bases and taxes:
                expected = float(tax_bases[-1]["value"]) + float(taxes[-1]["value"])
                if abs(float(item["value"]) - expected) < 0.01:
                    item["score"] = item["confidence"] = 0.995
                    item["validation"] = "RECONCILED_DPP_PLUS_TAX"
        return checked

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
        cleaned = value.strip()
        for indonesia, english in _MONTHS.items():
            cleaned = re.sub(indonesia, english, cleaned, flags=re.IGNORECASE)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue
        return None

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
