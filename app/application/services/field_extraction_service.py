from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.domain.value_objects.money_amount import MoneyAmount

_NUMBER_RE = re.compile(r"[A-Z0-9][A-Z0-9/.\-]{2,}", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?:Rp\.?\s*)?([0-9][0-9.,]*)", re.IGNORECASE)
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d", "%d %B %Y", "%d %b %Y")
_MONTHS = {
    "januari": "January", "februari": "February", "maret": "March", "mei": "May", "juni": "June",
    "juli": "July", "agustus": "August", "september": "September", "oktober": "October",
    "november": "November", "desember": "December",
}

# Order matters: the first matching amount label is the intended business role.
_LABELS: dict[str, tuple[tuple[str, float], ...]] = {
    "document_number": (("invoice number", 1.0), ("invoice no", 1.0), ("nomor invoice", 1.0), ("no invoice", 1.0), ("no faktur", 0.95), ("faktur penjualan", 0.9), ("invoice", 0.8)),
    "billing_number": (("billing number", 1.0), ("billing no", 1.0), ("nomor billing", 1.0), ("no tagihan", 0.95), ("kode billing", 0.9)),
    "transaction_amount": (("grand total", 1.0), ("total bayar", 0.98), ("amount due", 0.98), ("nilai tagihan", 0.96), ("total amount", 0.95), ("total", 0.75), ("subtotal", 0.35), ("sub total", 0.35), ("dpp", 0.2), ("ppn", 0.15)),
    "transaction_date": (("invoice date", 1.0), ("tanggal invoice", 1.0), ("tanggal faktur", 0.95), ("date", 0.75), ("tanggal", 0.75), ("tgl", 0.7)),
    "vendor_name": (("vendor", 1.0), ("supplier", 1.0), ("pemasok", 1.0), ("penjual", 0.95), ("seller", 0.95)),
}


class FieldExtractionService:
    """Extract a small, evidence-backed field set from Nemotron OCR blocks."""

    def extract_document_pages(self, pages: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        candidates: dict[str, list[dict[str, Any]]] = {}
        for page_number, page in enumerate(pages, start=1):
            for name, items in self._candidates(page, doc_type).items():
                for item in items:
                    item["source_page_number"] = page_number
                    item["source_page_index"] = page_number - 1
                    candidates.setdefault(name, []).append(item)
        return {name: self._resolve(name, items) for name, items in candidates.items()}

    def extract_from_ocr(self, ocr_result: dict[str, Any], doc_type: str | None = None) -> dict[str, Any]:
        return {name: self._resolve(name, items) for name, items in self._candidates(ocr_result, doc_type).items()}

    def extract_layout_aware(self, tokens: list[dict[str, Any]], doc_type: str | None = None) -> dict[str, Any]:
        return self.extract_from_ocr({"tokens_json": tokens}, doc_type)

    def _candidates(self, page: dict[str, Any], doc_type: str | None) -> dict[str, list[dict[str, Any]]]:
        candidates: dict[str, list[dict[str, Any]]] = {}
        tokens = page.get("tokens_json", []) or []
        lines: list[tuple[str, Any]] = []
        for token in tokens:
            lines.extend((line.strip(), token.get("bbox")) for line in str(token.get("text", "")).splitlines() if line.strip())
        if not lines:
            raw_text = page.get("raw_text", "") or ""
            lines = [(line.strip(), None) for line in raw_text.splitlines() if line.strip()]

        for line, bbox in lines:
            label, value = self._split_label_value(line)
            if label and value:
                self._add_labeled(candidates, label, value, bbox, "label_value", doc_type)

        # Nemotron may emit a label and its value in adjacent semantic blocks.
        for index, token in enumerate(tokens[:-1]):
            label = str(token.get("text", "")).strip()
            value = str(tokens[index + 1].get("text", "")).strip()
            if label and value and self._spatially_related(token.get("bbox"), tokens[index + 1].get("bbox")):
                self._add_labeled(candidates, label, value, tokens[index + 1].get("bbox"), "spatial_label_value", doc_type)

        # Conservative fallback: document numbers must keep an invoice/faktur prefix;
        # money must carry an Rp marker. Bare numbers are never guessed as totals.
        for line, bbox in lines:
            if "document_number" not in candidates:
                match = re.search(
                    r"(?i)\b(?:invoice|faktur(?:\s+penjualan)?)\s*(?:no\.?|number|nomor)?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/.\-]{2,})",
                    line,
                ) or re.search(r"(?i)\b((?:INV|FAK)[\s/\-]*[0-9][A-Z0-9/.\-]*)", line)
                if match:
                    self._add(candidates, "document_number", match.group(1), 0.45, bbox, "pattern", line)
            if "transaction_amount" not in candidates and re.search(r"(?i)\brp\.?\s*\d", line):
                value = self._money(line)
                if value is not None:
                    self._add(candidates, "transaction_amount", value, 0.4, bbox, "currency_pattern", line, currency="IDR")
        return candidates

    def _add_labeled(
        self, candidates: dict[str, list[dict[str, Any]]], label: str, value: str, bbox: Any, method: str, doc_type: str | None
    ) -> None:
        normalized = self._normal(label)
        for name, options in _LABELS.items():
            for alias, score in options:
                if alias in normalized:
                    parsed = self._parse(name, value)
                    if parsed is not None and self._allowed(name, normalized, doc_type):
                        self._add(candidates, name, parsed, score, bbox, method, f"{label}: {value}", label, value)
                    return

    @staticmethod
    def _allowed(name: str, label: str, doc_type: str | None) -> bool:
        # Tax invoice numbers are not the invoice number of an ordinary invoice.
        return not (name == "document_number" and "pajak" in label and (doc_type or "").upper() not in {"TAX_INVOICE", "FAKTUR_PAJAK"})

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
    def _split_label_value(line: str) -> tuple[str | None, str | None]:
        match = re.match(r"^\s*(.+?)\s*[:=]\s*(.+?)\s*$", line)
        return (match.group(1), match.group(2)) if match else (None, None)

    def _parse(self, name: str, value: str) -> Any | None:
        if name in {"document_number", "billing_number"}:
            match = _NUMBER_RE.search(value)
            return match.group(0) if match else None
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
            return True
        lx1, ly1, lx2, ly2 = label_bbox
        vx1, vy1, vx2, vy2 = value_bbox
        same_row = abs(((ly1 + ly2) - (vy1 + vy2)) / 2) <= max(20, (ly2 - ly1) * 1.5)
        below = vy1 >= ly2 and abs(((lx1 + lx2) - (vx1 + vx2)) / 2) <= max(80, (lx2 - lx1) * 1.5)
        return (same_row and vx1 >= lx1) or below
