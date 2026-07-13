import hashlib


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_idempotency_key(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return sha256(raw)
