# Local End-to-End Model Validation Design

**Status:** approved for planning

## Purpose

Validate the document AI pipeline and model quality locally before connecting a real RabbitMQ broker, PostgreSQL database, or image/file server. The Streamlit testing UI, automated benchmark runner, and JSON export must exercise one shared processing path so a result inspected manually is produced by the same code that is measured automatically.

## Scope

The phase accepts a local file or folder of images/PDFs, converts it to pages, runs OCR, field extraction, YOLO detection, barcode decoding, quality/color inspection, confidence scoring, and business validation. It returns a canonical JSON result with page details and a folder/document summary, displays that result and progress in Streamlit, and produces reproducible evaluation reports.

RabbitMQ and PostgreSQL remain unconnected. Their existing production adapters are retained behind explicit interfaces; local no-op or in-memory implementations supply the same request/job/result boundary. No broker, database, Docker environment, migration, remote URL fetch, retry delivery, or external image-server test is part of this phase.

## Architecture

`Streamlit upload` and `benchmark CLI` both call a new local execution facade. The facade accepts local files, creates a local job, runs one shared page pipeline with bounded document/page concurrency, builds the canonical result envelope, validates it against a versioned JSON schema, and records progress plus timing. Streamlit polls job state from the local runtime and renders the completed result; it does not contain a separate OCR/detection/extraction pipeline.

The execution facade depends on existing OCR, YOLO, barcode, field extraction, reasoning, confidence, quality, and business-rule services. It returns only application/domain data and depends on a `JobStore` and `ResultSink` protocol. In this phase, those protocols use an in-memory store and JSON-file result sink. Existing RabbitMQ consumer/publisher and PostgreSQL repositories remain production adapters only and must not connect while local mode is selected.

## Canonical Result Contract

One result builder owns the externally visible shape. It contains a correlation/job ID, source file metadata, per-page timings, OCR raw text/blocks, extracted fields and candidates, financial final total plus taxes/discounts/adjustments, YOLO objects with class ID, class name, confidence, pixel bbox, normalized bbox, barcode decode attempts and final value, quality/color evidence, confidence components, validation results, errors, and semantic notes.

The envelope has document/file and folder summary levels. `invoice_number` is nullable: a missing number is represented as `null` with a `NOT_FOUND` field status and must not alone force `NG`. `OK` requires both the selected business rules and confidence at least 85; otherwise the result is `NG`. Confidence remains a heuristic display/decision signal in this phase, not a calibrated probability claim.

## Evaluation and Acceptance Gates

Field evaluation uses all 135 entries in `dataset groundtruth/ground_truth.json`. For `document_number`, `transaction_amount`, and `transaction_date`, normalized exact-match accuracy is reported independently. Each field must reach at least 85%. The report includes matched, mismatched, missing-prediction, and unexpected-prediction examples mapped to source file names.

YOLO evaluation uses `dataset yolo/val/images` and paired labels. The model class map is read from the loaded model, never hard-coded. For barcode, stamp, materai, and signature, report per-class and aggregate precision, recall, AP@0.50, and mAP@0.50. The acceptance gate is at least 90% AP@0.50 for every required class and at least 90% aggregate mAP@0.50. A missing or ambiguous required class mapping fails the run rather than silently scoring incorrect labels.

Barcode decoding has no value ground truth and color checking has no labels. Both appear in the JSON and Streamlit review output, together with a clear `not_evaluated` status in automated reports. They are not pass/fail gates until labels exist.

## Concurrency and UI Behavior

Local processing uses fixed, configurable semaphore limits for documents and pages. CPU/GPU model calls remain bounded to prevent memory exhaustion. The UI starts a persisted local job and periodically refreshes progress, so it remains interactive during a long upload or folder run. A job exposes queued, running, succeeded, failed, and partial-result states; each page failure is included in the final envelope without discarding successful pages.

The benchmark runner uses the same facade but waits for completion. It writes a timestamped, machine-readable JSON report and a compact console summary with latency percentiles, throughput, the field metrics, YOLO metrics, and acceptance-gate outcome.

## Testing

Unit tests cover contract construction and schema validation, optional invoice behavior, local job state/progress, bounded concurrency, normalizers, and metric calculations. Integration tests use deterministic fake OCR/YOLO/barcode adapters to prove Streamlit-facing local execution and benchmark execution invoke the same facade and produce the same canonical envelope. Dataset-backed evaluation tests are opt-in and skip with an explicit message when model weights or optional native dependencies are unavailable.

## Out of Scope

- Connecting to, publishing to, or consuming from RabbitMQ.
- Connecting to or finalizing PostgreSQL tables/migrations.
- Fetching attachments from HTTP/image-file servers.
- Production throughput claims for 1,000–8,000 documents/day.
- Training or relabeling YOLO, barcode, or color datasets.
- Treating heuristic confidence as statistically calibrated confidence.
