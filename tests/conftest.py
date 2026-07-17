import sys
import types

import pytest

if "structlog" not in sys.modules:
    sys.modules["structlog"] = types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    )


@pytest.fixture
def sample_invoice_payload() -> dict:
    return {
        "DOC_NO": "INV-2026-0007842",
        "DOC_TYPE": "INV",
        "DOC_SEQ": 1,
        "TRANS_TYPE_CD": "LSP-J",
        "FILE_NM": "INV-2026-0007842.pdf",
        "AI_SCAN_APP": "VISION",
        "PATH_FILE": "https://doc-server/INV-2026-0007842.pdf",
    }


@pytest.fixture
def sample_dn_payload() -> dict:
    return {
        "DOC_NO": "DN-2026-000100",
        "DOC_TYPE": "DN",
        "DOC_SEQ": 1,
        "TRANS_TYPE_CD": "LSP-J",
        "FILE_NM": "DN-2026-000100.pdf",
        "AI_SCAN_APP": "VISION",
        "PATH_FILE": "https://doc-server/DN-2026-000100.pdf",
    }
