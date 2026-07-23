import sys
import types
from importlib import import_module

sys.modules.setdefault(
    "cv2",
    types.SimpleNamespace(
        IMREAD_COLOR=1,
        COLOR_BGR2GRAY=0,
        THRESH_BINARY=0,
        imdecode=lambda *args, **kwargs: None,
        cvtColor=lambda *args, **kwargs: None,
        threshold=lambda *args, **kwargs: (None, None),
        imencode=lambda *args, **kwargs: (
            True,
            types.SimpleNamespace(tobytes=lambda: b""),
        ),
    ),
)
sys.modules.setdefault(
    "numpy",
    types.SimpleNamespace(
        frombuffer=lambda data, *args, **kwargs: data,
        uint8=object(),
        ndarray=object,
    ),
)
sys.modules.setdefault(
    "structlog",
    types.SimpleNamespace(
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(),
        stdlib=types.SimpleNamespace(BoundLogger=object),
    ),
)
sys.modules.setdefault(
    "fitz",
    types.SimpleNamespace(),
)
sys.modules.setdefault(
    "asyncpg",
    types.SimpleNamespace(),
)
sys.modules.setdefault(
    "streamlit",
    types.SimpleNamespace(
        cache_resource=lambda **kwargs: lambda function: function,
        set_page_config=lambda **kwargs: None,
    ),
)

LocalJobSnapshot = import_module(
    "app.application.services.local_runtime"
).LocalJobSnapshot
upload_app = import_module("scripts.upload_app")


def test_failed_job_with_canonical_result_renders_detail_json(monkeypatch) -> None:
    envelope = {
        "documents": [
            {
                "document_id": "LOCAL-DOC-001",
                "document_name": "failed.png",
                "document_result": "NG",
                "processing_status": "FAILED",
                "pages": [],
                "errors": [
                    {
                        "stage": "PROCESSING",
                        "message": "model unavailable",
                    }
                ],
            }
        ]
    }
    snapshot = LocalJobSnapshot(
        job_id="job-failed",
        status="FAILED",
        completed_documents=1,
        total_documents=1,
        result=envelope,
        error=None,
    )
    errors: list[str] = []
    rendered_json: list[dict] = []
    fake_streamlit = types.SimpleNamespace(
        error=errors.append,
        json=rendered_json.append,
        selectbox=lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(upload_app, "st", fake_streamlit)

    upload_app._render_finished_job(snapshot, snapshot.job_id)

    assert rendered_json == [envelope]
    assert "model unavailable" in errors
    assert "Local processing failed." not in errors


def test_failed_job_without_result_uses_generic_failure(monkeypatch) -> None:
    snapshot = LocalJobSnapshot(
        job_id="job-failed",
        status="FAILED",
        completed_documents=0,
        total_documents=1,
        result=None,
        error="model warmup failed",
    )
    errors: list[str] = []
    fake_streamlit = types.SimpleNamespace(error=errors.append)
    monkeypatch.setattr(upload_app, "st", fake_streamlit)

    upload_app._render_finished_job(snapshot, snapshot.job_id)

    assert errors == ["model warmup failed"]
