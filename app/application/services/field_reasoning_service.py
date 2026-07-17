from __future__ import annotations

from typing import Any

from app.infrastructure.reasoning.qwen_reasoning_adapter import QwenReasoningAdapter
from app.shared.config.settings import settings

_FIELD_DEFINITIONS = {
    "document_number": "commercial invoice or document number, not a tax invoice number unless the document is tax invoice",
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
        self, fields: dict[str, dict[str, Any]], candidates: dict[str, list[dict[str, Any]]], doc_type: str
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        selected = {
            name: items
            for name, items in candidates.items()
            if len(items) > 1 and (fields.get(name, {}).get("status") == "AMBIGUOUS" or fields[name].get("confidence", 0) < settings.REASONING_CONFIDENCE_THRESHOLD)
        }
        if not settings.REASONING_ENABLED or not selected:
            return fields, {"enabled": settings.REASONING_ENABLED, "used": False, "engine": "deterministic"}

        candidate_index: dict[str, dict[str, dict[str, Any]]] = {}
        payload_fields: dict[str, list[dict[str, Any]]] = {}
        for name, items in selected.items():
            indexed: dict[str, dict[str, Any]] = {}
            public_items: list[dict[str, Any]] = []
            for index, item in enumerate(sorted(items, key=lambda item: item.get("score", item["confidence"]), reverse=True)[:8]):
                candidate_id = f"{name}-{index}"
                indexed[candidate_id] = item
                public_items.append({
                    "candidate_id": candidate_id,
                    "value": item["value"],
                    "label": item.get("source_label"),
                    "source_text": str(item.get("source_text", ""))[:500],
                    "page": item.get("source_page_number"),
                    "block_id": item.get("source_block_id"),
                })
            candidate_index[name] = indexed
            payload_fields[name] = public_items

        reply = await self._adapter.select(
            {
                "document_type": doc_type,
                "field_definitions": {name: _FIELD_DEFINITIONS.get(name, name) for name in payload_fields},
                "candidates": payload_fields,
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
            chosen = dict(item)
            reason_code = str(decision.get("reason_code", ""))
            if reason_code not in _REASON_CODES.get(name, set()):
                reason_code = "MODEL_SELECTED_CANDIDATE"
            chosen.update({
                "status": "FOUND",
                # Model confidence is not calibrated. Preserve deterministic evidence score.
                "reason_code": reason_code,
                "reasoning_engine": "qwen3.5-9b",
            })
            resolved[name] = chosen
            applied.append(name)
        return resolved, {
            "enabled": True,
            "used": bool(applied),
            "engine": "qwen3.5-9b",
            "resolved_fields": applied,
            "error": reply.get("error"),
        }

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
        reply = await summarize({
            "document_result": document_result,
            "verified_fields": {name: field.get("value") for name, field in fields.items()},
            "failed_rules": [{"rule_id": rule.get("rule_id"), "rule_name": rule.get("rule_name")} for rule in failed_rules],
        })
        rule_ids = reply.get("rule_ids")
        summary = reply.get("summary")
        allowed = {str(rule.get("rule_id")) for rule in failed_rules}
        received = {str(item) for item in rule_ids} if isinstance(rule_ids, list) else set()
        if isinstance(summary, str) and 0 < len(summary) <= 500 and received == allowed:
            return {**fallback, "reason": summary, "engine": "qwen3.5-9b"}
        return fallback
