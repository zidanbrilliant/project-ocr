"""Memory-only job state for local document execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable, Literal
from uuid import uuid4


@dataclass(frozen=True)
class LocalDocument:
    name: str
    content_type: str
    content: bytes
    doc_type: str


@dataclass(frozen=True)
class LocalJobSnapshot:
    job_id: str
    status: str
    completed_documents: int
    total_documents: int
    result: dict[str, Any] | None
    error: str | None


class LocalJobNotFoundError(LookupError):
    """Raised when a local job ID is not held by this store."""


class LocalJobStateError(RuntimeError):
    """Raised when an operation does not match the job's current state."""


@dataclass
class _LocalJobRecord:
    status: str
    total_documents: int
    completed_documents: int = 0
    failed_documents: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None


class InMemoryLocalJobStore:
    """Thread-safe, process-local state for local execution jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, _LocalJobRecord] = {}
        self._lock = RLock()

    def create(self, documents: Iterable[LocalDocument]) -> str:
        job_id = str(uuid4())
        total_documents = len(list(documents))
        with self._lock:
            self._jobs[job_id] = _LocalJobRecord(status="PENDING", total_documents=total_documents)
        return job_id

    def snapshot(self, job_id: str) -> LocalJobSnapshot:
        with self._lock:
            record = self._record(job_id)
            return LocalJobSnapshot(
                job_id=job_id,
                status=record.status,
                completed_documents=record.completed_documents,
                total_documents=record.total_documents,
                result=deepcopy(record.result),
                error=record.error,
            )

    def start(self, job_id: str) -> None:
        with self._lock:
            record = self._record(job_id)
            self._require_status(job_id, record, "PENDING")
            record.status = "RUNNING"

    def document_finished(self, job_id: str, *, failed: bool = False) -> None:
        with self._lock:
            record = self._record(job_id)
            self._require_status(job_id, record, "RUNNING")
            if record.completed_documents >= record.total_documents:
                raise LocalJobStateError(f"job '{job_id}' has no unfinished documents")
            record.completed_documents += 1
            if failed:
                record.failed_documents += 1

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            record = self._record(job_id)
            self._require_status(job_id, record, "PENDING", "RUNNING")
            record.status = "FAILED"
            record.error = error

    def complete(
        self,
        job_id: str,
        result: dict[str, Any],
        *,
        status: Literal["SUCCEEDED", "PARTIAL_SUCCESS"] | None = None,
    ) -> None:
        with self._lock:
            record = self._record(job_id)
            self._require_status(job_id, record, "PENDING", "RUNNING")
            record.result = deepcopy(result)
            record.status = status or ("PARTIAL_SUCCESS" if record.failed_documents else "SUCCEEDED")

    def _record(self, job_id: str) -> _LocalJobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise LocalJobNotFoundError(f"unknown local job '{job_id}'") from error

    @staticmethod
    def _require_status(job_id: str, record: _LocalJobRecord, *allowed: str) -> None:
        if record.status not in allowed:
            allowed_statuses = ", ".join(allowed)
            raise LocalJobStateError(
                f"job '{job_id}' is {record.status}; expected one of: {allowed_statuses}"
            )


class LocalConsumer:
    """Creates local jobs without a broker or external connection."""

    def __init__(self, store: InMemoryLocalJobStore) -> None:
        self._store = store

    def submit(self, documents: Iterable[LocalDocument]) -> str:
        return self._store.create(documents)


class LocalPublisher:
    """Completes local jobs without a network publisher."""

    def __init__(self, store: InMemoryLocalJobStore) -> None:
        self._store = store

    def publish(self, job_id: str, result: dict[str, Any]) -> None:
        self._store.complete(job_id, result)
