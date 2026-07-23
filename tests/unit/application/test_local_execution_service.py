import asyncio
import threading
import time
from typing import Any

import pytest

from app.application.services.local_execution_service import LocalExecutionService
from app.application.services.local_runtime import LocalDocument
from app.shared.config.settings import settings


def document(name: str) -> LocalDocument:
    return LocalDocument(name, "image/png", name.encode(), "INV")


def successful_raw_result(name: str) -> dict[str, Any]:
    return {
        "document_id": f"document-{name}",
        "status": "OK",
        "doc_type": "INV",
        "pages": [],
        "validation": {"passed": True},
        "confidence": {"overall_result": "OK"},
        "processing_time_ms": 1,
    }


def failed_raw_result(name: str) -> dict[str, Any]:
    return {
        "filename": name,
        "doc_type": "INV",
        "status": "NG",
        "error": f"cannot process {name}",
        "processing_time_ms": 1,
        "document_info": {},
        "ocr": {},
        "detections": [],
        "detection_aggregated": {},
        "barcode": {},
        "fields": {},
        "validation": {},
        "confidence": {},
        "remarks": f"cannot process {name}",
        "pages": [],
    }


class RecordingProcessor:
    def __init__(
        self,
        failing_name: str | None = None,
        returning_error_name: str | None = None,
    ) -> None:
        self.failing_name = failing_name
        self.returning_error_name = returning_error_name
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.database_saves = 0

    async def process(self, file_bytes: bytes, filename: str, doc_type: str) -> dict[str, Any]:
        self.calls.append(filename)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            if filename == self.failing_name:
                raise RuntimeError(f"cannot process {filename}")
            if filename == self.returning_error_name:
                return failed_raw_result(filename)
            return successful_raw_result(filename)
        finally:
            self.active -= 1

    async def _save_to_db(self, *_args: Any) -> None:
        self.database_saves += 1


def test_run_inline_bounds_parallel_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_PARALLEL_DOCUMENTS", 2)
    processor = RecordingProcessor()
    service = LocalExecutionService(processor=processor)

    snapshot = asyncio.run(
        service.run_inline([document("a.png"), document("b.png"), document("c.png")])
    )

    assert processor.max_active == 2
    assert sorted(processor.calls) == ["a.png", "b.png", "c.png"]
    assert snapshot.result is not None
    assert snapshot.result["header"]["correlation_id"] == snapshot.job_id
    assert snapshot.result["processing"]["job_id"] == snapshot.job_id
    assert processor.database_saves == 0


def test_run_inline_keeps_successful_documents_when_one_fails() -> None:
    processor = RecordingProcessor(failing_name="b.png")
    service = LocalExecutionService(processor=processor)

    snapshot = asyncio.run(
        service.run_inline([document("a.png"), document("b.png"), document("c.png")])
    )

    assert snapshot.status == "PARTIAL_SUCCESS"
    assert snapshot.completed_documents == 3
    assert snapshot.result is not None
    assert [item["document_name"] for item in snapshot.result["documents"]] == [
        "a.png",
        "b.png",
        "c.png",
    ]
    assert snapshot.result["documents"][1]["processing_status"] == "FAILED"
    assert snapshot.result["documents"][1]["document_result"] == "NG"
    assert snapshot.result["errors"] == [
        {
            "document_name": "b.png",
            "stage": "PROCESSING",
            "message": "cannot process b.png",
        }
    ]
    assert snapshot.result["header"]["processing_result"] == "PARTIAL_SUCCESS"


def test_run_inline_treats_returned_processor_error_as_failed_document() -> None:
    processor = RecordingProcessor(returning_error_name="b.png")
    service = LocalExecutionService(processor=processor)

    snapshot = asyncio.run(
        service.run_inline([document("a.png"), document("b.png"), document("c.png")])
    )

    assert processor.calls == ["a.png", "b.png", "c.png"]
    assert snapshot.status == "PARTIAL_SUCCESS"
    assert snapshot.completed_documents == 3
    assert snapshot.result is not None
    assert snapshot.result["documents"][1]["processing_status"] == "FAILED"
    assert snapshot.result["documents"][1]["document_result"] == "NG"
    assert snapshot.result["errors"] == [
        {
            "document_name": "b.png",
            "stage": "PROCESSING",
            "message": "cannot process b.png",
        }
    ]
    assert snapshot.result["header"]["processing_result"] == "PARTIAL_SUCCESS"


