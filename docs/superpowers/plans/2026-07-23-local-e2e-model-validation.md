# Local End-to-End Model Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make Streamlit testing use one non-blocking local document-processing service with validated detailed JSON and repeatable field/YOLO acceptance reports.

**Architecture:** DirectProcessor remains the only local OCR, YOLO, barcode, extraction, validation, and confidence pipeline. A LocalExecutionService wraps it with an in-memory consumer, publisher, job store, and bounded concurrency; both Streamlit and the benchmark call this service. RabbitMQ, PostgreSQL, and remote image-file retrieval remain disabled and are not connected.

**Tech Stack:** Python 3.11+, asyncio, concurrent.futures, Pydantic v2, Streamlit, Ultralytics YOLO, Pillow, pytest.

## Global Constraints

- Keep ENABLE_RABBITMQ=false and ENABLE_DATABASE=false for this phase. Do not import a RabbitMQ connection, SQLAlchemy session, or HTTP file client from local execution code.
- Add no dependency. Pydantic, Pillow, Streamlit, and Ultralytics already exist.
- Never stage, rename, delete, or edit the user-owned datasets, model weights, or benchmark_report_35.json.
- A missing invoice number is null with status NOT_FOUND and is not by itself NG.
- Result is exactly OK only when business validation passes and confidence is at least 85; otherwise it is exactly NG.
- Field gates: document_number, transaction_amount, and transaction_date each need normalized exact-match >= 0.85.
- YOLO gates: barcode, materai, signature, and stamp each need AP@0.50 >= 0.90 and aggregate mAP@0.50 >= 0.90.
- Barcode decode and color are present in UI/JSON as not_evaluated until labels exist; they are not gates.
- Preserve response schema version 1.1.0 and add fields only.

---

## File Structure

| File | Responsibility |
| --- | --- |
| app/interfaces/schemas/local_result_contract.py | Pydantic validation boundary for the canonical local envelope. |
| app/application/services/local_runtime.py | In-memory job store and dummy consumer/publisher; no I/O. |
| app/application/services/local_execution_service.py | Background submission, bounded processing, progress, and canonical result publication. |
| app/application/services/model_evaluation_service.py | Field normalization, YOLO label parsing, IoU/AP metrics, and gates. |
| app/application/services/result_builder.py | Correlation/job metadata and semantic per-page notes. |
| app/infrastructure/detection/yolo_adapter.py | Read-only model class-map access. |
| scripts/direct_processor.py | Sole local AI pipeline, with Streamlit database persistence removed. |
| scripts/result_adapter.py | UI projection from the canonical envelope only. |
| scripts/upload_app.py | Streamlit submit/poll UI. |
| scripts/benchmark_pipeline.py | CLI report using the shared local execution path. |
| tests/unit/application/test_local_result_contract.py | Contract and optional-invoice tests. |
| tests/unit/application/test_local_runtime.py | Dummy message/job lifecycle tests. |
| tests/unit/application/test_local_execution_service.py | Concurrency and partial-result tests. |
| tests/unit/application/test_model_evaluation_service.py | Field and YOLO metric tests. |
| tests/integration/test_local_e2e.py | Deterministic facade test used by UI/benchmark integration. |

## Task 1: Freeze the Local Result Contract and Invoice Policy

**Files:**
- Create: app/interfaces/schemas/local_result_contract.py
- Modify: app/application/services/result_builder.py:31-181
- Modify: app/domain/services/business_rule_evaluator.py:14-45
- Modify: app/shared/config/settings.py:37-70
- Test: tests/unit/application/test_local_result_contract.py
- Test: tests/unit/application/test_result_builder.py
- Test: tests/unit/domain/test_business_rules.py

**Interfaces:**
- Produces: validate_local_result(payload: dict[str, Any]) -> dict[str, Any].
- Produces: build_result_envelope(..., correlation_id: str = "", job_id: str = "") -> dict[str, Any].

- [ ] **Step 1: Write the failing contract and policy tests**

    Add a smallest-valid-envelope fixture, assert missing correlation_id raises ValidationError, assert a bbox has exactly four coordinates, and assert a null invoice does not create INV-R001 when invoice policy is false.

    from pydantic import ValidationError

    def test_local_result_requires_correlation_id() -> None:
        with pytest.raises(ValidationError):
            validate_local_result({"header": {}, "documents": []})

    def test_invoice_number_is_optional_when_policy_is_false() -> None:
        result = BusinessRuleEvaluator(RuleConfig(require_invoice_number=False)).validate_invoice(
            OCRResult(invoice_number=None), [], 1_000, 90
        )
        assert "INV-R001" not in {item.rule_id for item in result.failed_rules}

