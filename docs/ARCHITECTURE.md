# AI Invoice Verification Agent Service — Architecture

> **Version:** 2.0.0 | **Python:** 3.11 | **Last Updated:** 2026-07-13

---

## 1. Project Overview

Automates Toyota invoice/delivery note verification using **YOLO** (object detection), **EasyOCR + pypdf** (text extraction), **zxing-cpp** (barcode), with RabbitMQ for messaging and PostgreSQL for persistence.

Clean Architecture: `domain/` → `application/` → `infrastructure/` → `interfaces/` + `workers/`.

---

## 2. Directory Structure

```
vision-ai/
├── app/
│   ├── domain/               # Business logic (no framework deps)
│   │   ├── entities/         # AIJob, Document, OCRResult, DetectionResult, etc.
│   │   ├── value_objects/    # ConfidenceScore, MoneyAmount
│   │   └── services/         # BusinessRuleEvaluator, ConfidencePolicy, RemarkPolicy
│   │
│   ├── application/          # Orchestration + use cases
│   │   ├── dto/              # InputPayloadDTO (RabbitMQ payload schema)
│   │   ├── queries/          # JobStatusResult, JobResultResponse
│   │   ├── commands/         # ReprocessJobCommand
│   │   ├── use_cases/        # Get/Reprocess job status/result
│   │   └── services/         # AIPipelineOrchestrator, FieldExtractionService,
│   │                         # ConfidenceScoringService, DocumentErrorBuilder
│   │
│   ├── infrastructure/       # Adapters for external systems
│   │   ├── database/         # SQLAlchemy models (13 tables), repos, Alembic migrations
│   │   ├── rabbitmq/         # Connection, consumer, publisher, retry, topology
│   │   ├── storage/          # ImageServerClient (HTTP), TempFileManager
│   │   ├── barcode/          # ZXingAdapter → PyzbarAdapter → OpenCVBarcodeAdapter
│   │   ├── detection/        # YOLOAdapter, DetectionMapper
│   │   ├── ocr/              # DocumentOCR (pypdf + EasyOCR), OCRFallbackChain
│   │   └── document_converter/  # DocumentValidator, PDFRenderer, ImagePreprocessor, WordConverter
│   │
│   ├── interfaces/           # FastAPI REST
│   │   └── api/routes/       # health, jobs, models, metrics
│   │
│   ├── workers/              # Production entry point
│   │   ├── worker_main.py    # WorkerMain — RabbitMQ consumer orchestrator
│   │   └── processors/       # JobProcessor
│   │
│   └── shared/               # Common: settings, constants, exceptions, logging, utils
│
├── scripts/
│   ├── upload_app.py         # Streamlit UI (local testing)
│   ├── direct_processor.py   # Standalone processor (used by Streamlit, saves to DB)
│   ├── result_adapter.py     # Normalize pipeline output for Streamlit UI
│   ├── check.py              # Self-check (requires GPU/OCR)
│   ├── db_query.py           # CLI database viewer
│   └── db_reset.py           # Drop + recreate all tables

├── models/                   # YOLO weights
├── docs/
├── tests/
├── docker-compose.yml        # 7 services
├── Dockerfile
├── .env.example
└── db_reset.bat
```

---

## 3. Flow — Production Path

```
VISION Service
    │
    │  RabbitMQ message {DOC_NO, DOC_TYPE, FILE_NM, PATH_FILE, ...}
    ▼
InvoiceRequestConsumer (app/infrastructure/rabbitmq/consumer.py)
    │  1. Parse JSON
    │  2. Ack or reject
    ▼
JobProcessor (app/workers/processors/job_processor.py)
    │  Delegates to orchestrator
    ▼
AIPipelineOrchestrator (app/application/services/ai_pipeline_orchestrator.py)
    │
    ├── 1. Validate payload (InputPayloadDTO)
    ├── 2. Check idempotency (build_idempotency_key → DB lookup)
    ├── 3. Save job record → ai_jobs
    ├── 4. Download document (ImageServerClient.fetch)
    ├── 5. Validate document (DocumentValidator)
    ├── 6. Render PDF → page images (PDFRenderer)
    ├── 7. Preprocess images (ImagePreprocessor)
    │
    ├── 8. YOLO detect ALL pages (YOLOAdapter.detect_batch) ⬅ GPU batch
    ├── 9. OCR + Barcode PER PAGE parallel (asyncio.gather) ⬅ page loop
    ├── 10. Aggregate results across pages
    │
    ├── 11. Field extraction (FieldExtractionService)
    ├── 12. Business rules (BusinessRuleEvaluator — INV or DN rules)
    ├── 13. Confidence scoring (ConfidenceScoringService)
    ├── 14. Save pages[] + final result → ai_final_results (JSONB)
    │
    ├── 15. Publish RabbitMQ result {QUEUE_ID, AI_RETURN_STATUS, ...}
    └── 16. Ack message
```

**Error paths:**
- Document error (file corrupt, unsupported, too large) → NG + DOCUMENT_ERROR, ack
- Internal error (timeout, crash) → retry up to 5x (backoff 30s/60s/120s/300s) → DLQ

---

## 4. Flow — Streamlit Testing

```
streamlit run scripts/upload_app.py
    │
    ▼
scripts/upload_app.py
    │  Upload PDF → select doc type (INV/DN) → Process
    ▼
scripts/direct_processor.py (DirectProcessor)
    │
    ├── 1. DocumentValidator.validate()
    ├── 2. PDFRenderer.render() → page images
    ├── 3. ImagePreprocessor.preprocess()
    ├── 4. OCR per page (DocumentOCR: pypdf → EasyOCR)
    ├── 5. Barcode per page (BarcodeFallbackChain)
    ├── 6. YOLO batch all pages (YOLOAdapter.detect_batch)
    ├── 7. Field extraction + Business rules + Confidence scoring
    │
    ├── 8. Save to PostgreSQL (ai_jobs + per-page OCR/detection/barcode + pages[])
    └── 9. Return result dict → Streamlit UI
```

