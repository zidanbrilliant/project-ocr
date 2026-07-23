import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

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


def test_benchmark_marks_every_labeled_field_mismatched_on_processing_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "failed.png"
    image.write_bytes(b"image")

    class FailedService:
        async def run_inline(self, documents: list[object]) -> LocalJobSnapshot:
            document = {
                "document_name": documents[0].name,
                "processing_status": "FAILED",
                "fields": [
                    {
                        "field_name": "document_number",
                        "value": None,
                        "status": "NOT_FOUND",
                    },
                    {
                        "field_name": "transaction_amount",
                        "value": 10,
                        "currency": "IDR",
                    },
                ],
                "errors": [{"stage": "PROCESSING", "message": "model unavailable"}],
                "pages": [],
            }
            return LocalJobSnapshot(
                job_id="job-failed",
                status="FAILED",
                completed_documents=1,
                total_documents=1,
                result={"documents": [document], "errors": []},
                error=None,
            )

    monkeypatch.setattr(
        benchmark_pipeline,
        "LocalExecutionService",
        FailedService,
    )

    report = asyncio.run(
        benchmark_pipeline.benchmark(
            tmp_path,
            "INV",
            {
                image.name: {
                    "document_number": None,
                    "transaction_amount": {"value": 10, "currency": "IDR"},
                }
            },
        )
    )

    row = report["results"][0]
    assert row["error"] == "model unavailable"
    assert row["checks"] == {
        "document_number": False,
        "transaction_amount": False,
    }
    assert report["accuracy"]["all_core_fields_exact"] == 0


def test_benchmark_evaluates_val_with_the_local_execution_detector(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "invoice.png").write_bytes(b"image")
    yolo_root = tmp_path / "yolo"
    (yolo_root / "val").mkdir(parents=True)
    detector = object()

    class FakeService(FakeLocalExecutionService):
        def __init__(self) -> None:
            self._processor = types.SimpleNamespace(_yolo=detector)

    calls: list[tuple[object, Path, set[str]]] = []

    async def fake_evaluate(
        received_detector: object,
        dataset_root: Path,
        required_labels: set[str],
    ) -> dict:
        calls.append((received_detector, dataset_root, required_labels))
        return {"acceptance": {"passed": True}}

    monkeypatch.setattr(benchmark_pipeline, "LocalExecutionService", FakeService)
    monkeypatch.setattr(
        benchmark_pipeline,
        "evaluate_yolo_validation",
        fake_evaluate,
    )

    report = asyncio.run(
        benchmark_pipeline.benchmark(
            input_dir,
            "INV",
            yolo_dataset_root=yolo_root,
        )
    )

    assert calls == [
        (
            detector,
            yolo_root / "val",
            {"barcode", "materai", "signature", "stamp"},
        )
    ]
    assert report["yolo_validation"] == {"acceptance": {"passed": True}}


def test_required_yolo_gate_writes_report_before_exit_two(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "report.json"
    input_dir = tmp_path / "input"
    yolo_root = tmp_path / "yolo"
    input_dir.mkdir()
    yolo_root.mkdir()
    expected_report = {
        "accuracy": {"field_acceptance": {"passed": True}},
        "yolo_validation": {"acceptance": {"passed": False}},
        "results": [],
    }

    async def fake_benchmark(*args, **kwargs) -> dict:
        return expected_report

    monkeypatch.setattr(benchmark_pipeline, "benchmark", fake_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_pipeline.py",
            str(input_dir),
            "--yolo-dataset-root",
            str(yolo_root),
            "--require-yolo-gate",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as error:
        benchmark_pipeline.main()

    assert error.value.code == 2
    assert json.loads(output.read_text(encoding="utf-8")) == expected_report