- [ ] **Step 2: Run tests to verify they fail**

    Run: pytest tests/unit/application/test_local_result_contract.py tests/unit/domain/test_business_rules.py -v

    Expected: FAIL because the contract and REQUIRE_INVOICE_NUMBER setting do not exist.

- [ ] **Step 3: Implement the minimal contract and additive builder fields**

    Create Pydantic models with ConfigDict(extra="allow") for header, document/page essentials, and bbox. Require schema version 1.1.0, correlation ID, non-empty document name/ID, page number >= 1, and result values OK or NG. Return model_dump(mode="json") from validate_local_result.

    class ResultHeader(BaseModel):
        model_config = ConfigDict(extra="allow")
        correlation_id: str = Field(min_length=1)
        overall_result: Literal["OK", "NG"]
        processing_status: str

    class ResultEnvelope(BaseModel):
        model_config = ConfigDict(extra="allow")
        schema_version: Literal["1.1.0"]
        header: ResultHeader
        documents: list[dict[str, Any]]

    Add REQUIRE_INVOICE_NUMBER: bool = False, LOCAL_MAX_ACTIVE_JOBS: int = 1, FIELD_EXACT_MATCH_THRESHOLD: float = 0.85, and YOLO_AP50_THRESHOLD: float = 0.90 to Settings. Pass REQUIRE_INVOICE_NUMBER when creating default RuleConfig. Extend build_result_envelope with keyword-only correlation_id and job_id, place them in header and processing, and add a deterministic page ai_note based on OCR, detections, barcode, and color evidence.

- [ ] **Step 4: Run focused regression tests**

    Run: pytest tests/unit/application/test_local_result_contract.py tests/unit/application/test_result_builder.py tests/unit/domain/test_business_rules.py -v

    Expected: PASS. The JSON validator rejects malformed required metadata, while missing invoice number remains a valid extraction state.

- [ ] **Step 5: Commit**

    git add app/interfaces/schemas/local_result_contract.py app/application/services/result_builder.py app/domain/services/business_rule_evaluator.py app/shared/config/settings.py tests/unit/application/test_local_result_contract.py tests/unit/application/test_result_builder.py tests/unit/domain/test_business_rules.py
    git commit -m "feat: define local result contract and invoice policy"

## Task 2: Add Dummy Consumer, Publisher, and In-Memory Job State

**Files:**
- Create: app/application/services/local_runtime.py
- Test: tests/unit/application/test_local_runtime.py

**Interfaces:**
- Produces: LocalDocument(name: str, content_type: str, content: bytes, doc_type: str).
- Produces: LocalJobSnapshot(job_id: str, status: str, completed_documents: int, total_documents: int, result: dict[str, Any] | None, error: str | None).
- Produces: InMemoryLocalJobStore.create, snapshot, start, document_finished, fail, complete.
- Produces: LocalConsumer.submit(documents) -> str and LocalPublisher.publish(job_id, result) -> None.

- [ ] **Step 1: Write failing lifecycle tests**

    def test_dummy_consumer_and_publisher_do_not_need_external_services() -> None:
        store = InMemoryLocalJobStore()
        job_id = LocalConsumer(store).submit([LocalDocument("a.png", "image/png", b"x", "INV")])
        LocalPublisher(store).publish(job_id, {"schema_version": "1.1.0"})
        assert store.snapshot(job_id).status == "SUCCEEDED"

    Also test unknown ID, failure state, and progress count.

- [ ] **Step 2: Run tests to verify they fail**

    Run: pytest tests/unit/application/test_local_runtime.py -v

    Expected: FAIL because local_runtime does not exist.

- [ ] **Step 3: Implement the memory-only boundary**

    Use frozen dataclasses for LocalDocument and LocalJobSnapshot, a private mutable job record, and threading.RLock for state. LocalConsumer only creates a UUID job and returns it. LocalPublisher only stores a result and transitions the job; it has no URL, connection, retry, SQL, or message-broker dependency.

    class LocalPublisher:
        def __init__(self, store: InMemoryLocalJobStore) -> None:
            self._store = store

        def publish(self, job_id: str, result: dict[str, Any]) -> None:
            self._store.complete(job_id, result)

