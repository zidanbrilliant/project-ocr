from __future__ import annotations

import re
from time import monotonic
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
_TEXT_FIELDS = ("document_number", "transaction_date")
_GROUNDED_MODEL_CONFIDENCE = 0.85


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
        resolved = self._fallback_fields(fields, candidates)
        text_fields = list(_TEXT_FIELDS)
        document_context = self._document_context(pages or [])
        if not settings.REASONING_ENABLED:
            return resolved, self._audit(False, "deterministic", text_fields, document_context)
        if not document_context:
            return resolved, self._audit(False, "deterministic", text_fields, document_context)

        started = monotonic()
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
        rejected: list[dict[str, str]] = []
        for decision in reply.get("decisions", []) if isinstance(reply.get("decisions"), list) else []:
            if not isinstance(decision, dict):
                rejected.append({"field": "unknown", "reason": "invalid_decision"})
                continue
            name = decision.get("field_name")
            item = self._grounded_candidate(decision, pages or [], doc_type)
            if item is None:
                rejected.append({"field": str(name or "unknown"), "reason": "ungrounded_or_invalid_value"})
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
                    "independent_evidence_count": 1,
                    "confidence_source": "GROUNDED_MODEL_SELECTION",
                    "confidence_calibrated": False,
                    # Operational floor only: exact OCR grounding, not a calibrated probability.
                    "confidence": max(float(chosen.get("confidence", 0.0)), _GROUNDED_MODEL_CONFIDENCE),
                    "score": max(float(chosen.get("score", 0.0)), _GROUNDED_MODEL_CONFIDENCE),
                    "manual_review_required": False,
                }
            )
            resolved[name] = chosen
            applied.append(name)
        audit = self._audit(bool(applied), "qwen3.5-9b", text_fields, document_context)
        audit.update(
            {
                "adapter_available": self._adapter.is_available,
                "resolved_fields": applied,
                "overrides": overrides,
                "grounding_rejections": rejected,
                "decision_count": len(reply.get("decisions", [])) if isinstance(reply.get("decisions"), list) else 0,
                "generation_chars": reply.get("generation_chars"),
                "generation_attempts": reply.get("generation_attempts"),
                "error": reply.get("error"),
                "latency_ms": round((monotonic() - started) * 1000),
            }
        )
        return resolved, audit

    @staticmethod
    def _audit(
        used: bool, engine: str, requested_fields: list[str], document_context: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "enabled": settings.REASONING_ENABLED,
            "used": used,
            "engine": engine,
            "requested_fields": requested_fields,
            "context_pages": [page["page_number"] for page in document_context],
            "visual_pages": [],
            "overrides": [],
            "conflicts": [],
            "grounding_rejections": [],
        }

    @staticmethod
    def _fallback_fields(
        fields: dict[str, dict[str, Any]], candidates: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """Keep deterministic evidence visible when Qwen is unavailable or rejects its response."""
        resolved = dict(fields)
        for name in _TEXT_FIELDS:
            field = fields.get(name, {})
            if field.get("value") is not None:
                resolved[name] = {
                    **field,
                    "reason_code": "DETERMINISTIC_FALLBACK",
                    "verification_status": "FALLBACK_UNVERIFIED",
                    "independent_evidence_count": 1,
                    "confidence_source": "DETERMINISTIC_HEURISTIC",
                    "confidence_calibrated": False,
                    "manual_review_required": True,
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
        page_text = str(page.get("raw_text", ""))
        if not _ocr_contains(page_text, raw_value) or not _ocr_contains(page_text, evidence_quote):
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
    def _document_context(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass every OCR page in document order; candidates are audit-only."""
        return [
            {"page_number": page_number, "raw_text": raw_text}
            for page_number, page in enumerate(pages, start=1)
            if (raw_text := str(page.get("raw_text", "")).strip())
        ]

    async def summarize(
        self, document_result: str, fields: dict[str, dict[str, Any]], failed_rules: list[dict[str, Any]]
    ) -> dict[str, Any]:
        failed_items = [str(rule.get("rule_name", "Validation failed")) for rule in failed_rules]
        if self._adapter is not None and self._adapter.is_available:
            try:
                return await self._summarize_with_llm(document_result, fields, failed_rules, failed_items)
            except Exception:
                pass
        return {
            "result": document_result,
            "failed_items": failed_items,
            "reason": "Verification passed." if not failed_items else "; ".join(failed_items[:3]),
            "recommendations": [],
            "engine": "deterministic",
        }

    async def _summarize_with_llm(
        self,
        document_result: str,
        fields: dict[str, dict[str, Any]],
        failed_rules: list[dict[str, Any]],
        failed_items: list[str],
    ) -> dict[str, Any]:
        field_str = ", ".join(
            f"{name}={field.get('value')}" for name, field in fields.items()
            if field.get("value") is not None
        )
        rule_str = "; ".join(
            f"{r.get('rule_name')}: {r.get('message', '')}" for r in failed_rules
        ) if failed_rules else "None"
        prompt = (
            f"Document verification: {document_result}. "
            f"Fields: {field_str}. "
            f"Failed rules: {rule_str}. "
            f"Provide a 1-2 sentence summary in Bahasa Indonesia."
        )
        result = await self._adapter.select({"requests": [{"id": "summary", "text": prompt}]})
        decisions = result.get("decisions", [])
        ai_reason = decisions[0].get("selected", "") if decisions else ""
        engine = "qwen3.5-9b" if ai_reason.strip() else "deterministic"
        return {
            "result": document_result,
            "failed_items": failed_items,
            "reason": ai_reason.strip() or ("Verification passed." if not failed_items else "; ".join(failed_items[:3])),
            "recommendations": [],
            "engine": engine,
        }


def _ocr_contains(text: str, value: str) -> bool:
    """Accept harmless OCR spacing/punctuation differences while keeping evidence grounded."""
    normalized_value = re.sub(r"[^0-9a-z]+", "", value.casefold())
    return bool(normalized_value) and normalized_value in re.sub(r"[^0-9a-z]+", "", text.casefold())
