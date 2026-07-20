from __future__ import annotations

from typing import Any

from app.infrastructure.reasoning.qwen_reasoning_adapter import QwenReasoningAdapter
from app.shared.config.settings import settings

_FIELD_DEFINITIONS = {
    "document_number": (
        "commercial invoice or document number, not a tax invoice number unless the document is tax invoice"
    ),
    "billing_number": "billing or payment reference number",
    "transaction_amount": "final payable amount, not DPP, PPN, subtotal, or unit price",
    "transaction_date": "document issuance or invoice date",
    "vendor_name": "seller, supplier, or issuer; not buyer or recipient",
}

_REASON_CODES = {
    "document_number": {"COMMERCIAL_DOCUMENT_NUMBER"},
    "billing_number": {"BILLING_REFERENCE"},
    "transaction_amount": {"FINAL_PAYABLE_TOTAL"},
    "transaction_date": {"DOCUMENT_ISSUE_DATE"},
    "vendor_name": {"SELLER_OR_ISSUER"},
}
_CORE_SELECTION_FIELDS = {"document_number", "transaction_amount", "transaction_date"}
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
_MAX_REASONING_PAGES = 4
_MAX_REASONING_PAGE_CHARS = 12_000


class FieldReasoningService:
    """Resolve only conflicting OCR candidates and preserve their evidence."""

    def __init__(self, adapter: QwenReasoningAdapter | None = None) -> None:
        self._adapter = adapter or QwenReasoningAdapter()

    @property
    def is_available(self) -> bool:
        return self._adapter.is_available

    @property
    def load_error(self) -> str | None:
        return self._adapter.load_error

    async def warmup(self) -> None:
        await self._adapter.warmup()

    async def resolve(
        self,
        fields: dict[str, dict[str, Any]],
        candidates: dict[str, list[dict[str, Any]]],
        doc_type: str,
        pages: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        selected = {
            name: items
            for name, items in candidates.items()
            if items
            and (
                len({str(item.get("value")) for item in items}) > 1
                or (
                    name in _CORE_SELECTION_FIELDS
                    and (
                        fields.get(name, {}).get("status") != "FOUND"
                        or fields.get(name, {}).get("confidence", 0) < settings.REASONING_CONFIDENCE_THRESHOLD
                    )
                )
            )
        }
        if not settings.REASONING_ENABLED or not selected:
            return fields, {"enabled": settings.REASONING_ENABLED, "used": False, "engine": "deterministic"}
        if not self._adapter.is_available:
            return fields, {
                "enabled": True,
                "used": False,
                "engine": "deterministic",
                "error": self._adapter.load_error or "reasoning_not_ready",
            }

        candidate_index: dict[str, dict[str, dict[str, Any]]] = {}
        payload_fields: dict[str, list[dict[str, Any]]] = {}
        for name, items in selected.items():
            eligible_items = [
                item
                for item in items
                if not (
                    name == "transaction_amount" and item.get("amount_role") in _NON_PAYABLE_ROLES
                )
                and not (name == "transaction_date" and item.get("date_role") in _NON_ISSUE_DATE_ROLES)
            ]
            if not eligible_items or (
                len({str(item.get("value")) for item in eligible_items}) < 2
                and name not in _CORE_SELECTION_FIELDS
            ):
                continue
            # One value can be discovered by several OCR paths.  Give the model
            # distinct values, not twelve copies of the same noisy candidate.
            unique_items: dict[str, dict[str, Any]] = {}
            for item in eligible_items:
                key = str(item.get("value"))
                if key not in unique_items or float(item.get("score", item["confidence"])) > float(
                    unique_items[key].get("score", unique_items[key]["confidence"])
                ):
                    unique_items[key] = item
            indexed: dict[str, dict[str, Any]] = {}
            public_items: list[dict[str, Any]] = []
            for index, item in enumerate(
                sorted(unique_items.values(), key=lambda item: item.get("score", item["confidence"]), reverse=True)[:12]
            ):
                candidate_id = f"{name}-{index}"
                indexed[candidate_id] = item
                public_items.append(
                    {
                        "candidate_id": candidate_id,
                        "value": item["value"],
                        "label": item.get("source_label"),
                        "confidence": item.get("confidence"),
                        "currency": item.get("currency"),
                        "amount_role": item.get("amount_role"),
                        "source_text": str(item.get("source_text", ""))[:500],
                        "page": item.get("source_page_number"),
                        "block_id": item.get("source_block_id"),
                        "bbox": item.get("source_bbox"),
                        "document_position": item.get("source_position"),
                        "label_relation": item.get("label_relation"),
                        "label_distance": item.get("label_distance"),
                    }
                )
            candidate_index[name] = indexed
            payload_fields[name] = public_items

        if not payload_fields:
            return fields, {"enabled": True, "used": False, "engine": "deterministic"}

        document_context = self._document_context(pages or [], candidates)

        reply = await self._adapter.select(
            {
                "document_type": doc_type,
                "field_definitions": {name: _FIELD_DEFINITIONS.get(name, name) for name in payload_fields},
                "candidates": payload_fields,
                "document_context": document_context,
            }
        )
        resolved = dict(fields)
        applied: list[str] = []
        for decision in reply.get("decisions", []) if isinstance(reply.get("decisions"), list) else []:
            if not isinstance(decision, dict):
                continue
            name, candidate_id = decision.get("field_name"), decision.get("candidate_id")
            item = candidate_index.get(name, {}).get(candidate_id)
            if item is None:
                continue
            current = fields.get(name, {})
            if (
                name == "transaction_amount"
                and current.get("amount_role") == "final_total"
                and current.get("validation", "").startswith("RECONCILED")
                and item.get("value") != current.get("value")
            ):
                continue
            chosen = dict(item)
            reason_code = str(decision.get("reason_code", ""))
            if reason_code not in _REASON_CODES.get(name, set()):
                reason_code = "MODEL_SELECTED_CANDIDATE"
            chosen.update(
                {
                    "status": "FOUND",
                    # Model confidence is not calibrated. Preserve deterministic evidence score.
                    "reason_code": reason_code,
                    "reasoning_engine": "qwen3.5-9b",
                }
            )
            resolved[name] = chosen
            applied.append(name)
        return resolved, {
            "enabled": True,
            "used": bool(applied),
            "engine": "qwen3.5-9b",
            "resolved_fields": applied,
            "context_pages": [page["page_number"] for page in document_context],
            "error": reply.get("error"),
        }

    @staticmethod
    def _document_context(pages: list[dict[str, Any]], candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        if not pages:
            return []
        priority: dict[int, float] = {1: 1.0, len(pages): 0.9}
        for name in _CORE_SELECTION_FIELDS:
            for item in candidates.get(name, []):
                page_number = int(item.get("source_page_number") or 0)
                if 1 <= page_number <= len(pages):
                    priority[page_number] = max(priority.get(page_number, 0.0), float(item.get("score", 0.0)))

        # ponytail: context is capped to relevant pages; use token-aware packing only if real documents exceed it.
        selected_pages = sorted(priority, key=lambda page_number: (-priority[page_number], page_number))[
            :_MAX_REASONING_PAGES
        ]
        return [
            {
                "page_number": page_number,
                "raw_text": str(pages[page_number - 1].get("raw_text", ""))[:_MAX_REASONING_PAGE_CHARS],
            }
            for page_number in sorted(selected_pages)
            if str(pages[page_number - 1].get("raw_text", "")).strip()
        ]

    async def summarize(
        self, document_result: str, fields: dict[str, dict[str, Any]], failed_rules: list[dict[str, Any]]
    ) -> dict[str, Any]:
        failed_items = [str(rule.get("rule_name", "Validation failed")) for rule in failed_rules]
        fallback = {
            "result": document_result,
            "failed_items": failed_items,
            "reason": "Verification passed." if not failed_items else "; ".join(failed_items[:3]),
            "recommendations": [],
            "engine": "deterministic",
        }
        summarize = getattr(self._adapter, "summarize", None)
        if not settings.REASONING_ENABLED or not self._adapter.is_available or not callable(summarize):
            return fallback
        reply = await summarize(
            {
                "document_result": document_result,
                "verified_fields": {name: field.get("value") for name, field in fields.items()},
                "failed_rules": [
                    {"rule_id": rule.get("rule_id"), "rule_name": rule.get("rule_name")} for rule in failed_rules
                ],
            }
        )
        rule_ids = reply.get("rule_ids")
        summary = reply.get("summary")
        allowed = {str(rule.get("rule_id")) for rule in failed_rules}
        received = {str(item) for item in rule_ids} if isinstance(rule_ids, list) else set()
        if isinstance(summary, str) and 0 < len(summary) <= 500 and received == allowed:
            return {**fallback, "reason": summary, "engine": "qwen3.5-9b"}
        return fallback