- [ ] **Step 4: Run lifecycle tests**

    Run: pytest tests/unit/application/test_local_runtime.py -v

    Expected: PASS with deterministic state transitions and no external calls.

- [ ] **Step 5: Commit**

    git add app/application/services/local_runtime.py tests/unit/application/test_local_runtime.py
    git commit -m "feat: add in-memory local job runtime"

## Task 3: Build One Background Execution Path

**Files:**
- Create: app/application/services/local_execution_service.py
- Modify: scripts/direct_processor.py:1-566
- Test: tests/unit/application/test_local_execution_service.py
- Test: tests/unit/test_direct_processor.py

**Interfaces:**
- Produces: LocalExecutionService.submit(documents: list[LocalDocument]) -> str.
- Produces: LocalExecutionService.snapshot(job_id: str) -> LocalJobSnapshot.
- Produces: async LocalExecutionService.run_inline(documents: list[LocalDocument]) -> LocalJobSnapshot.
- Consumes: DirectProcessor.process(file_bytes, filename, doc_type), result builder, contract validator, local runtime.

- [ ] **Step 1: Write failing bounded-concurrency tests**

    Use a fake processor that increments an active counter before await asyncio.sleep(0). Submit three documents with MAX_PARALLEL_DOCUMENTS=2. Assert max_active is 2, correlation ID equals job ID, one failed document produces PARTIAL_SUCCESS, and no PostgreSQL save method is called.

    @pytest.mark.asyncio
    async def test_run_inline_bounds_parallel_documents() -> None:
        processor = RecordingProcessor()
        service = LocalExecutionService(processor=processor)
        snapshot = await service.run_inline([document("a.png"), document("b.png"), document("c.png")])
        assert processor.max_active == 2
        assert snapshot.result["header"]["correlation_id"] == snapshot.job_id

- [ ] **Step 2: Run tests to verify they fail**

    Run: pytest tests/unit/application/test_local_execution_service.py -v

    Expected: FAIL because LocalExecutionService does not exist.

- [ ] **Step 3: Implement submit and shared async execution**

    submit creates the dummy-consumer job then schedules asyncio.run(self._run_job(...)) on a ThreadPoolExecutor whose max_workers is LOCAL_MAX_ACTIVE_JOBS; it returns immediately. run_inline creates the same job and awaits the same _run_job. In _run_job, use asyncio.Semaphore(settings.MAX_PARALLEL_DOCUMENTS), call DirectProcessor.process exactly once per file, transform each raw result through build_result_payload, gather with return_exceptions=True, build one envelope, validate it, and publish it.

    async def _run_job(self, job_id: str, documents: list[LocalDocument]) -> LocalJobSnapshot:
        semaphore = asyncio.Semaphore(settings.MAX_PARALLEL_DOCUMENTS)

        async def process_one(document: LocalDocument) -> dict[str, Any]:
            async with semaphore:
                raw = await self._processor.process(document.content, document.name, document.doc_type)
                return build_result_payload(
                    raw, document.name, document.content_type, len(document.content), raw["processing_time_ms"]
                )["documents"][0]

        settled = await asyncio.gather(*(process_one(item) for item in documents), return_exceptions=True)
        envelope = build_result_envelope(
            self._documents_from_settled(settled, documents),
            self._store.elapsed_ms(job_id),
            queue_id=job_id,
            correlation_id=job_id,
            job_id=job_id,
            source_system="streamlit-local",
        )
        self._publisher.publish(job_id, validate_local_result(envelope))
        return self._store.snapshot(job_id)

    Remove DirectProcessor._save_to_db and the ENABLE_DATABASE branch. Database persistence remains only in the production worker/orchestrator, so Streamlit never imports PostgreSQL repositories.

- [ ] **Step 4: Run service and direct-processor tests**

    Run: pytest tests/unit/application/test_local_execution_service.py tests/unit/test_direct_processor.py -v

    Expected: PASS. Existing PDF text fallback remains green.

- [ ] **Step 5: Commit**

    git add app/application/services/local_execution_service.py scripts/direct_processor.py tests/unit/application/test_local_execution_service.py tests/unit/test_direct_processor.py
    git commit -m "feat: run local documents as background jobs"

