# AI Invoice Verification Agent Service — Architecture

> **Version:** 2.1.0 | **Python:** 3.11 | **Last Updated:** 2026-07-13

---

## 1. Overview

Multi-document, multi-page AI verification service for Toyota invoices/delivery notes. One RabbitMQ message = one business case = one job with N documents, each with M pages.

| Component | Tech |
|-----------|------|
| OCR | pypdf → EasyOCR (GPU) |
| Detection | Ultralytics YOLO (GPU batch) |
| Barcode | zxing-cpp → pyzbar → OpenCV |
| Message broker | RabbitMQ (aio-pika) |
| Database | PostgreSQL 16 (SQLAlchemy async) |
| API | FastAPI |
| Local UI | Streamlit |

---

## 2. Directory Structure

```
app/
├── domain/          # No framework deps
│   ├── entities/    # AIJob, OCRResult, DetectionResult, NormalizedJobRequest, etc.
│   ├── value_objects/
│   └── services/    # BusinessRuleEvaluator, ConfidencePolicy, RemarkPolicy
├── application/     # Orchestration + DTOs + use cases
│   ├── dto/         # InputPayloadDTO, RequestNormalizer
│   ├── services/    # AIPipelineOrchestrator, FieldExtraction, ConfidenceScoring
│   ├── use_cases/   # GetJobStatus, GetJobResult, Reprocess
│   └── commands/    # ReprocessJobCommand
├── infrastructure/  # Adapters
│   ├── database/    # SQLAlchemy models (21 tables), repos, migrations
│   ├── rabbitmq/    # Connection, consumer, publisher, outbox, retry, topology
│   ├── storage/     # ImageServerClient, TempFileManager
│   ├── barcode/     # ZXing → Pyzbar → OpenCV fallback chain
│   ├── detection/   # YOLOAdapter, DetectionMapper (pixel/normalized/pdf bbox)
│   ├── ocr/         # DocumentOCR (pypdf + EasyOCR), OCRFallbackChain
│   └── document_converter/  # Validator, PDFRenderer, ImagePreprocessor, WordConverter
├── interfaces/      # FastAPI routes: health, jobs, models, metrics
├── workers/         # WorkerMain → JobProcessor → AIPipelineOrchestrator
└── shared/          # Config, constants, exceptions, logging, utils
```

---

## 3. Flow

```
RabbitMQ → InvoiceRequestConsumer → JobProcessor → AIPipelineOrchestrator
                                                           │
                          ┌────────────────────────────────┼────────────────────────────┐
                          ▼                                ▼                            ▼
                    normalize_request()           _process_job()                  outbox_publisher
                    (legacy / batch)             │                                   (SKIP LOCKED loop)
                          │                     ├── doc[0] (parallel) ─┬── page[0] (parallel)
                          │                     │                      ├── page[1]
                          │                     │                      └── page[N]
                          │                     ├── doc[1] (parallel)  ─── YOLO batch
                          │                     └── doc[N]               OCR + barcode per page
                          │                     │
                          ▼                     ▼
                NormalizedJobRequest      DocumentProcessingResult[]
                          │                     │
                          └── sort by document_index → aggregate → final_result + outbox_event
```

Key properties:
- **Bounded concurrency**: `MAX_PARALLEL_DOCUMENTS` semaphore for documents, `MAX_PARALLEL_PAGES` for pages
- **YOLO batch**: `detect_batch()` across all pages in one GPU call, retry with larger input if empty
- **Error isolation**: one page fail → other pages continue; one document fail → other documents continue
- **Deterministic output**: documents sorted by `document_index`, pages by `page_index`

---

## 4. Request Formats

### Legacy (single-doc)
```json
{"DOC_NO": "INV-001", "DOC_TYPE": "INV", "PATH_FILE": "https://...", ...}
```

### Batch (multi-doc)
```json
{
  "message_id": "MSG-001", "queue_no": "AIQ-001",
  "source_system": "VISION",
  "business_context": {"entity_type": "PAYMENT_VOUCHER", "entity_id": "PV-001"},
  "documents": [
    {"document_id": "DOC-001", "document_index": 0, "document_type": "INVOICE",
     "file": {"file_name": "inv.pdf", "file_url": "https://..."}},
    {"document_id": "DOC-002", "document_index": 1, "document_type": "DELIVERY_NOTE", ...}
  ]
}
```

Auto-detected by `RequestNormalizer`. Internally always uses `NormalizedJobRequest`.

---

## 5. Database — 21 Tables