Streamlit tabs: Preview (page image), OCR (raw text), Detection (objects + bbox), Fields (extracted values), Confidence (score breakdown).

---

## 5. Key Components

### 5.1 OCR — `app/infrastructure/ocr/document_ocr.py`

Two-phase: PDF → try `pypdf` text extraction first; if empty → fallback to **EasyOCR** (GPU). Single engine, no multi-engine chain.

### 5.2 YOLO Detection — `app/infrastructure/detection/yolo_adapter.py`

Ultralytics YOLO (model: `best-v5.pt`). Detects 4 classes:
| ID | Object |
|----|--------|
| 0 | barcode |
| 1 | materai |
| 2 | signature |
| 3 | stamp |

Threshold: `YOLO_CONFIDENCE_THRESHOLD=0.40`. Batch inference via `detect_batch()` — processes ALL pages in one GPU call.

### 5.3 Barcode — `app/infrastructure/barcode/barcode_fallback_chain.py`

3-tier fallback: **zxing-cpp** → **pyzbar** → **OpenCV**. Preprocess image for barcode before retrying. Full-page scan at multiple scales as last resort.

### 5.4 Business Rules — `app/domain/services/business_rule_evaluator.py`

| Rule | INV | DN | Condition |
|------|-----|----|-----------|
| R001 | Invoice number | — | Required |
| R002 | Amount | — | Required |
| R003 | Billing number | — | Optional |
| R004 | Materai > Rp5M | — | Required above threshold |
| R005 | Company stamp | — | Required |
| R006 | Signature | Signature count >= 2 | Configurable |
| R007 | Barcode | — | Configurable |
| R008 | Confidence >= 80 | Confidence >= 80 | Required |

### 5.5 Confidence Scoring — `app/domain/services/confidence_policy.py`

```
total = 0.30 × OCR + 0.20 × Fields + 0.30 × Detection + 0.10 × Barcode + 0.10 × Quality
```

Barcode confidence: uses **real decoder confidence** from zxing/pyzbar/OpenCV, not hardcoded.

---

## 6. Database

13 tables, all in `app/infrastructure/database/models.py`. Key relationships:

```
ai_jobs ──┬── ai_documents ──┬── ai_ocr_results        (per page)
         │                  ├── ai_detection_results   (per object)
         │                  ├── ai_barcode_results      (per page)
         │                  ├── ai_business_validation_results
         │                  ├── ai_duplicate_check_results
         │                  └── ai_document_summaries   (1:1)
         ├── ai_final_results    (1:1, has pages[] JSONB)
         ├── ai_error_logs
         ├── ai_audit_logs
         └── ai_retry_logs
```

`ai_final_results.internal_result_json` — JSONB column containing `pages[]` with per-page OCR, detections, barcode.

---

## 7. API

| Route | Method | Description |
|-------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/jobs/{queue_id}/status` | GET | Processing status |
| `/api/v1/jobs/{queue_id}/result` | GET | Final result + `pages[]` |
| `/api/v1/jobs/{queue_id}/reprocess` | POST | Trigger reprocessing |
| `/api/v1/models/version` | GET | Model metadata |
| `/metrics` | GET | Prometheus metrics |

Auth: `X-API-Key` header (configurable via `API_AUTH_MODE`).

---

## 8. Configuration

**Single file:** `app/shared/config/settings.py` — `Settings` class (~80 env vars).

Key settings:

| Variable | Default | Notes |
|----------|---------|-------|
| `YOLO_CONFIDENCE_THRESHOLD` | `0.40` | Raised from 0.25 to reduce false positives |
| `CONFIDENCE_THRESHOLD` | `80` | Min total confidence for OK result |
| `MAX_RETRY` | `5` | Max retry attempts on internal error |
| `MAX_FILE_SIZE_MB` | `25` | Max document size |

---

## 9. Docker

```
docker compose up -d postgres adminer          # dev: DB + web viewer
docker compose up -d postgres rabbitmq ai-worker  # production
```

| Service | Port | Purpose |
|---------|------|---------|
| postgres | 5432 | Database |
| rabbitmq | 5672, 15672 | Message broker + management UI |
| adminer | 8080 | Web-based DB viewer (login: postgres/postgres) |
| ai-worker | — | Production worker (GPU) |
| app-api | 8000 | FastAPI (optional) |
| prometheus | 9090 | Metrics |
| grafana | 3000 | Dashboard |

Reset DB: `python scripts/db_reset.py` (or double-click `db_reset.bat`). Drops and recreates all tables from ORM models.

---

## 10. Error Handling

| Code | Meaning | Retry? | Confidence |
|------|---------|--------|------------|
| `SUCCESS` | Pipeline completed | No | 0–100 |
| `DOCUMENT_ERROR` | File corrupt/unsupported | No | null |
| `INTERNAL_ERROR` | Timeout/crash/OOM | Yes (5x) | null |
| `DLQ_ERROR` | Retries exhausted | No | null |

---

## 11. Deployment

```bash
# Build
docker compose build

# Run
docker compose up -d postgres rabbitmq ai-worker

# Self-check
python scripts/check.py test_invoice.pdf
```

Requires NVIDIA GPU with CUDA 12.1+, 6GB VRAM minimum. YOLO model weights in `./models/`.
