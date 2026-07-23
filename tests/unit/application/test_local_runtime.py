import pytest

from app.application.services.local_runtime import (
    InMemoryLocalJobStore,
    LocalConsumer,
    LocalDocument,
    LocalJobNotFoundError,
    LocalPublisher,
)


def test_dummy_consumer_and_publisher_do_not_need_external_services() -> None:
    store = InMemoryLocalJobStore()
    job_id = LocalConsumer(store).submit([LocalDocument("a.png", "image/png", b"x", "INV")])

    LocalPublisher(store).publish(job_id, {"schema_version": "1.1.0"})

    snapshot = store.snapshot(job_id)
    assert snapshot.status == "SUCCEEDED"
    assert snapshot.result == {"schema_version": "1.1.0"}
    assert snapshot.total_documents == 1


def test_store_tracks_progress_and_partial_success() -> None:
    store = InMemoryLocalJobStore()
    job_id = store.create([LocalDocument("a.png", "image/png", b"x", "INV"), LocalDocument("b.png", "image/png", b"y", "INV")])

    store.start(job_id)
    store.document_finished(job_id)
    store.document_finished(job_id, failed=True)
    store.complete(job_id, {"schema_version": "1.1.0"})

    snapshot = store.snapshot(job_id)
    assert snapshot.status == "PARTIAL_SUCCESS"
    assert snapshot.completed_documents == 2
    assert snapshot.total_documents == 2


def test_store_records_failure_state() -> None:
    store = InMemoryLocalJobStore()
    job_id = store.create([])

    store.start(job_id)
    store.fail(job_id, "processor unavailable")

    snapshot = store.snapshot(job_id)
    assert snapshot.status == "FAILED"
    assert snapshot.error == "processor unavailable"
    assert snapshot.result is None


def test_store_raises_explicit_error_for_unknown_job() -> None:
    store = InMemoryLocalJobStore()

    with pytest.raises(LocalJobNotFoundError, match="missing-job"):
        store.snapshot("missing-job")
