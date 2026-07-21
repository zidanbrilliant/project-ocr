from __future__ import annotations

import base64
from typing import Any

from app.application.services.field_extraction_service import FieldExtractionService
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
_VISUAL_FIELDS = ("document_number", "transaction_date")
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
_NON_ISSUE_DATE_ROLES = {"due_date", "payment_date", "print_date", "tax_period", "unlabelled"}
_MAX_VISUAL_CONTEXT_CHARS = 12_000
_MAX_VISUAL_PAGES = 2


class FieldReasoningService:
    """Resolve fields once, with deterministic fallback and grounded Qwen rescue."""

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
        page_images: list[bytes] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        fields = self._field_extractor.resolve_document_candidates(candidates)
        resolved = self._strict_core_fallback(fields, candidates)
        visual_fields = [
            name for name in _VISUAL_FIELDS if self._needs_visual_verification(name, fields.get(name, {}), candidates)
        ]
        if not settings.REASONING_ENABLED or not visual_fields:
            return resolved, {"enabled": settings.REASONING_ENABLED, "used": False, "engine": "deterministic"}
        if not page_images:
            return resolved, {
                "enabled": True,
                "used": False,
                "engine": "deterministic",
                "error": "visual_pages_unavailable",
            }
        if not self._adapter.is_available:
            return resolved, {
                "enabled": True,
                "used": False,
                "engine": "deterministic",
                "error": self._adapter.load_error or "reasoning_not_ready",
            }

        candidate_index: dict[str, dict[str, dict[str, Any]]] = {}
        payload_fields: dict[str, list[dict[str, Any]]] = {}
        for name in visual_fields:
            items = candidates.get(name, [])
            eligible_items = [
                item
                for item in items
                if not (name == "transaction_date" and item.get("date_role") in _NON_ISSUE_DATE_ROLES)
            ]
            # One value can be discovered by several OCR paths.  Give the model
            # distinct values, not twelve copies of the same noisy candidate.
            unique_items: dict[tuple[Any, ...], dict[str, Any]] = {}
            for item in eligible_items:
                key = (
                    str(item.get("value")),
                    item.get("currency"),
                    item.get("amount_role"),
                    item.get("source_page_number"),
                    item.get("label_relation"),
                )
                if key not in unique_items or float(item.get("score", item["confidence"])) > float(
                    unique_items[key].get("score", unique_items[key]["confidence"])
                ):
                    unique_items[key] = item
            indexed: dict[str, dict[str, Any]] = {}
            public_items: list[dict[str, Any]] = []
            for index, item in enumerate(
                sorted(unique_items.values(), key=lambda item: item.get("score", item["confidence"]), reverse=True)
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
                        "extraction_method": item.get("extraction_method"),
                    }
                )
            candidate_index[name] = indexed
            payload_fields[name] = public_items

        document_context = self._document_context(pages or [], candidates, visual_fields)
        images = self._visual_images(page_images or [], document_context)
        if not payload_fields or not document_context:
            return resolved, {"enabled": True, "used": False, "engine": "deterministic"}

        reply = await self._adapter.select(
            {
                "document_type": doc_type,
                "requested_fields": visual_fields,
                "field_definitions": {name: _FIELD_DEFINITIONS.get(name, name) for name in payload_fields},
                "candidates": payload_fields,
                "page_ocr": document_context,
                "images": images,
            }
        )
        applied: list[str] = []
        conflicts: list[str] = []
        for decision in reply.get("decisions", []) if isinstance(reply.get("decisions"), list) else []:
            if not isinstance(decision, dict):
                continue
            name, candidate_id = decision.get("field_name"), decision.get("candidate_id")
            item = candidate_index.get(name, {}).get(candidate_id)
            if item is None:
                item = self._grounded_candidate(decision, pages or [], doc_type)
            if item is None:
                continue
            current = resolved.get(name, {})
            if current.get("value") is not None and current.get("value") != item.get("value"):
                resolved[name] = self._conflict(current, item, candidates.get(name, []))
                conflicts.append(name)
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
                    "reasoning_engine": "qwen3-vl-8b",
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
            "engine": "qwen3-vl-8b",
            "resolved_fields": applied,
            "context_pages": [page["page_number"] for page in document_context],
            "visual_pages": [item["page_number"] for item in images],
            "conflicts": conflicts,
            "error": reply.get("error"),
        }

    @staticmethod
    def _needs_visual_verification(
        name: str, field: dict[str, Any], candidates: dict[str, list[dict[str, Any]]]
    ) -> bool:
        # Invoice/date confidence becomes high only after an independent visual check.
        if field.get("value") is not None:
            return True
        if field.get("status") != "FOUND" or field.get("candidate_only"):
            return True
        if name == "transaction_date" and field.get("date_role") != "issue_date":
            return True
        if field.get("extraction_method") == "context_label_value":
            return True
        return len({str(item.get("value")) for item in candidates.get(name, [])}) > 1

    @staticmethod
    def _conflict(
        current: dict[str, Any], visual: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "value": None,
            "raw_value": None,
            "confidence": 0.0,
            "score": 0.0,
            "status": "NOT_FOUND",
            "reason_code": "DETERMINISTIC_VISUAL_CONFLICT",
            "verification_status": "CONFLICT",
            "manual_review_required": True,
            "candidate_count": len(candidates),
            "alternatives": [
                {"value": current.get("value"), "source_text": current.get("source_text")},
                {"value": visual.get("value"), "source_text": visual.get("source_text")},
            ],
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
                single_source = name in _VISUAL_FIELDS
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
            name not in _CORE_SELECTION_FIELDS
            or not isinstance(raw_value, str)
            or not isinstance(evidence_quote, str)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= len(pages)
        ):
            return None
        page = pages[page_number - 1]
        if evidence_quote not in str(page.get("raw_text", "")):
            return None
        item = self._field_extractor.build_grounded_candidate(name, raw_value, evidence_quote, doc_type)
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
        visual_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not pages:
            return []
        visual_fields = visual_fields or list(_VISUAL_FIELDS)
        priority: dict[int, float] = {1: 1.0, len(pages): 0.9}
        for name in visual_fields:
            for item in candidates.get(name, []):
                page_number = int(item.get("source_page_number") or 0)
                if 1 <= page_number <= len(pages):
                    priority[page_number] = max(priority.get(page_number, 0.0), float(item.get("score", 0.0)))

        prioritized = sorted(priority, key=lambda page_number: (-priority[page_number], page_number))
        remaining_pages = [page_number for page_number in range(1, len(pages) + 1) if page_number not in priority]
        ordered_pages = prioritized + remaining_pages
        context: dict[int, str] = {}
        remaining = _MAX_VISUAL_CONTEXT_CHARS
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

    @staticmethod
    def _visual_images(page_images: list[bytes], context_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for page in context_pages[:_MAX_VISUAL_PAGES]:
            page_number = int(page["page_number"])
            if 1 <= page_number <= len(page_images) and page_images[page_number - 1]:
                images.append(
                    {
                        "page_number": page_number,
                        "image_b64": base64.b64encode(page_images[page_number - 1]).decode("ascii"),
                    }
                )
        return images

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
