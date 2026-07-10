from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentIdentity:
    doc_no: str
    doc_type: str
    doc_seq: int
    file_nm: str

    def to_idempotency_parts(self) -> str:
        return f"{self.doc_no}|{self.doc_type}|{self.doc_seq}|{self.file_nm}"
