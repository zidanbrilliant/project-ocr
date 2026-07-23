import asyncio
from pathlib import Path

import scripts.benchmark_pipeline as benchmark_pipeline
from app.application.services.local_runtime import LocalJobSnapshot


class FakeLocalExecutionService:
    calls: list[list[object]] = []

    async def run_inline(self, documents: list[object]) -> LocalJobSnapshot:
        self.calls.append(documents)
        file_name = documents[0].name
        result = {
            "documents": [
                {
                    "document_id": "document-1",
                    "document_name": file_name,
                    "document_result": "OK",
                    "processing_status": "COMPLETED",
                    "processing_time_ms": 12,
                    "fields": [
                        {"field_name": "document_number", "value": " inv-7 "},
                        {
                            "field_name": "transaction_amount",
                            "value": "1,110,000.00",
                            "currency": "IDR",
                        },
                        {
                            "field_name": "transaction_date",
                            "value": "2026-07-20",
                        },
                    ],
                    "field_candidate_audit": {
                        "document_number": [{"value": "INV-7"}],
                        "transaction_amount": [
                            {"value": 1_110_000, "currency": "IDR"}
                        ],
                        "transaction_date": [{"value": "2026-07-20"}],
                    },
                    "pages": [
                        {
                            "page_number": 1,
                            "ocr": {
                                "engine": "fake",
                                "raw_text": "private OCR trace",
                                "text_blocks": [],
                            },
                        }
                    ],
                    "errors": [],
                }
            ],
            "errors": [],
        }
        return LocalJobSnapshot(
            job_id="job-1",
            status="SUCCEEDED",
            completed_documents=1,
            total_documents=1,
            result=result,
            error=None,
        )


def test_benchmark_uses_local_execution_and_reports_field_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "invoice.png"
    image.write_bytes(b"image")
    FakeLocalExecutionService.calls = []
    monkeypatch.setattr(
        benchmark_pipeline,
        "LocalExecutionService",
        FakeLocalExecutionService,
    )
    expected = {
        image.name: {
            "document_number": "INV-7",
            "transaction_amount": {"value": 1_110_000, "currency": "IDR"},
            "transaction_date": "2026-07-20",
        }
    }

    report = asyncio.run(
        benchmark_pipeline.benchmark(tmp_path, "INV", expected)
    )

    assert len(FakeLocalExecutionService.calls) == 1
    submitted = FakeLocalExecutionService.calls[0][0]
    assert submitted.name == image.name
    assert submitted.content == b"image"
    assert submitted.doc_type == "INV"
    row = report["results"][0]
    assert row["file_name"] == image.name
    assert row["expected"] == expected[image.name]
    assert row["actual"]["document_number"] == {"value": " inv-7 "}
    assert row["checks"] == {
        "document_number": True,
        "transaction_amount": True,
        "transaction_date": True,
    }
    assert isinstance(row["duration_ms"], int)
    assert row["error"] is None
    assert "trace" not in row
    assert report["accuracy"]["field_acceptance"] == {
        "passed": True,
        "failed_fields": [],
        "threshold": 0.85,
    }
    assert report["accuracy"]["mismatch_examples"] == []


def test_benchmark_includes_raw_ocr_only_when_trace_is_requested(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "invoice.png").write_bytes(b"image")
    monkeypatch.setattr(
        benchmark_pipeline,
        "LocalExecutionService",
        FakeLocalExecutionService,
    )

    report = asyncio.run(
        benchmark_pipeline.benchmark(tmp_path, "INV", include_trace=True)
    )

    assert report["results"][0]["trace"]["ocr_pages"] == [
        {
            "page_number": 1,
            "engine": "fake",
            "raw_text": "private OCR trace",
            "text_blocks": [],
        }
    ]
