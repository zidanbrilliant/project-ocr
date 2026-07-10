import hashlib


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_idempotency_key(
    doc_no: str,
    doc_type: str,
    doc_seq: int,
    file_nm: str,
    path_file: str,
) -> str:
    path_hash = sha256(path_file)
    raw = f"{doc_no}|{doc_type}|{doc_seq}|{file_nm}|{path_hash}"
    return sha256(raw)