## Task 4: Update Streamlit to Submit and Poll Jobs

**Files:**
- Modify: scripts/upload_app.py:1-189 and 463-464
- Modify: scripts/result_adapter.py:21-112
- Test: tests/integration/test_local_e2e.py

**Interfaces:**
- Consumes: LocalExecutionService.submit, snapshot, and LocalJobSnapshot.result.
- Produces: normalize_result_envelope_for_ui(envelope: dict[str, Any]) -> list[dict[str, Any]].
- Streamlit must not call DirectProcessor.process directly.

- [ ] **Step 1: Write the failing UI-facing integration test**

    def test_ui_adapter_reads_completed_canonical_envelope() -> None:
        envelope = complete_envelope_with_two_documents()
        results = normalize_result_envelope_for_ui(envelope)
        assert [item["document"]["file_name"] for item in results] == ["a.png", "b.png"]
        assert results[0]["rabbitmq_preview"] is envelope

    Add a static source assertion that upload_app has no await processor.process call.

- [ ] **Step 2: Run test to verify it fails**

    Run: pytest tests/integration/test_local_e2e.py -v

    Expected: FAIL because the current UI converts a separate raw result.

- [ ] **Step 3: Implement synchronous submit/poll UI**

    Make main_ui synchronous. Cache LocalExecutionService with st.cache_resource. On Process, convert uploads to LocalDocument, submit once, save local_job_id in session state, and rerun immediately. On later reruns, query the snapshot. Show QUEUED/RUNNING progress and a Refresh progress button; show completed documents using normalize_result_envelope_for_ui; show FAILED error without destroying the stored state.

    @st.cache_resource(show_spinner=False)
    def get_local_service() -> LocalExecutionService:
        return LocalExecutionService(processor=get_processor())

    if st.button("Process", type="primary", disabled=not uploaded):
        docs = [LocalDocument(item.name, item.type or "", item.getvalue(), doc_type) for item in uploaded]
        st.session_state.local_job_id = get_local_service().submit(docs)
        st.rerun()

    snapshot = get_local_service().snapshot(st.session_state.local_job_id)
    if snapshot.status in {"QUEUED", "RUNNING"}:
        st.info(f"Processing {snapshot.completed_documents}/{snapshot.total_documents} document(s).")
        if st.button("Refresh progress"):
            st.rerun()
        return

    Replace normalize_pipeline_result_for_ui with an envelope-only adapter; it must display the exact result the dummy publisher stored and must not rebuild header, summary, or document JSON.

- [ ] **Step 4: Run UI and service regression tests**

    Run: pytest tests/integration/test_local_e2e.py tests/unit/application/test_local_execution_service.py tests/unit/application/test_result_builder.py -v

    Expected: PASS. submit returns before fake processing finishes, and displayed JSON is the published canonical envelope.

- [ ] **Step 5: Commit**

    git add scripts/upload_app.py scripts/result_adapter.py tests/integration/test_local_e2e.py
    git commit -m "feat: make streamlit poll local jobs"

## Task 5: Add Field Accuracy Evaluation and the 85% Gate

**Files:**
- Create: app/application/services/model_evaluation_service.py
- Modify: scripts/benchmark_pipeline.py:1-175
- Test: tests/unit/application/test_model_evaluation_service.py
- Test: tests/unit/test_benchmark_pipeline.py

**Interfaces:**
- Produces: normalize_field_value(name: str, value: Any) -> str | Decimal | None.
- Produces: field_gate(metrics: dict[str, dict[str, Any]], threshold: float) -> dict[str, Any].
- Consumes: dataset groundtruth/ground_truth.json through the existing CLI loader and LocalExecutionService.run_inline.

- [ ] **Step 1: Write failing field-metric tests**

    Cover invoice trimming/case normalization, Decimal-safe amount comparison plus currency, ISO-date equality, null-to-null matching, mismatch examples, and failure when any independent field score is below 0.85.

    def test_field_gate_requires_each_core_field() -> None:
        report = field_gate(
            {"document_number": {"evaluated": 10, "exact_match_rate": 0.85},
             "transaction_amount": {"evaluated": 10, "exact_match_rate": 0.84},
             "transaction_date": {"evaluated": 10, "exact_match_rate": 1.00}},
            0.85,
        )
        assert report["passed"] is False
        assert report["failed_fields"] == ["transaction_amount"]

