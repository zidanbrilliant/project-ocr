from typing import Any

from app.shared.constants import return_codes, statuses

_REMARK_MAP: dict[str, str] = {
    "Submitted FILE_PATH is empty.": "Submitted FILE_PATH is empty.",
    "Document is missing from server": "Document is missing from server using submitted FILE_PATH.",
    "File corrupt or unreadable.": "File corrupt or unreadable.",
    "Unsupported document format.": "Unsupported document format.",
    "File size exceeds maximum limit.": "File size exceeds maximum limit.",
    "Document resolution is below minimum requirement.": "Document resolution is below minimum requirement.",
    "PDF page count exceeds maximum limit.": "PDF page count exceeds maximum limit.",
    "PDF is password protected and cannot be processed.": "PDF is password protected and cannot be processed.",
}


def build_document_error_result(payload: dict[str, Any], remark: str) -> dict[str, Any]:
    return {
        "QUEUE_ID": payload.get("QUEUE_ID", ""),
        "DOC_NO": payload.get("DOC_NO", ""),
        "DOC_TYPE": payload.get("DOC_TYPE", ""),
        "DOC_SEQ": payload.get("DOC_SEQ", 0),
        "TRANS_TYPE_CD": payload.get("TRANS_TYPE_CD", ""),
        "FILE_NM": payload.get("FILE_NM", ""),
        "AI_SCAN_APP": payload.get("AI_SCAN_APP", "VISION"),
        "AI_RETURN_STATUS": statuses.NG,
        "AI_RETURN_REMARK": _REMARK_MAP.get(remark, "Document could not be processed, please contact support."),
        "AI_RETURN_CD": return_codes.DOCUMENT_ERROR,
        "AI_RETURN_CONFIDENCE": None,
    }
