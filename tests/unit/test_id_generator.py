import re

from app.shared.utils.hash import build_idempotency_key, sha256
from app.shared.utils.id_generator import generate_queue_id


def test_queue_id_format() -> None:
    qid = generate_queue_id()
    assert re.match(r"^AIQ-\d{8}-\d{6}$", qid) is not None


def test_idempotency_key_consistency() -> None:
    k1 = build_idempotency_key("DOC-001", "INV", 1, "file.pdf", "/path/doc.pdf")
    k2 = build_idempotency_key("DOC-001", "INV", 1, "file.pdf", "/path/doc.pdf")
    assert k1 == k2
    assert len(k1) == 64


def test_idempotency_key_changes_on_diff() -> None:
    k1 = build_idempotency_key("DOC-001", "INV", 1, "file.pdf", "/path/a.pdf")
    k2 = build_idempotency_key("DOC-001", "INV", 1, "file.pdf", "/path/b.pdf")
    assert k1 != k2


def test_sha256_length() -> None:
    h = sha256("test")
    assert len(h) == 64
    assert h == sha256("test")