- [ ] **Step 2: Run tests to verify they fail**

    Run: pytest tests/unit/application/test_model_evaluation_service.py tests/unit/test_benchmark_pipeline.py -v

    Expected: FAIL because field gate and normalization have not been extracted.

- [ ] **Step 3: Implement field evaluation and route benchmark through LocalExecutionService**

    Keep JSON/JSONL loading in scripts/benchmark_pipeline.py. Move exact-match, candidate recall, mismatch examples, and field-gate construction into model_evaluation_service. Replace DirectProcessor construction in benchmark with LocalExecutionService.run_inline so CLI and UI use identical processing. Preserve per-file file_name, expected, actual, checks, duration_ms, and error; only include raw OCR trace when --include-trace is set.

    CORE_FIELDS = ("document_number", "transaction_amount", "transaction_date")

    def field_gate(metrics: dict[str, dict[str, Any]], threshold: float) -> dict[str, Any]:
        failed = [
            field for field in CORE_FIELDS
            if metrics[field]["evaluated"] == 0 or metrics[field]["exact_match_rate"] < threshold
        ]
        return {"passed": not failed, "failed_fields": failed, "threshold": threshold}

- [ ] **Step 4: Run evaluator and benchmark tests**

    Run: pytest tests/unit/application/test_model_evaluation_service.py tests/unit/test_benchmark_pipeline.py -v

    Expected: PASS. Report now includes field_acceptance with threshold, failed_fields, and exact-match rates.

- [ ] **Step 5: Commit**

    git add app/application/services/model_evaluation_service.py scripts/benchmark_pipeline.py tests/unit/application/test_model_evaluation_service.py tests/unit/test_benchmark_pipeline.py
    git commit -m "feat: add field accuracy acceptance gate"

## Task 6: Add YOLO Validation and the 90% Gate

**Files:**
- Modify: app/application/services/model_evaluation_service.py
- Modify: app/infrastructure/detection/yolo_adapter.py:16-155
- Modify: scripts/benchmark_pipeline.py:109-175
- Test: tests/unit/application/test_model_evaluation_service.py
- Test: tests/unit/test_yolo_adapter.py
- Test: tests/unit/test_benchmark_pipeline.py

**Interfaces:**
- Produces: YOLOAdapter.class_map -> dict[int, str].
- Produces: evaluate_yolo_validation(detector, dataset_root: Path, required_labels: set[str]) -> dict[str, Any].
- Produces: iou_xyxy(left: Sequence[float], right: Sequence[float]) -> float.

- [ ] **Step 1: Write failing YOLO metric tests**

    Use a fake detector with a class map and normalized xyxy boxes. Test perfect detection, false positive, missed target, IoU 0.49 miss, absent required mapping, and an AP 0.89 class gate failure.

    def test_yolo_gate_fails_when_one_class_is_below_threshold() -> None:
        report = yolo_gate(
            {"barcode": {"ap50": 0.99}, "materai": {"ap50": 0.89},
             "signature": {"ap50": 0.95}, "stamp": {"ap50": 0.96}},
            0.90,
        )
        assert report["failed_classes"] == ["materai"]

- [ ] **Step 2: Run tests to verify they fail**

    Run: pytest tests/unit/application/test_model_evaluation_service.py tests/unit/test_yolo_adapter.py -v

    Expected: FAIL because class_map and AP@0.50 logic do not exist.

- [ ] **Step 3: Implement class-map validation and AP@0.50**

    Add YOLOAdapter.class_map returning a copy of the loaded model names map, or empty dict before warmup. Parse YOLO labels as class_id, center_x, center_y, width, height and convert to normalized xyxy. Per class, sort predictions by confidence, greedily match one same-file unmatched target at IoU >= 0.50, calculate precision/recall, and calculate 101-point interpolated AP. Fail clearly if required labels barcode, materai, signature, stamp cannot be mapped exactly once from the loaded model.

    def iou_xyxy(a: Sequence[float], b: Sequence[float]) -> float:
        left, top = max(a[0], b[0]), max(a[1], b[1])
        right, bottom = min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        union = area(a) + area(b) - intersection
        return intersection / union if union else 0.0