def test_run_inline_marks_all_failed_result_envelope_failed() -> None:
    snapshot = asyncio.run(
        LocalExecutionService(
            processor=RecordingProcessor(failing_name="only.png")
        ).run_inline([document("only.png")])
    )

    assert snapshot.status == "FAILED"
    assert snapshot.result is not None
    assert snapshot.result["header"]["processing_status"] == "FAILED"
    assert snapshot.result["header"]["processing_result"] == "FAILED"
    assert snapshot.result["processing"]["status"] == "FAILED"
    assert snapshot.result["documents"][0]["processing_status"] == "FAILED"


class BlockingProcessor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def process(self, file_bytes: bytes, filename: str, doc_type: str) -> dict[str, Any]:
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.005)
        return successful_raw_result(filename)


def test_submit_returns_while_processing_continues_in_background() -> None:
    processor = BlockingProcessor()
    service = LocalExecutionService(processor=processor)

    job_id = service.submit([document("a.png")])

    assert processor.started.wait(timeout=1)
    assert service.snapshot(job_id).status == "RUNNING"
    processor.release.set()

    deadline = time.monotonic() + 1
    while service.snapshot(job_id).status == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.snapshot(job_id).status == "SUCCEEDED"


class JobRecordingProcessor:
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.second_started = threading.Event()
        self.release_first = threading.Event()

    async def process(self, file_bytes: bytes, filename: str, doc_type: str) -> dict[str, Any]:
        if filename == "first.png":
            self.first_started.set()
            while not self.release_first.is_set():
                await asyncio.sleep(0.005)
        else:
            self.second_started.set()
        return successful_raw_result(filename)


def test_submit_bounds_active_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LOCAL_MAX_ACTIVE_JOBS", 1)
    processor = JobRecordingProcessor()
    service = LocalExecutionService(processor=processor)

    first_job = service.submit([document("first.png")])
    assert processor.first_started.wait(timeout=1)
    second_job = service.submit([document("second.png")])

    assert not processor.second_started.wait(timeout=0.05)
    processor.release_first.set()
    assert processor.second_started.wait(timeout=1)

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if all(
            service.snapshot(job_id).status == "SUCCEEDED"
            for job_id in (first_job, second_job)
        ):
            break
        time.sleep(0.005)
    assert service.snapshot(first_job).status == "SUCCEEDED"
    assert service.snapshot(second_job).status == "SUCCEEDED"


class WarmupRecordingProcessor:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.warmup_started = threading.Event()
        self.release_warmup = threading.Event()

    async def warmup(self) -> None:
        self.events.append("warmup:start")
        self.warmup_started.set()
        while not self.release_warmup.is_set():
            await asyncio.sleep(0.005)
        self.events.append("warmup:end")

    async def process(self, file_bytes: bytes, filename: str, doc_type: str) -> dict[str, Any]:
        self.events.append(f"process:{filename}")
        return successful_raw_result(filename)


def test_submit_warms_processor_once_before_concurrent_and_subsequent_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LOCAL_MAX_ACTIVE_JOBS", 2)
    processor = WarmupRecordingProcessor()
    service = LocalExecutionService(processor=processor)

    first_job = service.submit([document("first.png")])
    assert processor.warmup_started.wait(timeout=1)
    second_job = service.submit([document("second.png")])

    assert processor.events == ["warmup:start"]
    processor.release_warmup.set()

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if all(
            service.snapshot(job_id).status == "SUCCEEDED"
            for job_id in (first_job, second_job)
        ):
            break
        time.sleep(0.005)

    third_job = service.submit([document("third.png")])
    deadline = time.monotonic() + 1
    while service.snapshot(third_job).status != "SUCCEEDED" and time.monotonic() < deadline:
        time.sleep(0.005)

    assert service.snapshot(first_job).status == "SUCCEEDED"
    assert service.snapshot(second_job).status == "SUCCEEDED"
    assert service.snapshot(third_job).status == "SUCCEEDED"
    assert processor.events.count("warmup:start") == 1
    assert processor.events.count("warmup:end") == 1
    assert processor.events.index("warmup:end") < processor.events.index("process:first.png")
    assert processor.events.index("warmup:end") < processor.events.index("process:second.png")
    assert processor.events.index("warmup:end") < processor.events.index("process:third.png")


class FailingWarmupProcessor:
    def __init__(self) -> None:
        self.process_calls: list[str] = []

    async def warmup(self) -> None:
        raise RuntimeError("model warmup failed")

    async def process(self, file_bytes: bytes, filename: str, doc_type: str) -> dict[str, Any]:
        self.process_calls.append(filename)
        return successful_raw_result(filename)


def test_warmup_failure_fails_job_without_processing() -> None:
    processor = FailingWarmupProcessor()
    service = LocalExecutionService(processor=processor)

    snapshot = asyncio.run(service.run_inline([document("a.png")]))

    assert snapshot.status == "FAILED"
    assert snapshot.error == "model warmup failed"
    assert processor.process_calls == []
