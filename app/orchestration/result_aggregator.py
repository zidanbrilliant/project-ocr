from typing import Any


def aggregate_transaction_result(
    queue_id: str,
    transaction_id: str,
    trace_id: str,
    received_at: str,
    completed_at: str,
    processing_time_ms: int,
    documents: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    model_info: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    summary = {
        "total_documents": len(documents),
        "successful_documents": 0,
        "partial_documents": 0,
        "failed_documents": 0,
        "total_pages": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "is_complete": False,
    }

    for doc in documents:
        doc_status = doc.get("status", "FAILED")
        if doc_status == "SUCCESS":
            summary["successful_documents"] += 1
        elif doc_status == "PARTIAL_SUCCESS":
            summary["partial_documents"] += 1
        else:
            summary["failed_documents"] += 1

        for page in doc.get("pages", []):
            summary["total_pages"] += 1
            if page.get("status") == "SUCCESS":
                summary["successful_pages"] += 1
            else:
                summary["failed_pages"] += 1

    summary["is_complete"] = summary["failed_pages"] == 0

    return {
        "schema_version": "1.0.0",
        "pipeline_version": "vision-pipeline-2026.07",
        "queue_id": queue_id,
        "transaction_id": transaction_id,
        "correlation_id": transaction_id,
        "status": status,
        "received_at": received_at,
        "completed_at": completed_at,
        "processing_time_ms": processing_time_ms,
        "validation_summary": summary,
        "models": model_info,
        "documents": documents,
        "errors": errors,
        "trace": {"trace_id": trace_id, "request_id": queue_id},
    }
