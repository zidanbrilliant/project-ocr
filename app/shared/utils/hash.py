import hashlib


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_idempotency_key(*parts: str) -> str:
    raw = "|".join(parts)
    return sha256(raw)
