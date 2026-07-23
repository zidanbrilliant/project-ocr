"""Background execution for documents supplied directly by local clients."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from app.application.services.local_runtime import (
    InMemoryLocalJobStore,
    LocalConsumer,
    LocalDocument,
    LocalJobSnapshot,
    LocalPublisher,
)
from app.application.services.result_builder import (
    build_result_envelope,
    build_result_payload,
)
from app.interfaces.schemas.local_result_contract import validate_local_result
from app.shared.config.settings import settings


class LocalExecutionService:
    """Run local documents without broker, database, or file-client dependencies."""

    def __init__(
        self,
        processor: Any | None = None,
        store: InMemoryLocalJobStore | None = None,
    ) -> None:
        if processor is None:
            from scripts.direct_processor import DirectProcessor

            processor = DirectProcessor()
        self._processor = processor
        self._store = store or InMemoryLocalJobStore()
        self._consumer = LocalConsumer(self._store)
        self._publisher = LocalPublisher(self._store)
        self._warmup_lock = Lock()
        self._warmup_future: Future[None] | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=settings.LOCAL_MAX_ACTIVE_JOBS,
            thread_name_prefix="local-document-job",
        )

    def submit(self, documents: list[LocalDocument]) -> str:
        documents = list(documents)
        job_id = self._consumer.submit(documents)
        self._executor.submit(self._run_in_thread, job_id, documents)
        return job_id

    def snapshot(self, job_id: str) -> LocalJobSnapshot:
        return self._store.snapshot(job_id)

    async def run_inline(self, documents: list[LocalDocument]) -> LocalJobSnapshot:
        documents = list(documents)
        job_id = self._consumer.submit(documents)
        return await self._run_job(job_id, documents)

    def _run_in_thread(self, job_id: str, documents: list[LocalDocument]) -> None:
        asyncio.run(self._run_job(job_id, documents))

    async def _run_job(
        self,
        job_id: str,
        documents: list[LocalDocument],
    ) -> LocalJobSnapshot:
        started_at = time.monotonic()
        self._store.start(job_id)
        semaphore = asyncio.Semaphore(settings.MAX_PARALLEL_DOCUMENTS)

        async def process_one(document: LocalDocument) -> dict[str, Any]:
            try:
                async with semaphore:
                    raw = await self._processor.process(
                        document.content,
                        document.name,
                        document.doc_type,
                    )
                    if raw.get("error"):
                        raise RuntimeError(str(raw["error"]))
                    result_document = build_result_payload(
                        raw,
                        document.name,
                        document.content_type,
                        len(document.content),
                        raw["processing_time_ms"],
                    )["documents"][0]
            except Exception:
                self._store.document_finished(job_id, failed=True)
                raise
            self._store.document_finished(job_id)
            return result_document

        try:
            await self._warmup_processor_once()
            settled = await asyncio.gather(
                *(process_one(document) for document in documents),
                return_exceptions=True,
            )
            result_documents, errors = self._documents_from_settled(
                settled,
                documents,
            )
            completion_status = (
                "FAILED"
                if errors and len(errors) == len(result_documents)
                else "PARTIAL_SUCCESS"
                if errors
                else "SUCCEEDED"
            )
            envelope = build_result_envelope(
                result_documents,
                int((time.monotonic() - started_at) * 1000),
                status=completion_status,
                errors=errors,
                queue_id=job_id,
                correlation_id=job_id,
                job_id=job_id,
                source_system="streamlit-local",
            )
            self._publisher.publish(job_id, validate_local_result(envelope))
        except Exception as error:
            self._store.fail(job_id, str(error))
        return self._store.snapshot(job_id)

    async def _warmup_processor_once(self) -> None:
        with self._warmup_lock:
            future = self._warmup_future
            is_owner = future is None
            if future is None:
                future = self._warmup_future = Future()

        if not is_owner:
            await asyncio.wrap_future(future)
            return

        try:
            warmup = getattr(self._processor, "warmup", None)
            if warmup is not None:
                await warmup()
        except BaseException as error:
            future.set_exception(error)
            raise
        else:
            future.set_result(None)

    @staticmethod
    def _documents_from_settled(
        settled: list[Any],
        documents: list[LocalDocument],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        result_documents: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for index, (result, document) in enumerate(zip(settled, documents, strict=True)):
            if not isinstance(result, BaseException):
                result_documents.append(result)
                continue

            error = {
                "document_name": document.name,
                "stage": "PROCESSING",
                "message": str(result),
            }
            errors.append(error)
            result_documents.append(
                {
                    "document_id": f"LOCAL-DOC-{index + 1:03d}",
                    "document_name": document.name,
                    "document_type": document.doc_type,
                    "document_result": "NG",
                    "processing_status": "FAILED",
                    "processing_result": "INTERNAL_ERROR",
                    "page_count": 0,
                    "file_information": {
                        "file_name": document.name,
                        "content_type": document.content_type,
                        "file_size_bytes": len(document.content),
                    },
                    "pages": [],
                    "errors": [error],
                }
            )
        return result_documents, errors
