# AI Invoice Verification Agent Service — Complete Architecture

> **Version:** 1.0.0 | **Python:** 3.11 | **Last Updated:** 2026-07-10

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Configuration Reference](#4-configuration-reference)
5. [Core Pipeline Processing Flow](#5-core-pipeline-processing-flow)
6. [PDF Rendering (PyMuPDF)](#6-pdf-rendering)
7. [YOLO Object Detection Pipeline](#7-yolo-object-detection-pipeline)
8. [OCR Pipeline (EasyOCR)](#8-ocr-pipeline)
9. [Business Validation Rules](#9-business-validation-rules)
10. [Confidence Scoring](#10-confidence-scoring)
11. [RabbitMQ Messaging](#11-rabbitmq-messaging)
12. [Database Schema](#12-database-schema)
13. [API Endpoints](#13-api-endpoints)
14. [Streamlit Testing UI](#14-streamlit-testing-ui)
15. [Observability](#15-observability)
16. [Deployment](#16-deployment)
17. [Testing](#17-testing)
18. [Performance Benchmarks](#18-performance-benchmarks)
19. [Error Handling Reference](#19-error-handling-reference)
20. [Migration Guide](#20-migration-guide)

---

## 1. Project Overview

### 1.1 Purpose

AI Invoice Verification Agent Service for Toyota. Automates document verification for invoices and delivery notes using:
- **YOLO** object detection (materai, stamp, signature, barcode)
- **EasyOCR** for text extraction
- **PyMuPDF** for PDF rendering
- **RabbitMQ** for message broker (target production)
- **Streamlit** for local testing UI

### 1.2 Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture Style | Clean Architecture (Domain/Application/Infrastructure) | Separation of business logic from frameworks |
| OCR Engine | EasyOCR (primary GPU), fallback Tesseract (CPU) | Accuracy for Indonesian invoice documents |
| PDF Renderer | PyMuPDF (fitz) v1.28 | Fast, supports DPI scaling, text extraction |
| DL Model Framework | Ultralytics YOLO 8.4.x | Production-proven, batch inference support |
| Message Broker | RabbitMQ with aio-pika | Async, reliable, DLQ/retry support |
| Async Runtime | asyncio + ProcessPoolExecutor | Balanced I/O and CPU parallelism |
| GPU Management | Dedicated single-thread GPU worker | Avoids CUDA context duplication across processes |
| UI Testing | Streamlit (development only) | Fast prototyping, not for production |

### 1.3 Class Mapping (YOLO)

| Class ID | Label | Description |
|----------|-------|-------------|
| 0 | barcode | Barcode or QR code |
| 1 | materai | Stamp duty / meterai |
| 2 | signature | Tanda tangan / signature |
| 3 | stamp | Company stamp |

---

## 2. System Architecture

### 2.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Production Worker                            │
│  ┌────────────────┐    ┌─────────────────────────────────────────┐  │
│  │  RabbitMQ       │───▶│  DocumentWorker (app/main.py)           │  │
│  │  Consumer       │    │                                         │  │
│  └────────────────┘    │  ┌─────────────┐  ┌───────────────────┐ │  │
│                         │  │ YoloRuntime  │  │ EasyOCRRuntime    │ │  │
│                         │  │ (GPU, once)  │  │ (GPU single-thr)  │ │  │
│                         │  └──────┬──────┘  └────────┬──────────┘ │  │
│                         │         │                  │            │  │
│                         │  ┌──────▼──────────────────▼──────────┐ │  │
│                         │  │    TransactionProcessor             │ │  │
│                         │  │  ┌──────────────────────────────┐   │ │  │
│                         │  │  │ ProcessPool (Render 4x)      │   │ │  │
│                         │  │  └──────────────────────────────┘   │ │  │
│                         │  └────────────────────────────────────┘ │  │
│  ┌────────────────┐    │                                         │  │
│  │  RabbitMQ       │◀───│  Result Aggregator → Publisher         │  │
│  │  Publisher      │    └─────────────────────────────────────────┘  │
│  └────────────────┘                                                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        Streamlit Testing UI                         │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐   │
│  │  Upload App   │───▶│  StreamlitProcessor (scripts/            │   │
│  │  (scripts/    │    │  streamlit_processor.py)                 │   │
│  │   upload_app) │    │                                          │   │
│  └──────────────┘    │  Same cores: YoloRuntime, EasyOCRRuntime  │   │
│                      │  + RenderPool (persistent)                │   │
│                      └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Pipeline Flow

```
[Upload/RabbitMQ]
    │
    ▼
[Inspect PDF] → page_count, dimensions, rotation, text_layer presence
    │
    ▼
[Render Pages] → ProcessPoolExecutor (4 workers), PyMuPDF, 200 DPI
    │
    ▼
[Submit to YOLO Batcher] → Dynamic batch collection (max 8 images, 20ms wait)
    │
    ├── [Batch GPU Inference] → One model.predict(list_of_paths)
    │
    ▼
[Submit to OCR] → Single EasyOCR GPU instance (dedicated thread)
    │                or CPU ProcessPool (fallback)
    ▼
[Coordinate Mapping] → pixel → normalized → PDF points
    │
    ▼
[Result Aggregation] → Per-page, per-document, per-transaction
    │
    ▼
[Publish Result] → JSON structure or Streamlit display
```

---

## 3. Directory Structure

```
E:\TOYOTA\VISION\vision-ai\
├── .env                          # Local environment config
├── .env.example                  # Template for .env
├── .dockerignore                 # Docker build exclusions
├── .gitignore                    # Git exclusions
├── .python-version               # Python 3.11
├── .streamlit/
│   └── config.toml               # maxUploadSize=10MB
├── pyproject.toml                # Project metadata + dependencies
├── requirements.txt              # pip dependencies
├── Dockerfile                    # Multi-stage build
├── docker-compose.yml            # 6 services
├── prometheus.yml                # Metrics scrape config
├── PRD.md                        # Full product requirements
├── README.md                     # Quick start guide
│
├── app/
│   ├── __init__.py
│   ├── config.py                 # PipelineConfig (pydantic-settings)
│   ├── main.py                   # DocumentWorker entry point
│   │
│   ├── inference/
│   │   ├── __init__.py
│   │   ├── yolo_runtime.py       # YOLO model: load once, batch predict
│   │   ├── yolo_batcher.py       # Dynamic YOLO batch collector
│   │   ├── easyocr_runtime.py    # EasyOCR GPU: single thread
│   │   └── ocr_runtime.py        # OCR CPU worker for ProcessPool
│   │
│   ├── orchestration/
│   │   ├── __init__.py
│   │   ├── transaction_processor.py  # End-to-end pipeline
│   │   └── result_aggregator.py      # JSON result builder
│   │
│   ├── rendering/
│   │   ├── __init__.py
│   │   └── pdf_renderer.py       # PyMuPDF inspect + render
│   │
│   ├── postprocessing/
│   │   ├── __init__.py
│   │   └── coordinate_mapper.py  # Bbox pixel/normalized/PDF point
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── local_storage.py      # Temp file management
│   │
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── logging.py            # structlog setup
│   │   ├── metrics.py            # Prometheus metrics
│   │   └── tracing.py            # Trace ID context
│   │
│   ├── domain/
│   │   ├── entities/             # 7 dataclass entities
│   │   ├── value_objects/        # 6 value objects
│   │   ├── services/             # 3 domain services
│   │   ├── repositories/         # 3 repository interfaces
│   │   └── errors/               # 5 error classes
│   │
│   ├── application/
│   │   ├── use_cases/            # 4 use cases
│   │   ├── dto/                  # 4 DTOs
│   │   ├── commands/             # 2 commands
│   │   ├── queries/              # 2 queries
│   │   ├── ports/                # 6 port interfaces
│   │   └── services/             # 6 services
│   │
│   ├── infrastructure/
│   │   ├── database/             # SQLAlchemy models, repos, migrations
│   │   ├── rabbitmq/             # Connection, consumer, publisher, retry, DLQ
│   │   ├── storage/              # Image server, temp manager, object storage
│   │   ├── barcode/              # zxing, pyzbar, OpenCV adapters
│   │   ├── detection/            # YOLO adapter, mapper, fallback
│   │   ├── ocr/                  # PaddleOCR, EasyOCR, Tesseract adapters (legacy)
│   │   ├── document_converter/   # PDF render, word converter, preprocessor
│   │   └── monitoring/           # Prometheus metrics, tracing (legacy)
│   │
│   ├── interfaces/
│   │   └── api/                  # FastAPI routes (health, jobs, models, metrics)
│   │
│   └── workers/
│       ├── consumers/            # RabbitMQ consumer
│       └── processors/           # Job processor, retry handler, DLQ handler
│
├── scripts/
│   ├── __init__.py
│   ├── upload_app.py             # Streamlit UI
│   ├── streamlit_processor.py    # Parallel pipeline adapter for Streamlit
│   ├── result_adapter.py         # Pipeline result → UI normalization
│   └── direct_processor.py       # Legacy sequential processor
│
├── tests/
│   ├── conftest.py               # Shared fixtures
│   ├── unit/
│   │   ├── domain/               # Business rules, confidence, remark
│   │   ├── test_validator.py     # Document validator
│   │   └── test_id_generator.py  # Queue ID, idempotency key
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── models/                       # YOLO model weights
│   ├── best-v5.pt                # Current document model
│   ├── best-v4.pt                # Previous version
│   ├── best-v3.pt                # Earlier version
│   └── yolo11s.pt                # COCO pretrained
│
└── docs/
    └── ARCHITECTURE.md           # This file
```

---

## 4. Configuration Reference

### 4.1 PipelineConfig (`app/config.py`)

**File:** `app/config.py` | **Class:** `PipelineConfig` (line 5) | **Instance:** `config = PipelineConfig()` (line 90)

#### General

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `"local"` | Environment name (local/staging/production) |
| `LOG_LEVEL` | `"INFO"` | Logging level |

#### RabbitMQ

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_URL` | `""` | Connection URL (e.g., `amqp://guest:guest@localhost:5672/`) |
| `RABBITMQ_INPUT_QUEUE` | `"ai.transaction.input"` | Input queue name |
| `RABBITMQ_INPUT_EXCHANGE` | `"ai.transaction.exchange"` | Input exchange name |
| `RABBITMQ_INPUT_ROUTING_KEY` | `"ai.transaction.input"` | Input routing key |
| `RABBITMQ_RESULT_EXCHANGE` | `"ai.transaction.result.exchange"` | Result exchange |
| `RABBITMQ_RESULT_QUEUE` | `"ai.transaction.result"` | Result queue |
| `RABBITMQ_RESULT_ROUTING_KEY` | `"ai.transaction.result"` | Result routing key |
| `RABBITMQ_DLX` | `"ai.transaction.dlx"` | Dead letter exchange |
| `RABBITMQ_DLQ` | `"ai.transaction.dlq"` | Dead letter queue |
| `RABBITMQ_PREFETCH_COUNT` | `1` | Prefetch count |

#### PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `""` | Async PostgreSQL URL |

#### YOLO

| Variable | Default | Description |
|----------|---------|-------------|
| `YOLO_MODEL_PATH` | `"./models/best-v5.pt"` | YOLO weights path |
| `YOLO_INPUT_SIZE` | `640` | Input image size (px) |
| `YOLO_CONFIDENCE_THRESHOLD` | `0.25` | Detection confidence threshold |
| `YOLO_NMS_THRESHOLD` | `0.45` | Non-max suppression IoU |
| `YOLO_BATCH_SIZE` | `8` | Max images per batch |
| `YOLO_MAX_BATCH_WAIT_MS` | `20` | Batch collection timeout (ms) |

#### OCR

| Variable | Default | Description |
|----------|---------|-------------|
| `OCR_ENGINE` | `"easyocr"` | OCR engine (`easyocr` or `tesseract`) |
| `OCR_USE_GPU` | `True` | Enable GPU for OCR |
| `OCR_PROCESS_WORKERS` | `2` | CPU OCR process pool size |
| `EASYOCR_BATCH_SIZE` | `4` | EasyOCR internal batch size |
| `EASYOCR_DOWNLOAD_ENABLED` | `True` | Allow model download |

#### PDF Rendering

| Variable | Default | Description |
|----------|---------|-------------|
| `PDF_DEFAULT_DPI` | `200` | Default render DPI |
| `PDF_MIN_DPI` | `150` | Minimum adaptive DPI |
| `PDF_MAX_DPI` | `300` | Maximum adaptive DPI |
| `RENDER_PROCESS_WORKERS` | `4` | PDF render process pool size |

#### Concurrency

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCUMENT_CONCURRENCY` | `3` | Max documents processed in parallel |
| `PAGE_CONCURRENCY` | `16` | Max pages processed in parallel |
| `DOWNLOAD_CONCURRENCY` | `4` | Max simultaneous downloads |

#### Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `DOWNLOAD_TIMEOUT_SECONDS` | `60` | Document download |
| `PDF_INSPECT_TIMEOUT_SECONDS` | `30` | PDF metadata inspection |
| `PDF_RENDER_TIMEOUT_SECONDS` | `120` | Full PDF rendering |
| `YOLO_TIMEOUT_SECONDS` | `60` | YOLO inference |
| `OCR_TIMEOUT_SECONDS` | `120` | OCR inference |
| `TRANSACTION_TIMEOUT_SECONDS` | `900` | Complete transaction (15 min) |
| `PUBLISH_TIMEOUT_SECONDS` | `30` | Result publish |

#### Retry

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_RETRY` | `5` | Maximum retry attempts |
| `RETRY_BACKOFF_SECONDS` | `30` | Initial backoff |
| `RETRY_BACKOFF_MULTIPLIER` | `2` | Backoff multiplier |

#### Business Rules

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | `80` | Minimum total confidence for OK |
| `AMOUNT_STAMP_DUTY_THRESHOLD` | `5_000_000` | Amount threshold for materai requirement |
| `REQUIRE_SIGNATURE_FOR_INVOICE` | `False` | Signature mandatory for invoice |
| `REQUIRE_STAMP_FOR_INVOICE` | `True` | Stamp mandatory for invoice |
| `REQUIRE_BARCODE_FOR_INVOICE` | `False` | Barcode mandatory for invoice |
| `REQUIRE_MATERAI_ABOVE_THRESHOLD` | `True` | Materai mandatory above threshold |
| `DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT` | `2` | Min signatures for DN |
| `DELIVERY_NOTE_REQUIRED_STAMP_COUNT` | `2` | Min stamps for DN |

#### File Validation

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_FILE_SIZE_MB` | `25` | Max upload size |
| `MIN_IMAGE_WIDTH` | `800` | Min image width (px) |
| `MIN_IMAGE_HEIGHT` | `800` | Min image height (px) |
| `MAX_PAGE_COUNT` | `200` | Max PDF pages |

### 4.2 Streamlit Config (`.streamlit/config.toml`)

```toml
[server]
maxUploadSize = 10  # MB
```

---

## 5. Core Pipeline Processing Flow

### 5.1 Entry Points

#### Production Path (`app/main.py`)

```python
# app/main.py:83-84
if __name__ == "__main__":
    asyncio.run(main())
```

`DocumentWorker` (line 24):
1. `start()` (line 33): Loads YOLO → Starts batcher → Loads EasyOCR → Creates render pool → Creates TransactionProcessor
2. Waits for shutdown signal
3. `_shutdown()` (line 67): Stops batcher → Shuts down EasyOCR → Shuts down render pool → Cleans up storage

#### Testing Path (`scripts/upload_app.py`)

```python
# scripts/upload_app.py:231-232
if __name__ == "__main__":
    asyncio.run(main_ui())
```

`main_ui()` (line 74): Initializes state → Renders sidebar (processor mode, clear) → Upload area → Process button → Result display

### 5.2 TransactionProcessor Pipeline

**File:** `app/orchestration/transaction_processor.py` | **Class:** `TransactionProcessor` (line 29)

| Step | Method | Line | Description |
|------|--------|------|-------------|
| 1 | `process_transaction()` | 47 | Sets trace_id, creates result structure, parses documents |
| 2 | `_parse_documents()` | 153 | Extracts single or multi-doc from payload |
| 3 | `_process_document()` | 169 | Per document: download, inspect, render, process pages |
| 4 | `_download_document()` | 250 | HTTP GET via httpx with semaphore |
| 5 | `inspect_pdf()` | 198 | PDF metadata (page_count, rotation, text layer) |
| 6 | `render_page()` | 213 | ProcessPoolExecutor map for parallel rendering |
| 7 | `_process_pages()` | 258 | Per page: YOLO batcher → OCR pool → coordinate mapping |

### 5.3 YOLO Dynamic Batcher

**File:** `app/inference/yolo_batcher.py` | **Class:** `YoloBatcher` (line 23)

```
                        ┌─────────────────────────┐
Page A1 image_path ────▶│  asyncio.Queue(max=32)   │
Page A2 image_path ────▶│                          │
Page B1 image_path ────▶│ batch collector          │
                        └────────┬─────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Collect until:          │
                    │  - Batch size >= BATCH   │
                    │  - OR 20ms timeout       │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  YoloRuntime             │
                    │  .predict_batch(paths)   │
                    │  → 1 GPU call            │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Resolve futures:        │
                    │  results[page_idx]        │
                    └─────────────────────────┘
```

### 5.4 StreamlitProcessor (Testing)

**File:** `scripts/streamlit_processor.py` | **Class:** `StreamlitProcessor` (line 21)

- `__init__` (line 26): Creates YoloRuntime, YoloBatcher, EasyOCRRuntime, RenderPool, LocalStorage
- `warmup()` (line 36): Loads YOLO → Starts batcher → Loads EasyOCR GPU → Creates persistent render pool
- `process()` (line 67): Temp dir → inspect PDF → render pages (persistent pool) → parallel page processing via `asyncio.gather()` → aggregate results

### 5.5 Result Adapter (`scripts/result_adapter.py`)

**Function:** `normalize_pipeline_result_for_ui()` (line 10)

Converts raw pipeline result into stable UI format:

```python
# Raw Pipeline Output (schema may vary)
{
    "status": "OK",
    "processing_time_ms": 70813,
    "pages": [numpy_array, ...],  # Page images
    "detections": [...],           # All detections
    "detection_aggregated": {...}, # Aggregated per label
    "ocr": {...},                  # Last OCR result
    "fields": {...},
    "confidence": {...},
    "remarks": "...",
}

# Normalized UI Result
{
    "status": "SUCCESS",
    "processing_time_ms": 70813,
    "document": {
        "file_name": "...", "extension": ".pdf",
        "size_bytes": 384409, "size_kb": 375.4,
        "content_type": "application/pdf",
        "page_count": 3,
    },
    "pages": [{
        "page_index": 0,
        "page_number": 1,
        "status": "SUCCESS",
        "preview": {"image_bytes": b"...", "mime_type": "image/png"},
        "ocr": {"status": "SUCCESS", "engine": "easyocr", "raw_text": "...", "avg_confidence": 91.0},
        "detections": [{"label": "signature", "confidence": 69.4, "bbox": [...]}],
        "fields": {},
    }],
}
```

---

## 6. PDF Rendering

### 6.1 Inspection (`app/rendering/pdf_renderer.py`)

**Function:** `inspect_pdf(file_path)` (line 13)

```python
# Returns:
{
    "status": "SUCCESS",
    "page_count": 5,
    "has_text_layer": True,
    "pages": [
        {"page_index": 0, "page_number": 1, "page_width_pt": 595.0, "page_height_pt": 842.0,
         "rotation": 0, "has_text": True},
        ...
    ]
}
```

### 6.2 Rendering (`app/rendering/pdf_renderer.py`)

**Function:** `render_page(args_dict)` (line 45)

- **Engine:** PyMuPDF (fitz) v1.28
- **DPI:** configurable (default 200)
- **Colorspace:** `fitz.csRGB` (RGB)
- **Output:** PNG file saved to `{output_dir}/{document_id}_page_{page_number:05d}.png`
- **Parallelism:** ProcessPoolExecutor (4 workers by default)

```python
# Each render_page call:
doc = fitz.open(file_path)
page = doc.load_page(page_index)
mat = fitz.Matrix(dpi / 72, dpi / 72)
pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
pix.save(output_path)
# Returns metadata dict with image_path, dimensions, dpi, rotation, timing
```

### 6.3 Adaptive DPI Strategy

| Document Type | DPI Range | Condition |
|--------------|-----------|-----------|
| Digital clear | 150-200 | Text layer present |
| Normal scan | 200-250 | No text layer |
| Small text/barcode | 250-300 | Low OCR confidence trigger |
| Retry on failure | 300 | Single page re-render |

---

## 7. YOLO Object Detection Pipeline

### 7.1 Model Lifecycle

**File:** `app/inference/yolo_runtime.py` | **Class:** `YoloRuntime` (line 18)

```
Application Startup
    │
    ├── YoloRuntime.load()
    │   ├── torch.load monkey-patch (weights_only=False)
    │   └── YOLO(config.YOLO_MODEL_PATH)  ← LOADED ONCE
    │
    ├── YoloRuntime.warmup()
    │   └── model.predict(dummy_640x640)   ← CUDA warm-up
    │
    └── YoloBatcher.start()
        └── asyncio.create_task(_batch_loop)
```

### 7.2 Batch Inference

**File:** `app/inference/yolo_runtime.py` | **Method:** `predict_batch()` (line 39)

```python
results = self._model.predict(
    source=image_paths,      # list[str] — multiple images
    imgsz=640,               # 640px, not 1280
    conf=0.25,
    iou=0.45,
    device="cuda:0",
    verbose=False,
)
```

Returns: `list[list[dict]]` — one list per page, each containing detections with:
- `class_id`, `label`, `confidence`, `bbox_pixel_xyxy` (int coordinates)

### 7.3 Detection Classes

From YOLO model `model.names`:
```python
{0: 'barcode', 1: 'materai', 2: 'signature', 3: 'stamp'}
```

### 7.4 Bounding Box Coordinate System

**File:** `app/postprocessing/coordinate_mapper.py` | **Function:** `convert_bbox()` (line 4)

```python
{
    "pixel_xyxy": [1050.5, 1830.2, 1435.8, 2095.4],        # Raw pixel coords
    "normalized_xyxy": [0.6351, 0.7824, 0.8680, 0.8958],    # pixel / image_dim
    "pdf_points_xyxy": [378.3, 658.8, 517.0, 754.3],        # normalized * page_dim_pt
}
```

Rotation handling: 0°, 90°, 180°, 270° coordinate correction.

---

## 8. OCR Pipeline

### 8.1 GPU Path (Single Thread)

**File:** `app/inference/easyocr_runtime.py` | **Class:** `EasyOCRRuntime` (line 17)

- **ThreadPoolExecutor(1)** ensures only 1 GPU inference at a time
- **Reason:** Avoids CUDA context duplication across process pools
- **Load time:** ~5-10s (first call, CUDA init + model load)
- **Inference time:** ~1-3s per page (GPU)

```python
# Initialization
self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="easyocr-gpu")

# Load (called once during startup)
self._reader = easyocr.Reader(["en"], gpu=True, download_enabled=True)

# Read (called per page)
results = self._reader.readtext(
    img, detail=1, paragraph=False,
    batch_size=4, workers=0, canvas_size=2560,
)
```

### 8.2 CPU Path (ProcessPool)

**File:** `app/inference/ocr_runtime.py` | **Function:** `init_ocr_worker()` (line 16)

- Used for CPU fallback when GPU unavailable
- Each process initializes its own EasyOCR (CPU mode)
- ProcessPoolExecutor with 2 workers

### 8.3 Image Preprocessing

Before OCR:
- If image dimension > 1920px: resize to 1920px max
- Preserve aspect ratio via `cv2.INTER_AREA`

### 8.4 OCR Output Structure

```python
{
    "status": "SUCCESS",
    "language": ["en"],
    "mean_confidence": 0.934,
    "full_text": "INVOICE NO: INV-2026-001234\nTotal: Rp 15.750.000\n...",
    "blocks": [
        {"text": "INVOICE NO: INV-2026-001234", "confidence": 0.97, "bbox": [...]},
        ...
    ],
    "duration_ms": 1542,
}
```

---

## 9. Business Validation Rules

**File:** `app/domain/services/business_rule_evaluator.py` | **Class:** `BusinessRuleEvaluator` (line 28)

### 9.1 Invoice Rules

| Rule Code | Rule Name | Condition | Failure Remark |
|-----------|-----------|-----------|----------------|
| INV-R001 | Invoice number required | Invoice number detected | "Invoice number not found." |
| INV-R002 | Amount required | Amount detected | "Amount not found." |
| INV-R003 | Billing number required | Billing number detected | "Billing number not found." |
| INV-R004 | Materai required above threshold | Amount > 5M → materai detected | "Above Rp. 5.000.000. Missing Stamp Duty." |
| INV-R005 | Company stamp required | Stamp detected | "Missing company stamp." |
| INV-R006 | Signature required | Signature detected | "Missing signature." |
| INV-R007 | Barcode required | Barcode detected | "Barcode not found." |
| INV-R008 | Confidence below threshold | Total >= 80 | "AI confidence below threshold." |
| INV-R009 | All rules passed | All above OK | "Verification passed." |

### 9.2 Delivery Note Rules

| Rule Code | Rule Name | Condition | Failure Remark |
|-----------|-----------|-----------|----------------|
| DN-R001 | Signature count | signature_count >= config | "Required signature count not met." |
| DN-R002 | Stamp count | stamp_count >= config | "Required company stamp count not met." |
| DN-R003 | Stamp colour (optional) | Valid colour | "Stamp colour requirement not met." |
| DN-R004 | All rules passed | All above OK | "Verification passed." |

### 9.3 RuleConfig

```python
class RuleConfig:
    require_invoice_number: bool = True
    require_amount: bool = True
    require_billing_number: bool = False
    amount_stamp_duty_threshold: int = 5_000_000
    require_materai_above_threshold: bool = True
    require_signature: bool = False
    require_stamp: bool = True
    require_barcode: bool = False
    required_signature_count: int = 2
    required_stamp_count: int = 2
    require_colored_stamp: bool = True
    confidence_threshold: int = 80
    min_object_confidence: float = 0.25
```

---

## 10. Confidence Scoring

**File:** `app/domain/services/confidence_policy.py` | **Class:** `ConfidencePolicy` (line 8)

### 10.1 Weighted Formula

```python
total_confidence = (
    0.30 * ocr_field_confidence +
    0.20 * field_validation_confidence +
    0.30 * object_detection_confidence +
    0.10 * barcode_confidence +
    0.10 * document_quality_confidence
)
```

### 10.2 Score Components

| Component | Weight | Calculation |
|-----------|--------|-------------|
| OCR Field | 30% | Average of invoice_num + billing_num + amount OCR confidence |
| Field Validation | 20% | 100 if invoice_num and amount found, else 30 |
| Object Detection | 30% | Average of all detection confidences |
| Barcode | 10% | 100 if decoded, 70 if found not decoded, 100 if not required, 0 if missing required |
| Document Quality | 10% | Average of resolution, blur, brightness, page_readability |

### 10.3 Confidence Levels

| Range | Level | Description |
|-------|-------|-------------|
| ≥ 95 | Very High | Excellent confidence |
| ≥ 80 | High | Meets threshold |
| ≥ 60 | Medium | Needs review |
| < 60 | Low | Likely needs manual processing |

### 10.4 Status Determination

```
if confidence >= 80 AND all mandatory business rules pass:
    status = "OK"
else:
    status = "NG"
    
if inference never ran (file error):
    confidence = null
```

---

## 11. RabbitMQ Messaging

### 11.1 Topology

**File:** `app/infrastructure/rabbitmq/topology.py` | **Function:** `declare_topology()` (line 10)

| Component | Name | Type | Purpose |
|-----------|------|------|---------|
| Input Exchange | `ai.transaction.exchange` | direct | Receives processing requests |
| Input Queue | `ai.transaction.input` | durable, DLX → dlx | Main processing queue |
| Result Exchange | `ai.transaction.result.exchange` | direct | Published results |
| Result Queue | `ai.transaction.result` | durable | Result consumption |
| Retry Exchange | `ai.transaction.retry.exchange` | direct | Retry routing |
| Retry Queue | `ai.transaction.retry.queue` | TTL, DLX → input | Delayed retry |
| DLX | `ai.transaction.dlx` | direct | Dead letter exchange |
| DLQ | `ai.transaction.dlq` | durable | Final failure queue |

### 11.2 Retry Policy

| Attempt | Delay |
|---------|-------|
| 1 | Immediate |
| 2 | 30s |
| 3 | 60s |
| 4 | 120s |
| 5 | 300s |
| After 5 | DLQ |

Formula: `backoff = RETRY_BACKOFF_SECONDS * (RETRY_BACKOFF_MULTIPLIER ** (retry_count - 1))`

### 11.3 Input Message Schema

From `AI_Verification_Request_Contract_v1.json`:

```json
{
  "message_version": "1.0.0",
  "queue_no": "AIQ-20260630-000001",
  "correlation_id": "PV-XDM-2026-000146-001",
  "pv_no": "000123456",
  "pv_year": "2026",
  "transaction_type": "INVOICE_BILLING",
  "vendor_code": "V000001",
  "vendor_name": "PT. MITRA ABADI",
  "total_amount": 7500000,
  "created_datetime": "2026-06-30T09:40:00+07:00",
  "documents": [
    {
      "doc_no": "INV-2026-001",
      "doc_type": "INV",
      "doc_seq": 1,
      "file_nm": "INV-2026-001.pdf",
      "path_file": "https://doc-server/INV-2026-001.pdf"
    }
  ]
}
```

### 11.4 Result Message Schema

From `AI_Verification_Result_Contract_v1.json`:

```json
{
  "QUEUE_ID": "AIQ-20260703-000124",
  "DOC_NO": "INV-2026-0007842",
  "DOC_TYPE": "INV",
  "DOC_SEQ": 1,
  "TRANS_TYPE_CD": "LSP-J",
  "FILE_NM": "INV-2026-0007842.pdf",
  "AI_SCAN_APP": "VISION",
  "AI_RETURN_STATUS": "NG",
  "AI_RETURN_REMARK": "Above Rp. 5.000.000. Missing Stamp Duty.",
  "AI_RETURN_CD": "SUCCESS",
  "AI_RETURN_CONFIDENCE": 90
}
```

### 11.5 Acknowledgement Strategy

```
1. Consume message
2. Validate payload
3. Check idempotency key
4. Save job to DB
5. Save outbox event
6. Ack message  ← Early ack, not waiting for full processing
7. Process pipeline
8. Save result
9. Publish with publisher confirm
10. Mark outbox as sent
```

---

## 12. Database Schema

### 12.1 Entity Relationship

```
ai_jobs ─┬─ ai_documents (1:N)
         ├─ ai_ocr_results (1:N)
         ├─ ai_detection_results (1:N)
         ├─ ai_barcode_results (1:N)
         ├─ ai_duplicate_check_results (1:N)
         ├─ ai_business_validation_results (1:N)
         ├─ ai_document_summaries (1:N)
         ├─ ai_final_results (1:1)
         ├─ ai_error_logs (1:N)
         ├─ ai_audit_logs (1:N)
         └─ ai_retry_logs (1:N)

ai_documents ─┬─ ai_ocr_results (1:N)
              ├─ ai_detection_results (1:N)
              ├─ ai_barcode_results (1:N)
              ├─ ai_duplicate_check_results (1:N)
              ├─ ai_business_validation_results (1:N)
              └─ ai_document_summaries (1:1)
```

### 12.2 Table Summary

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `ai_jobs` | PK: id, UK: queue_id, UK: idempotency_key, status, retry | Core job tracking |
| `ai_documents` | PK: id, FK: job_id, document metadata | Per-document records |
| `ai_ocr_results` | PK: id, FK: job_id + document_pk, raw_text, tokens_json, fields_json | OCR output per page |
| `ai_detection_results` | PK: id, FK: job_id + document_pk, object_type, confidence, bbox | Detection per object |
| `ai_barcode_results` | PK: id, FK: job_id + document_pk, barcode_found, decoded, value | Barcode data |
| `ai_duplicate_check_results` | PK: id, FK: job_id + document_pk, matched_document | Duplicate matching |
| `ai_business_validation_results` | PK: id, FK: job_id + document_pk, rule_code, result | Per-rule validation |
| `ai_document_summaries` | PK: id, FK: job_id + document_pk (unique), total/passed/failed | Document-level summary |
| `ai_final_results` | PK: id, FK: job_id (unique), queue_id (unique), AI_RETURN_* fields | Final result for publishing |
| `ai_error_logs` | PK: id, FK: job_id, error_category, stack_trace | Error tracking |
| `ai_model_versions` | PK: id, model_type, model_version, is_active | Model versioning |
| `ai_audit_logs` | PK: id, FK: job_id, actor, action, before/after JSON | Audit trail |
| `ai_retry_logs` | PK: id, FK: job_id, retry_count, scheduled_at | Retry history |

---

## 13. API Endpoints

### 13.1 FastAPI Routes

**File:** `app/interfaces/api/routes/`

| Endpoint | Method | File | Description |
|----------|--------|------|-------------|
| `/health` | GET | `health.py` | Service health check (200) |
| `/ready` | GET | `main.py:63` | Readiness check (DB, RabbitMQ, models) |
| `/api/v1/jobs/{queue_id}/status` | GET | `jobs.py:42` | Job processing status |
| `/api/v1/jobs/{queue_id}/result` | GET | `jobs.py:58` | Complete job result |
| `/api/v1/jobs/{queue_id}/reprocess` | POST | `jobs.py:74` | Trigger reprocessing |
| `/api/v1/models/version` | GET | `models.py:14` | Model version info |
| `/metrics` | GET | `metrics.py:11` | Prometheus metrics |

### 13.2 API Auth

- Mode: API key via `X-API-Key` header (configurable)
- Config: `API_AUTH_MODE` (api_key/jwt/none), `INTERNAL_API_KEY`
- **File:** `app/interfaces/api/dependencies.py`

---

## 14. Streamlit Testing UI

### 14.1 Architecture

**Files:**
- `scripts/upload_app.py` — Main application (232 lines)
- `scripts/streamlit_processor.py` — Parallel processor adapter (170 lines)
- `scripts/result_adapter.py` — Result normalization (120 lines)

### 14.2 Session State Management

**File:** `scripts/upload_app.py:38-47`

```python
DEFAULT_STATE = {
    "raw_result": None,           # Raw pipeline output
    "ui_result": None,            # Normalized UI result
    "processing_error": None,     # Error string if any
    "processing_done": False,     # Processing complete flag
    "processing_time_ms": None,   # Processing duration
    "uploaded_file_hash": None,   # SHA256 for file identity
    "selected_page_index": 0,     # Current page selector
    "artifact_directory": None,   # Temporary files location
}
```

### 14.3 UI Tabs

1. **Preview** — Page image, file metadata (extension, pages, size, content type)
2. **OCR** — Raw text, engine, avg confidence, blocks
3. **Detection** — Summary table, detection table, annotated image
4. **Fields** — Extracted fields table
5. **Confidence** — Total confidence, component scores

### 14.4 Page Selector

- Single global selectbox for all tabs
- Shows: "Page {number} of {total}"
- Stored in `st.session_state.selected_page_index`
- Changing page does NOT trigger pipeline re-run

### 14.5 @st.cache_resource

```python
# scripts/upload_app.py:44-52
@st.cache_resource(show_spinner=False)
def get_processor(mode: str):
    """Create processor once. Cached across Streamlit reruns."""
    if mode == "direct":
        p = DirectProcessor()
    else:
        p = StreamlitProcessor()
    return p
```

---

## 15. Observability

### 15.1 Structured Logging

**File:** `app/observability/logging.py`

- **Library:** structlog
- **Processors:** TimeStamper (ISO), context vars, level, logger name
- **Format:** ConsoleRenderer (local) or JSONRenderer (production)
- **Context fields:** `transaction_id`, `document_id`, `page_number`, `stage`, `duration_ms`

### 15.2 Prometheus Metrics

**File:** `app/observability/metrics.py`

| Metric | Type | Labels |
|--------|------|--------|
| `ai_transactions_received_total` | Counter | — |
| `ai_transactions_completed_total` | Counter | — |
| `ai_documents_processed_total` | Counter | — |
| `ai_pages_processed_total` | Counter | — |
| `ai_page_errors_total` | Counter | — |
| `ai_retries_total` | Counter | — |
| `ai_dlq_messages_total` | Counter | — |
| `ai_detections_total` | Counter | — |
| `ai_transaction_duration_seconds` | Histogram | 1-600s buckets |
| `ai_yolo_inference_seconds` | Histogram | 0.01-5s buckets |
| `ai_ocr_inference_seconds` | Histogram | 0.5-60s buckets |
| `ai_jobs_in_progress` | Gauge | — |
| `ai_yolo_queue_depth` | Gauge | — |
| `ai_gpu_memory_used_bytes` | Gauge | — |

### 15.3 Tracing

**File:** `app/observability/tracing.py`

- **Mechanism:** `contextvars.ContextVar` for trace_id (32-char hex UUID)
- **Propagation:** Structured log context
- **Future:** OpenTelemetry integration ready

### 15.4 Key Log Events

| Event | Stage | Purpose |
|-------|-------|---------|
| `yolo_loaded` | Startup | YOLO model loaded successfully |
| `yolo_batch_complete` | Inference | Batch processed with size + duration |
| `easyocr_init_done` | Startup | EasyOCR loaded with duration |
| `ocr_worker_init` | Startup | CPU OCR worker initialized |
| `pdf_rendered` | Rendering | Page render completed |
| `transaction_complete` | Result | Full transaction processed |

---

## 16. Deployment

### 16.1 Docker Compose Services

**File:** `docker-compose.yml`

| Service | Image | Ports | GPU | Depends On |
|---------|-------|-------|-----|------------|
| `app-api` | vision-ai-app-api (build) | 8000 | — | postgres, rabbitmq |
| `ai-worker` | vision-ai-ai-worker (build) | — | NVIDIA | postgres, rabbitmq |
| `rabbitmq` | rabbitmq:3-management | 5672, 15672 | — | — |
| `postgres` | postgres:16 | 5432 | — | — |
| `prometheus` | prom/prometheus | 9090 | — | — |
| `grafana` | grafana/grafana | 3000 | — | prometheus |

### 16.2 Dockerfile

**File:** `Dockerfile`

- **Base:** python:3.11-slim
- **System deps:** libreoffice-writer, libgl1, libglib2.0-0t64
- **Multi-stage:** `base` (deps) → `api` (uvicorn) → `worker` (python worker)

### 16.3 GPU Requirements

- **Runtime:** NVIDIA Container Toolkit
- **VRAM:** 6GB minimum (RTX 4050 dev), 24GB production
- **CUDA:** 12.1+ (cu121)
- **PyTorch:** 2.5.1+cu121 (verified working)

### 16.4 Environment Variables

Set via `.env` file or container environment:
```env
APP_ENV=local
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vision_ai
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
YOLO_MODEL_PATH=./models/best-v5.pt
OCR_USE_GPU=true
MAX_PAGE_COUNT=200
CONFIDENCE_THRESHOLD=80
```

---

## 17. Testing

### 17.1 Test Structure

| Directory | Coverage | Framework |
|-----------|----------|-----------|
| `tests/unit/domain/` | BusinessRuleEvaluator, ConfidencePolicy, RemarkPolicy | pytest |
| `tests/unit/test_validator.py` | DocumentValidator | pytest |
| `tests/unit/test_id_generator.py` | Queue ID, idempotency key | pytest |
| `tests/integration/` | Database, RabbitMQ, OCR, Detection, Barcode | pytest-asyncio |
| `tests/e2e/` | Full pipeline scenarios | pytest-asyncio |

### 17.2 Unit Test Examples

**Business Rules** (`tests/unit/domain/test_business_rules.py`):
- 6 tests covering invoice all-pass, missing stamp, missing materai, missing signature, delivery note pass/fail

**Confidence** (`tests/unit/domain/test_confidence.py`):
- 4 tests covering OCR average, detection average, barcode scores, total calculation

**Remark** (`tests/unit/domain/test_remark.py`):
- 3 tests covering pass remark, fail remark, doc error remark

**Validator** (`tests/unit/test_validator.py`):
- 4 tests covering empty file, invalid extension, PDF magic, valid small PDF

**ID Generator** (`tests/unit/test_id_generator.py`):
- 3 tests covering format, consistency, change on different input

### 17.3 Test Fixtures

**File:** `tests/conftest.py`

- `sample_invoice_payload()` → dict with INV document metadata
- `sample_dn_payload()` → dict with DN document metadata

---

## 18. Performance Benchmarks

### 18.1 Estimated Performance (RTX 4050 6GB VRAM)

| Operation | Per Page (GPU) | Per Page (CPU) | 5 Pages (GPU) |
|-----------|---------------|---------------|---------------|
| PDF Render (200 DPI) | ~200ms | ~200ms | ~200ms (parallel) |
| YOLO Detection (batch) | ~80ms | ~1s | ~100ms (1 batch) |
| EasyOCR | ~2-3s | ~30-40s | ~5-7s (parallel) |
| Barcode Decoding | ~200ms | ~200ms | ~200ms (parallel) |
| Preprocessing | ~30ms | ~30ms | ~30ms |
| **Total per page** | **~2.5s** | **~31s** | **~8s (parallel)** |

### 18.2 Key Optimizations

1. **YOLO batch inference:** 5 pages → 1 GPU call (~100ms) vs 5 calls (~400ms)
2. **EasyOCR single-GPU thread:** Avoids CUDA reinit penalty (~35s/worker)
3. **Render ProcessPool:** 4 workers parallel, pages render simultaneously
4. **Page processing via gather:** All pages processed concurrently
5. **Persistent pools:** No process creation per request

### 18.3 Memory Profile (5-page PDF)

| Resource | GPU VRAM | System RAM |
|----------|----------|------------|
| YOLO model | ~200MB | ~500MB |
| EasyOCR model | ~500MB | ~300MB |
| PDF render buffers | — | ~50MB |
| Page images (processing) | ~100MB | ~100MB |
| **Total** | **~800MB** | **~1GB** |

---

## 19. Error Handling Reference

### 19.1 Return Codes

| Code | Meaning | Retryable | Confidence |
|------|---------|-----------|------------|
| `SUCCESS` | AI process completed | No | 0-100 |
| `DOCUMENT_ERROR` | Document inaccessible/corrupt | No | null |
| `INTERNAL_ERROR` | Technical failure (timeout, OOM) | Yes | null |
| `DLQ_ERROR` | Retry exhausted | No | null |

### 19.2 Error Levels

| Level | Scope | Effect |
|-------|-------|--------|
| Transaction | Complete failure | All documents fail |
| Document | Single document | Other documents continue |
| Page | Single page | Other pages continue, status → PARTIAL_SUCCESS |
| Stage | YOLO/OCR/barcode failure | Other stages on same page continue |

### 19.3 Page-Level Error Isolation

```python
# transaction_processor.py:258-330
async def process_one_page(page_meta):
    try:
        yolo_dets = await yolo_batcher.submit(request)
    except Exception:
        pr["errors"].append({"stage": "YOLO", "code": "INFERENCE_FAILED", ...})
        yolo_dets = []
    
    try:
        ocr_res = await ocr_pool.submit(run_ocr, img_path)
    except Exception:
        pr["errors"].append({"stage": "OCR", "code": "INFERENCE_FAILED", ...})
        ocr_res = None
    
    return pr  # Always returns, never raises
```

---

## 20. Migration Guide

### 20.1 From Legacy to Parallel Pipeline

**Step 1:** Install dependencies
```powershell
conda create -n ocr python=3.11
conda activate ocr
pip install -r requirements.txt
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install easyocr pypdfium2
```

**Step 2:** Configure `.env`
```env
APP_ENV=local
YOLO_MODEL_PATH=./models/best-v5.pt
OCR_USE_GPU=true
```

**Step 3:** Place YOLO model weights in `./models/`

**Step 4:** Test with Streamlit
```powershell
$env:PYTHONIOENCODING="utf-8"
python -m streamlit run scripts\upload_app.py
```

**Step 5:** Test production worker
```powershell
python -m app.main
```

### 20.2 Files Changed During Refactor

| File | Status | Reason |
|------|--------|--------|
| `app/inference/easyocr_runtime.py` | CREATE | Single-GPU EasyOCR worker (replaces multi-process GPU) |
| `app/inference/ocr_runtime.py` | MODIFY | Remove GPU init, keep CPU-only process pool |
| `app/inference/yolo_batcher.py` | CREATE | Dynamic YOLO batch collector |
| `app/inference/yolo_runtime.py` | CREATE | Single YOLO instance with batch predict |
| `app/orchestration/transaction_processor.py` | MODIFY | Persistent render pool, parallel page processing |
| `app/rendering/pdf_renderer.py` | CREATE | PyMuPDF inspect + render functions |
| `app/postprocessing/coordinate_mapper.py` | CREATE | Bbox coordinate conversion |
| `app/storage/local_storage.py` | CREATE | Temp file management |
| `app/observability/logging.py` | CREATE | Structlog setup |
| `app/observability/metrics.py` | CREATE | Prometheus metrics |
| `app/observability/tracing.py` | CREATE | Trace ID management |
| `app/config.py` | CREATE | Centralized pipeline configuration |
| `app/main.py` | MODIFY | New DocumentWorker with persistent pools |
| `scripts/streamlit_processor.py` | CREATE | Parallel adapter for Streamlit |
| `scripts/result_adapter.py` | CREATE | Result normalization adapter |
| `scripts/upload_app.py` | MODIFY | Session state, caching, page navigation |
| `app/infrastructure/ocr/document_ocr.py` | MODIFY | Remove lazy init, require warmup |
| `app/infrastructure/detection/yolo_adapter.py` | MODIFY | Add detect_batch method |
| `app/infrastructure/document_converter/pdf_renderer.py` | MODIFY | PyMuPDF renderer update |

### 20.3 Breaking Changes

| Change | Impact | Migration |
|--------|--------|-----------|
| EasyOCR GPU removed from ProcessPool | No multi-process GPU | Single-thread `EasyOCRRuntime` handles GPU |
| Config moved to `app/config.py` | New `PipelineConfig` class | Update imports from `app.shared.config.settings` |
| Removed PaddleOCR/TurboOCR adapters | Only EasyOCR supported | N/A — adapters were unused |
| Result schema normalized for UI | `normalize_pipeline_result_for_ui()` | Use adapter for Streamlit display |

---

*End of Architecture Document*
