import uuid
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from app.domain.entities.normalized_request import (
    NormalizedDocumentRequest,
    NormalizedJobRequest,
)
from app.shared.utils.hash import build_idempotency_key
from app.shared.utils.id_generator import generate_queue_id


def normalize_legacy_request(payload: dict[str, Any]) -> NormalizedJobRequest:
    """Convert legacy single-document format to NormalizedJobRequest."""
    queue_id = payload.get("QUEUE_ID") or generate_queue_id()
    message_id = f"MSG-{queue_id}"

    doc = NormalizedDocumentRequest(
        external_document_id=f"DOC-001",
        document_index=0,
        document_type=payload.get("DOC_TYPE", ""),
        document_category="MAIN_DOCUMENT",
        file_name=payload.get("FILE_NM", ""),
        file_url=payload.get("PATH_FILE", ""),
        mime_type=_guess_mime(payload.get("FILE_NM", "")),
    )

    return NormalizedJobRequest(
        message_id=message_id,
        queue_id=queue_id,
        correlation_id=queue_id,
        source_system=payload.get("AI_SCAN_APP", "VISION"),
        request_schema_version="1.0",
        idempotency_key=build_idempotency_key(
            payload.get("DOC_NO", ""),
            payload.get("DOC_TYPE", ""),
            payload.get("DOC_SEQ", 0),
            payload.get("FILE_NM", ""),
            payload.get("PATH_FILE", ""),
        ),
        business_entity_type="PAYMENT_VOUCHER",
        business_entity_id=payload.get("DOC_NO", ""),
        business_entity_year=payload.get("PV_YEAR"),
        transaction_type=payload.get("TRANS_TYPE_CD", ""),
        documents=[doc],
        processing_options={"output_detail_level": "FULL"},
        raw_payload=payload,
    )


def normalize_batch_request(payload: dict[str, Any]) -> NormalizedJobRequest:
    """Convert batch multi-document format to NormalizedJobRequest."""
    context = payload.get("business_context", payload.get("context", {})) or {}
    queue_id = payload.get("queue_no", payload.get("QUEUE_ID")) or generate_queue_id()
    message_id = payload.get("message_id", payload.get("MESSAGE_ID", f"MSG-{uuid.uuid4().hex[:12]}"))

    raw_docs = payload.get("documents", [])
    documents: list[NormalizedDocumentRequest] = []
    for i, d in enumerate(raw_docs):
        file_info = d.get("file", d)
        file_url = file_info.get("file_url", file_info.get("attachment_url", ""))
        file_name = file_info.get("file_name") or _filename_from_url(file_url)
        doc = NormalizedDocumentRequest(
            external_document_id=d.get("document_id", f"DOC-{i+1:03d}"),
            document_index=d.get("document_index", i),
            document_type=d.get("document_type", ""),
            document_category=d.get("document_category", "MAIN_DOCUMENT"),
            file_name=file_name,
            file_url=file_url,
            mime_type=file_info.get("mime_type", _guess_mime(file_name)),
            checksum_sha256=file_info.get("checksum_sha256"),
            metadata=d.get("metadata", {}),
        )
        documents.append(doc)

    idempotency_parts = [queue_id]
    for d in documents:
        idempotency_parts.extend([d.external_document_id, d.file_url])
    idempotency_key = build_idempotency_key(*idempotency_parts)

    return NormalizedJobRequest(
        message_id=message_id,
        queue_id=queue_id,
        correlation_id=payload.get("correlation_id", queue_id),
        trace_id=payload.get("trace_id"),
        source_system=payload.get("source_system", payload.get("request_source", "ELVIS")),
        request_schema_version=payload.get("request_schema_version", "1.1"),
        idempotency_key=idempotency_key,
        business_entity_type=context.get("entity_type", "PAYMENT_VOUCHER"),
        business_entity_id=context.get("entity_id", payload.get("pv_no")),
        business_entity_year=context.get("entity_year", payload.get("pv_year")),
        transaction_type=context.get("transaction_type", payload.get("transaction_type")),
        documents=documents,
        processing_options=payload.get("processing_options", {"output_detail_level": "FULL"}),
        business_context=context,
        request_metadata=payload.get("request_metadata", payload.get("metadata")),
        raw_payload=payload,
    )


def normalize_request(payload: dict[str, Any]) -> NormalizedJobRequest:
    """Auto-detect format and normalize."""
    if "documents" in payload and isinstance(payload.get("documents"), list):
        first = payload["documents"][0] if payload["documents"] else {}
        if "file" in first or "document_id" in first:
            return normalize_batch_request(payload)
    return normalize_legacy_request(payload)


def _guess_mime(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext, "application/octet-stream")


def _filename_from_url(url: str) -> str:
    return PurePosixPath(urlparse(url).path).name
