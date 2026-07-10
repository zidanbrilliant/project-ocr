from datetime import datetime
from typing import Any

from app.domain.entities.final_result import FinalResult
from app.shared.constants.statuses import OK


def build_internal_result(
    final: FinalResult,
    documents: list[dict[str, Any]],
    model_info: dict[str, Any] | None = None,
    pv_no: str | None = None,
    pv_year: str | None = None,
) -> dict[str, Any]:
    ok_count = sum(1 for d in documents if d.get("document_summary", {}).get("result") == OK)
    total = len(documents)

    return {
        "header": {
            "queue_no": final.queue_id,
            "pv_no": pv_no,
            "pv_year": pv_year,
            "overall_result": final.overall_result,
            "processing_status": final.processing_status,
            "ai_confidence": final.ai_confidence,
            "ai_confidence_level": final.ai_confidence_level,
            "processing": {
                "request_datetime": None,
                "start_datetime": None,
                "finish_datetime": final.published_at.isoformat() if final.published_at else None,
                "duration_ms": final.processing_time_ms,
            },
            "model": model_info or {"model_name": "ELVIS AI Verification", "model_version": "v2.6.0"},
            "summary": {"total_documents": total, "ok_documents": ok_count, "ng_documents": total - ok_count},
            "ai_note": final.ai_note or "",
        },
        "documents": documents,
    }


def build_document_ocr(ocr: dict[str, Any]) -> dict[str, Any]:
    fields = ocr.get("fields_json", {})
    return {
        "document_number": fields.get("document_number", {"value": None, "result": "NG", "confidence": None}),
        "transaction_date": fields.get("transaction_date", {"value": None, "result": "NG", "confidence": None}),
        "transaction_time": fields.get("transaction_time", {"value": None, "result": "NG", "confidence": None}),
        "vendor_name": fields.get("vendor_name", {"value": None, "result": "NG", "confidence": None}),
        "transaction_amount": fields.get("transaction_amount", {"value": None, "result": "NG", "confidence": None}),
    }


def build_document_summary(
    result: str,
    failed_rules: list[str] | None = None,
) -> dict[str, Any]:
    total = 9
    failed = len(failed_rules) if failed_rules else 0
    passed = total - failed

    return {
        "result": result,
        "total_validation": total,
        "passed_validation": passed,
        "failed_validation": failed,
        "failed_items": failed_rules or [],
        "reason": f"{result} - {failed} validation(s) failed" if failed else "All mandatory validation items passed successfully.",
        "recommendation": ["No further action is required."] if result == OK else ["Manual review recommended."],
    }
