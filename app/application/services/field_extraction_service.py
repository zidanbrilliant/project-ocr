import re
from typing import Any

from app.domain.value_objects.money_amount import MoneyAmount

_INVOICE_KEYWORDS = [
    r"(?i)(invoice\s*(no|number)?|no\.?\s*invoice|nomor\s*invoice|faktur)\s*[:\-]?\s*([A-Z0-9\/\.\-]+)",
    r"(?i)(inv\s*no\.?)\s*[:\-]?\s*([A-Z0-9\/\.\-]+)",
    r"(?i)(no\.?\s*faktur)\s*[:\-]?\s*([A-Z0-9\/\.\-\s]+)",
    r"(?i)(faktur\s*pajak)\s*[:\-]?\s*([0-9\.\-]+)",
    r"(?i)(^|\s)(INV[\s\-]?[0-9\/\-]+)",
    r"(?i)(^|\s)(FAK[\s\-]?[0-9\/\-]+)",
]

_BILLING_KEYWORDS = [
    r"(?i)(billing\s*(no|number|id)?|nomor\s*billing|no\.?\s*tagihan)\s*[:\-]?\s*([A-Z0-9\/\.\-]+)",
    r"(?i)(kode\s*billing)\s*[:\-]?\s*([A-Z0-9]+)",
]

_AMOUNT_KEYWORDS = [
    r"(?i)(grand\s*total|total\s*amount|amount\s*due|total|jumlah|nilai\s*tagihan|sub\s*total)\s*[:\-]?\s*(Rp\.?\s*)?([0-9\.\,]+)",
    r"(?i)(jumlah\s*(total)?)\s*[:\-]?\s*(Rp\.?\s*)?([0-9\.\,]+)",
    r"(?i)(dpp\s*)\s*[:\-]?\s*(Rp\.?\s*)?([0-9\.\,]+)",
    r"(?i)(total\s*(bayar)?)\s*[:\-]?\s*(Rp\.?\s*)?([0-9\.\,]+)",
    r"(?:^|\s)Rp\.?\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:\,[0-9]+)?)",
]

_DATE_KEYWORDS = [
    r"(?i)(date|tanggal|tgl)\s*[:\-]?\s*(\d{2,4}[-/]\d{1,2}[-/]\d{2,4})",
    r"(?i)(date|tanggal|tgl)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{2,4})",
    r"(?i)(tgl\.?\s*)\s*(\d{2}[-/]\d{2}[-/]\d{2,4})",
    r"(?i)(\d{2}[-/]\d{2}[-/]\d{4})",
]

_VENDOR_KEYWORDS = [
    r"(?i)(vendor|supplier|pemasok|perusahaan|penjual)\s*[:\-]?\s*(.+)",
    r"(?i)(pt\.?\s+[\w\s]+)",
    r"(?i)(cv\.?\s+[\w\s]+)",
]


class FieldExtractionService:
    def extract_from_ocr(self, ocr_result: dict[str, Any]) -> dict[str, Any]:
        tokens = ocr_result.get("tokens_json", [])
        text_lines = [t.get("text", "") for t in tokens if t.get("text")]
        raw_text = ocr_result.get("raw_text", "") or "\n".join(text_lines)

        fields: dict[str, Any] = {}

        inv = self._extract(raw_text, _INVOICE_KEYWORDS, 3)
        if inv:
            fields["document_number"] = {"value": inv, "confidence": 90.0}

        bill = self._extract(raw_text, _BILLING_KEYWORDS, 3)
        if bill:
            fields["billing_number"] = {"value": bill, "confidence": 85.0}

        amt_raw = self._extract(raw_text, _AMOUNT_KEYWORDS, 3)
        if amt_raw:
            parsed = MoneyAmount.parse_rupiah(amt_raw)
            if parsed:
                fields["transaction_amount"] = {"value": parsed.value, "confidence": 85.0, "currency": "IDR"}

        if "transaction_amount" not in fields:
            candidates = self._find_amount_candidates(text_lines)
            if candidates:
                fields["transaction_amount"] = {"value": candidates[0], "confidence": 60.0, "currency": "IDR"}

        d = self._extract(raw_text, _DATE_KEYWORDS, 2)
        if d:
            fields["transaction_date"] = {"value": d, "confidence": 80.0}

        v = self._extract(raw_text, _VENDOR_KEYWORDS, 2)
        if v:
            fields["vendor_name"] = {"value": v, "confidence": 70.0}

        if "document_number" not in fields:
            for line in text_lines:
                m = re.search(r"(?i)((?:INV|FAK|INVOICE)[\s\-/]?[0-9]{2,}[0-9/\-]*)", line)
                if m:
                    fields["document_number"] = {"value": m.group(1).strip(), "confidence": 50.0}
                    break

        return fields

    def extract_layout_aware(self, tokens: list[dict[str, Any]]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        label_value_pairs = self._find_label_value_pairs(tokens)

        for label, value in label_value_pairs:
            label_lower = label.lower()
            if any(k in label_lower for k in ["invoice", "faktur", "inv"]):
                fields["document_number"] = {"value": value, "confidence": 90.0, "method": "layout"}
            elif any(k in label_lower for k in ["billing", "tagihan"]):
                fields["billing_number"] = {"value": value, "confidence": 85.0, "method": "layout"}
            elif any(k in label_lower for k in ["total", "amount", "jumlah"]):
                parsed = MoneyAmount.parse_rupiah(value)
                if parsed:
                    fields["transaction_amount"] = {"value": parsed.value, "confidence": 85.0, "currency": "IDR", "method": "layout"}
            elif any(k in label_lower for k in ["date", "tanggal", "tgl"]):
                fields["transaction_date"] = {"value": value, "confidence": 80.0, "method": "layout"}
            elif any(k in label_lower for k in ["vendor", "supplier", "perusahaan"]):
                fields["vendor_name"] = {"value": value, "confidence": 70.0, "method": "layout"}

        return fields

    def _extract(self, text: str, patterns: list[re.Pattern | str], group: int) -> str | None:
        for pat in patterns:
            m = re.search(pat, text)
            if m and m.lastindex and m.lastindex >= group:
                val = m.group(group)
                if val:
                    return val.strip()
                val = m.group(1)
                if val:
                    return val.strip()
        return None

    def _find_amount_candidates(self, lines: list[str]) -> list[float]:
        candidates = []
        for line in lines:
            clean = re.sub(r"[Rp\s\.]", "", line)
            clean = re.sub(r",(\d{2})$", r".\1", clean)
            try:
                val = float(clean)
                if val > 0:
                    candidates.append(val)
            except (ValueError, TypeError):
                continue
        return sorted(candidates, reverse=True)

    def _find_label_value_pairs(self, tokens: list[dict[str, Any]]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []

        for i, token in enumerate(tokens):
            text = token.get("text", "")
            if ":" in text or ":" in text:
                parts = re.split(r"[:]\s*", text, maxsplit=1)
                if len(parts) == 2 and parts[1].strip():
                    pairs.append((parts[0].strip(), parts[1].strip()))
                continue

            if i + 1 < len(tokens):
                next_text = tokens[i + 1].get("text", "")
                if self._is_label(text) and not self._is_label(next_text):
                    pairs.append((text, next_text))

        return pairs

    def _is_label(self, text: str) -> bool:
        labels = {"invoice", "no", "number", "date", "total", "amount", "vendor", "billing", "faktur", "tanggal", "jumlah"}
        return any(lb in text.lower() for lb in labels)