- [ ] **Step 4: Extend CLI and run all metric tests**

    Add --yolo-dataset-root PATH and --require-yolo-gate. When root is supplied, warm the same detector used by local execution and evaluate only PATH/val. Include yolo_validation.class_map, per_class precision/recall/ap50, aggregate_map50, evaluated_images, skipped_images, and acceptance. With --require-yolo-gate, write the report then exit 2 when either requested field or YOLO gate fails.

    Run: pytest tests/unit/application/test_model_evaluation_service.py tests/unit/test_yolo_adapter.py tests/unit/test_benchmark_pipeline.py -v

    Expected: PASS without model weights in unit tests.

- [ ] **Step 5: Commit**

    git add app/application/services/model_evaluation_service.py app/infrastructure/detection/yolo_adapter.py scripts/benchmark_pipeline.py tests/unit/application/test_model_evaluation_service.py tests/unit/test_yolo_adapter.py tests/unit/test_benchmark_pipeline.py
    git commit -m "feat: report yolo validation acceptance"

## Task 7: Verify and Document the Complete Local Flow

**Files:**
- Modify: README.md:1-67
- Modify: .gitignore:1-25 only if the team confirms dataset yolo must be untracked
- Test: tests/integration/test_local_e2e.py

**Interfaces:**
- Consumes: all Task 1-6 interfaces.
- Produces: a documented CLI command that writes one report before returning a gate result.

- [ ] **Step 1: Write final partial-success integration test**

    @pytest.mark.asyncio
    async def test_local_e2e_keeps_good_document_when_one_fails() -> None:
        snapshot = await LocalExecutionService(processor=MixedProcessor()).run_inline(
            [document("good.png"), document("bad.png")]
        )
        assert snapshot.status == "PARTIAL_SUCCESS"
        assert snapshot.result["summary"]["total_documents"] == 2
        assert snapshot.result["header"]["correlation_id"] == snapshot.job_id

    Assert page notes, barcode/color not_evaluated markers, validation, confidence, and JSON contract survive the UI adapter.

- [ ] **Step 2: Run integration test**

    Run: pytest tests/integration/test_local_e2e.py -v

    Expected: PASS after Tasks 1-6. If it fails, repair the relevant earlier task before documentation changes.

- [ ] **Step 3: Update README with exact local commands**

    Document Streamlit as a local background-job tester, not RabbitMQ/PostgreSQL integration. Add:

    streamlit run scripts/upload_app.py
    python scripts/benchmark_pipeline.py "dataset groundtruth" --ground-truth "dataset groundtruth/ground_truth.json" --yolo-dataset-root "dataset yolo" --output artifacts/benchmark-local.json --require-yolo-gate

    Explain that barcode decode and color are output-only until labels exist. Do not alter .gitignore unless the team explicitly asks to ignore dataset yolo; never stage it either way.

- [ ] **Step 4: Run complete verification**

    Run: python -m compileall app scripts

    Expected: exit code 0.

    Run: pytest -q

    Expected: PASS. Tests needing weights/native dependencies must be explicitly SKIPPED, never silently passed.

    Run only when model weights/runtime are available:

    python scripts/benchmark_pipeline.py "dataset groundtruth" --ground-truth "dataset groundtruth/ground_truth.json" --yolo-dataset-root "dataset yolo" --output artifacts/benchmark-local.json --require-yolo-gate

    Expected: report has field_acceptance and yolo_validation; exit 0 means all 85%/90% gates pass, exit 2 means report written but a requested gate failed.

- [ ] **Step 5: Commit**

    git add README.md tests/integration/test_local_e2e.py
    git commit -m "docs: document local e2e validation workflow"

## Plan Self-Review

**Spec coverage:** Tasks 1 and 3 provide one detailed canonical JSON, nullable invoice, per-page notes, confidence, validation, and no external persistence. Tasks 2-4 supply the requested dummy consumer/publisher, local job state, bounded parallel processing, and non-blocking Streamlit interaction. Tasks 5-6 enforce the agreed 85% field and 90% YOLO gates. Task 7 verifies and documents the workflow.

**Out of scope by design:** RabbitMQ connections, PostgreSQL table/migration decisions, image-server URLs, production load claims, YOLO training, barcode-value labels, and color labels. These need infrastructure or ground truth that is intentionally deferred.

**Consistency check:** LocalDocument is the single service input, LocalJobSnapshot is the single job-state output, validate_local_result is the sole external JSON boundary, and YOLOAdapter.class_map is the only class-ID mapping source. No task depends on an interface that a previous task does not define.
