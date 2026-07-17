import re
from typing import Any

from app.domain.value_objects.money_amount import MoneyAmount

_INVOICE_KEYWORDS = [
    r"(?i)(?:invoice\s*(?:no|number)?|no\.?\s*invoice|nomor\s*invoice|no\.?\s*faktur|faktur\s*pajak|inv\s*no\.?)\s*[:#\-]?\s*(?P<value>[A-Z0-9][A-Z0-9/\.\-]*)",
    r"(?i)(?:^|\s)(?P<value>(?:INV|FAK)[\s\-]?[0-9][A-Z0-9/\-]*)",
]

_BILLING_KEYWORDS = [
    r"(?i)(?:billing\s*(?:no|number|id)?|nomor\s*billing|no\.?\s*tagihan|kode\s*billing)\s*[:#\-]?\s*(?P<value>[A-Z0-9][A-Z0-9/\.\-]*)",
]

_AMOUNT_KEYWORDS = [
    r"(?i)(?:grand\s*total|total\s*bayar|total\s*amount|amount\s*due|jumlah\s*total|nilai\s*tagihan|sub\s*total|total|jumlah|dpp)\s*[:=\-]?\s*(?:Rp\.?\s*)?(?P<value>[0-9][0-9.,]*)",
    r"(?i)\bRp\.?\s*(?P<value>[0-9][0-9.,]*)",
]

_DATE_KEYWORDS = [
    r"(?i)(?:date|tanggal|tgl\.?)\s*[:\-]?\s*(?P<value>\d{2,4}[-/]\d{1,2}[-/]\d{2,4})",
    r"(?i)(?:date|tanggal|tgl\.?)\s*[:\-]?\s*(?P<value>\d{1,2}\s+[A-Za-z]+\s+\d{2,4})",
]

_VENDOR_KEYWORDS = [
    r"(?i)(?:vendor|supplier|pemasok|perusahaan|penjual)\s*[:\-]?\s*(?P<value>[^\n]+)",
    r"(?i)(?P<value>(?:pt|cv)\.?\s+[A-Za-z0-9 .,&()\-]+)",
]


class FieldExtractionService:
    def extract_from_ocr(self, ocr_result: dict[str, Any]) -> dict[str, Any]:
        tokens = ocr_result.get("tokens_json", [])
        text_lines = [t.get("text", "") for t in tokens if t.get("text")]
        raw_text = ocr_result.get("raw_text", "") or "\n".join(text_lines)

        fields: dict[str, Any] = {}

        inv = self._extract(raw_text, _INVOICE_KEYWORDS)
        if inv:
            fields["document_number"] = self._field(inv, 0.90, "regex")

        bill = self._extract(raw_text, _BILLING_KEYWORDS)
        if bill:
            fields["billing_number"] = self._field(bill, 0.85, "regex")

        amt_raw = self._extract(raw_text, _AMOUNT_KEYWORDS)
        if amt_raw:
            parsed = MoneyAmount.parse_rupiah(amt_raw)
            if parsed:
                fields["transaction_amount"] = self._field(parsed.value, 0.85, "regex", amt_raw, currency="IDR")

        if "transaction_amount" not in fields:
            candidates = self._find_amount_candidates(text_lines)
            if candidates:
                fields["transaction_amount"] = self._field(candidates[0], 0.60, "token", currency="IDR")

        d = self._extract(raw_text, _DATE_KEYWORDS)
        if d:
            fields["transaction_date"] = self._field(d, 0.80, "regex")

        v = self._extract(raw_text, _VENDOR_KEYWORDS)
        if v:
            fields["vendor_name"] = self._field(v, 0.70, "regex", source_text=v)

        if "document_number" not in fields:
            for line in text_lines:
                m = re.search(r"(?i)((?:INV|FAK|INVOICE)[\s\-/]?[0-9]{2,}[0-9/\-]*)", line)
                if m:
                    fields["document_number"] = self._field(m.group(1).strip(), 0.50, "token")
                    break

        return fields

    def extract_layout_aware(self, tokens: list[dict[str, Any]]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        label_value_pairs = self._find_label_value_pairs(tokens)

        for label, value in label_value_pairs:
            label_lower = label.lower()
            if any(k in label_lower for k in ["invoice", "faktur", "inv"]):
                fields["document_number"] = self._field(value, 0.90, "layout", source_text=f"{label}: {value}")
            elif any(k in label_lower for k in ["billing", "tagihan"]):
                fields["billing_number"] = self._field(value, 0.85, "layout", source_text=f"{label}: {value}")
            elif any(k in label_lower for k in ["total", "amount", "jumlah"]):
                parsed = MoneyAmount.parse_rupiah(value)
                if parsed:
                    fields["transaction_amount"] = self._field(parsed.value, 0.85, "layout", value, currency="IDR", source_text=f"{label}: {value}")
            elif any(k in label_lower for k in ["date", "tanggal", "tgl"]):
                fields["transaction_date"] = self._field(value, 0.80, "layout", source_text=f"{label}: {value}")
            elif any(k in label_lower for k in ["vendor", "supplier", "perusahaan"]):
                fields["vendor_name"] = self._field(value, 0.70, "layout", source_text=f"{label}: {value}")

        return fields

    def _extract(self, text: str, patterns: list[re.Pattern | str]) -> str | None:
        for pat in patterns:
            m = re.search(pat, text)
            if m and m.groupdict().get("value"):
                return m.group("value").strip()
        return None

    def _field(
        self, value: Any, confidence: float, method: str, raw_value: Any | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "value": value,
            "raw_value": str(raw_value if raw_value is not None else value),
            "confidence": confidence,
            "extraction_method": method,
            **extra,
        }

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
            if ":" in text:
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
