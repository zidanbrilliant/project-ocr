from typing import Any


class AIResultDTO:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.queue_id: str = payload.get("QUEUE_ID", "")
        self.doc_no: str = payload.get("DOC_NO", "")
        self.doc_type: str = payload.get("DOC_TYPE", "")
        self.doc_seq: int = payload.get("DOC_SEQ", 0)
        self.trans_type_cd: str = payload.get("TRANS_TYPE_CD", "")
        self.file_nm: str = payload.get("FILE_NM", "")
        self.ai_scan_app: str = payload.get("AI_SCAN_APP", "VISION")
        self.ai_return_status: str = payload.get("AI_RETURN_STATUS", "NG")
        self.ai_return_remark: str = payload.get("AI_RETURN_REMARK", "")
        self.ai_return_cd: str = payload.get("AI_RETURN_CD", "SUCCESS")
        self.ai_return_confidence: int | None = payload.get("AI_RETURN_CONFIDENCE")

    def to_rabbitmq(self) -> dict[str, Any]:
        return {
            "QUEUE_ID": self.queue_id,
            "DOC_NO": self.doc_no,
            "DOC_TYPE": self.doc_type,
            "DOC_SEQ": self.doc_seq,
            "TRANS_TYPE_CD": self.trans_type_cd,
            "FILE_NM": self.file_nm,
            "AI_SCAN_APP": self.ai_scan_app,
            "AI_RETURN_STATUS": self.ai_return_status,
            "AI_RETURN_REMARK": self.ai_return_remark,
            "AI_RETURN_CD": self.ai_return_cd,
            "AI_RETURN_CONFIDENCE": self.ai_return_confidence,
        }