| Table | Purpose | Parent FK |
|-------|---------|-----------|
| `ai_inbox_messages` | Idempotent message tracking | — |
| `ai_jobs` | 1 per business case | source_system + message_id unique |
| `ai_documents` | 1 per file in job | ai_jobs |
| `ai_pages` | 1 per rendered page | ai_documents |
| `ai_ocr_results` | OCR text per page | ai_pages |
| `ai_extracted_fields` | Structured field values | ai_pages |
| `ai_detection_results` | YOLO object detections | ai_pages |
| `ai_barcode_results` | Barcode/QR results | ai_pages |
| `ai_validation_results` | All rule results (PASSED/FAILED/etc) | ai_documents |
| `ai_cross_document_validation_results` | Inter-document consistency | ai_jobs |
| `ai_document_summaries` | Per-document aggregated summary | ai_documents |
| `ai_duplicate_check_results` | Duplicate detection | ai_documents |
| `ai_final_results` | Immutable final snapshot + JSONB | ai_jobs (1:1) |
| `ai_error_logs` | Scoped error tracking (JOB/DOC/PAGE) | ai_jobs |
| `ai_audit_logs` | Audit trail | ai_jobs |
| `ai_retry_logs` | Retry history | ai_jobs |
| `ai_model_versions` | Model metadata | — |
| `ai_model_runs` | Per-inference model usage | ai_jobs |
| `ai_artifacts` | File metadata (no binaries in DB) | ai_jobs |
| `ai_outbox_events` | Transactional outbox for publish | ai_jobs (1:1 per event type) |

---

## 6. Key Patterns

### Inbox Idempotency
```python
# ai_inbox_messages UNIQUE(source_system, message_id)
# Same message → same job → republish existing result
```

### Transactional Outbox
```sql
SELECT ... FROM ai_outbox_events
WHERE status = 'PENDING' AND available_at <= NOW()
ORDER BY created_at
FOR UPDATE SKIP LOCKED LIMIT :batch
```
Outbox publisher runs as a background task in the worker. Exponential backoff + jitter on failure.

### Document Concurrency
```python
doc_sem = asyncio.Semaphore(MAX_PARALLEL_DOCUMENTS)
async def process_one_doc(doc):
    async with doc_sem:
        return await _process_single_document(doc)
```

### Page Concurrency
```python
page_sem = asyncio.Semaphore(MAX_PARALLEL_PAGES)
async def process_one_page(pp_img, idx):
    async with page_sem:
        ocr = await self._ocr_chain.run(pp_img, ...)
        bc = await self._barcode_chain.read(pp_img)
        return ocr, bc
```

### YOLO Batch
```python
raw_detections = await self._yolo.detect_batch(preprocessed)
# All pages in one GPU call
```

---

## 7. Business Rules

| Rule | INV | DN | Default |
|------|-----|----|---------|
| Invoice number | R001 | — | Required |
| Amount | R002 | — | Required |
| Materai > Rp5M | R004 | — | Required |
| Company stamp | R005 | R002 | Required |
| Signature | R006 | R001 | Optional (configurable) |
| Barcode | R007 | — | Optional |
| Confidence >= 80 | R008 | R003 | Required |

Document types are extensible via `doc_types.py` (INV, DN, BILLING, RECEIPT, TAX, SUPPORTING, OTHER).

---

## 8. Confidence Scoring

```
total = 0.30 × OCR + 0.20 × Fields + 0.30 × Detection + 0.10 × Barcode + 0.10 × Quality
```

Threshold: `CONFIDENCE_THRESHOLD=80`. Barcode confidence from real decoder.

---

## 9. Config

`app/shared/config/settings.py` (~80 env vars). Key groups:

| Group | Example |
|-------|---------|
| Concurrency | `MAX_PARALLEL_DOCUMENTS=3`, `MAX_PARALLEL_PAGES=16`, `GPU_CONCURRENCY=1` |
| Timeouts | `DOCUMENT_PROCESSING_TIMEOUT_SECONDS=300`, `JOB=900` |
| Database | `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=10` |
| Outbox | `OUTBOX_POLL_INTERVAL_SECONDS=5`, `OUTBOX_BATCH_SIZE=10` |
| Result | `RESULT_DELIVERY_MODE=INLINE`, `MAX_RABBITMQ_RESULT_BYTES=5242880` |
| Retention | `FINAL_RESULT_RETENTION_DAYS=365`, `OCR_RESULT_RETENTION_DAYS=90` |
| YOLO | `YOLO_CONFIDENCE_THRESHOLD=0.40` |

---

## 10. Docker

```bash
docker compose up -d postgres adminer           # dev
docker compose up -d postgres rabbitmq ai-worker # production
python scripts/db_reset.py                       # create tables
```

---

## 11. Statuses

Jobs: RECEIVED → ACCEPTED → QUEUED → RUNNING → (COMPLETED | PARTIAL_COMPLETED | FAILED | DLQ)
Documents: PENDING → PROCESSING → COMPLETED | FAILED
Pages: PENDING → PROCESSING → COMPLETED | FAILED
Outbox: PENDING → PROCESSING → PUBLISHED | FAILED | DLQ
Inbox: RECEIVED → PROCESSING → PROCESSED | DUPLICATE | FAILED

Validation results: PASSED | FAILED | REVIEW | SKIPPED | NOT_APPLICABLE | ERROR
Business results: OK | NG | REVIEW | UNKNOWN
Processing results: SUCCESS | PARTIAL_SUCCESS | DOCUMENT_ERROR | INTERNAL_ERROR | TIMEOUT
