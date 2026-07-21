from __future__ import annotations

from typing import Any

from app.application.services.field_extraction_service import FieldExtractionService
from app.infrastructure.reasoning.qwen_reasoning_adapter import QwenReasoningAdapter
from app.shared.config.settings import settings

_FIELD_DEFINITIONS = {
    "document_number": (
        "commercial invoice or document number, not a tax invoice number unless the document is tax invoice"
    ),
    "transaction_date": "document issuance or invoice date",
}

_REASON_CODES = {
    "document_number": {"COMMERCIAL_DOCUMENT_NUMBER"},
    "transaction_date": {"DOCUMENT_ISSUE_DATE"},
}
_CORE_SELECTION_FIELDS = {"document_number", "transaction_amount", "transaction_date"}
_TEXT_FIELDS = ("document_number", "transaction_date")
_MAX_TEXT_CONTEXT_CHARS = 12_000


class FieldReasoningService:
    """Extract invoice/date from OCR, with a deterministic fallback when Qwen is unavailable."""

    def __init__(
        self,
        adapter: QwenReasoningAdapter | None = None,
        field_extractor: FieldExtractionService | None = None,
    ) -> None:
        self._adapter = adapter or QwenReasoningAdapter()
        self._field_extractor = field_extractor or FieldExtractionService()

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
        candidates: dict[str, list[dict[str, Any]]],
        doc_type: str,
        pages: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        fields = self._field_extractor.resolve_document_candidates(candidates)
        resolved = self._strict_core_fallback(fields, candidates)
        text_fields = list(_TEXT_FIELDS)
        if not settings.REASONING_ENABLED:
            return resolved, {"enabled": settings.REASONING_ENABLED, "used": False, "engine": "deterministic"}
        if not self._adapter.is_available:
            return resolved, {
                "enabled": True,
                "used": False,
                "engine": "deterministic",
                "error": self._adapter.load_error or "reasoning_not_ready",
            }

        document_context = self._document_context(pages or [], candidates, text_fields)
        if not document_context:
            return resolved, {"enabled": True, "used": False, "engine": "deterministic"}

        reply = await self._adapter.select(
            {
                "document_type": doc_type,
                "requested_fields": text_fields,
                "field_definitions": _FIELD_DEFINITIONS,
                "page_ocr": document_context,
            }
        )
        applied: list[str] = []
        overrides: list[str] = []
        for decision in reply.get("decisions", []) if isinstance(reply.get("decisions"), list) else []:
            if not isinstance(decision, dict):
                continue
            name = decision.get("field_name")
            item = self._grounded_candidate(decision, pages or [], doc_type)
            if item is None:
                continue
            current = resolved.get(name, {})
            if current.get("value") is not None and current.get("value") != item.get("value"):
                overrides.append(str(name))
            chosen = dict(item)
            reason_code = str(decision.get("reason_code", ""))
            if reason_code not in _REASON_CODES.get(name, set()):
                reason_code = "MODEL_EXTRACTED_GROUNDED_VALUE"
            chosen.update(
                {
                    "status": "FOUND",
                    # The model confidence is ignored; acceptance requires exact OCR grounding.
                    "reason_code": reason_code,
                    "reasoning_engine": "qwen3.5-9b",
                    "verification_status": "VERIFIED",
                    "independent_evidence_count": 2,
                    "confidence": max(float(chosen.get("confidence", 0.0)), 0.9),
                    "score": max(float(chosen.get("score", 0.0)), 0.9),
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
            "visual_pages": [],
            "overrides": overrides,
            "conflicts": [],
            "error": reply.get("error"),
        }

    @staticmethod
    def _strict_core_fallback(
        fields: dict[str, dict[str, Any]], candidates: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """Keep only unambiguous, strongly labelled fields when Qwen fails."""
        resolved = dict(fields)
        for name in _CORE_SELECTION_FIELDS:
            field = fields.get(name, {})
            confidence = float(field.get("confidence", 0.0))
            keep = field.get("status") == "FOUND" and not field.get("candidate_only") and (
                (name == "document_number" and confidence >= 0.9)
                or (
                    name == "transaction_amount"
                    and field.get("amount_role") == "final_total"
                    and confidence >= 0.95
                )
                or (name == "transaction_date" and field.get("date_role") == "issue_date" and confidence >= 0.9)
            )
            if keep:
                single_source = name in _TEXT_FIELDS
                resolved[name] = {
                    **field,
                    "confidence": min(confidence, 0.84) if single_source else confidence,
                    "score": min(confidence, 0.84) if single_source else confidence,
                    "verification_status": "SINGLE_SOURCE",
                    "independent_evidence_count": 1,
                }
                continue
            resolved[name] = {
                "value": None,
                "raw_value": None,
                "confidence": 0.0,
                "score": 0.0,
                "status": "NOT_FOUND",
                "reason_code": "REASONING_REQUIRED",
                "candidate_count": len(candidates.get(name, [])),
                "alternatives": [
                    {
                        "value": item.get("value"),
                        "score": item.get("score"),
                        "source_text": item.get("source_text"),
                    }
                    for item in candidates.get(name, [])[:3]
                ],
            }
        return resolved

    def _grounded_candidate(
        self, decision: dict[str, Any], pages: list[dict[str, Any]], doc_type: str
    ) -> dict[str, Any] | None:
        name = decision.get("field_name")
        raw_value = decision.get("raw_value")
        evidence_quote = decision.get("evidence_quote")
        page_number = decision.get("page_number")
        if (
            name not in _TEXT_FIELDS
            or not isinstance(raw_value, str)
            or not isinstance(evidence_quote, str)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= len(pages)
        ):
            return None
        page = pages[page_number - 1]
        if evidence_quote not in str(page.get("raw_text", "")):
            return None
        item = self._field_extractor.build_grounded_field(name, raw_value, evidence_quote, doc_type)
        if item is None:
            return None
        item.update({"source_page_number": page_number, "source_page_index": page_number - 1})
        for token in page.get("tokens_json", []) or []:
            token_text = str(token.get("text", ""))
            if raw_value in token_text or evidence_quote in token_text:
                item["source_bbox"] = token.get("bbox")
                item["source_block_id"] = token.get("block_id")
                break
        return item

    @staticmethod
    def _document_context(
        pages: list[dict[str, Any]],
        candidates: dict[str, list[dict[str, Any]]],
        text_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not pages:
            return []
        text_fields = text_fields or list(_TEXT_FIELDS)
        priority: dict[int, float] = {1: 1.0, len(pages): 0.9}
        for name in text_fields:
            for item in candidates.get(name, []):
                page_number = int(item.get("source_page_number") or 0)
                if 1 <= page_number <= len(pages):
                    priority[page_number] = max(priority.get(page_number, 0.0), float(item.get("score", 0.0)))

        prioritized = sorted(priority, key=lambda page_number: (-priority[page_number], page_number))
        remaining_pages = [page_number for page_number in range(1, len(pages) + 1) if page_number not in priority]
        ordered_pages = prioritized + remaining_pages
        context: dict[int, str] = {}
        remaining = _MAX_TEXT_CONTEXT_CHARS
        for page_number in ordered_pages:
            raw_text = str(pages[page_number - 1].get("raw_text", "")).strip()
            if not raw_text or remaining <= 0:
                continue
            context[page_number] = raw_text[:remaining]
            remaining -= len(context[page_number])
        return [
            {"page_number": page_number, "raw_text": context[page_number]}
            for page_number in ordered_pages
            if page_number in context
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
        return fallback
