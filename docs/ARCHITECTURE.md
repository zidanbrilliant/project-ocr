# Vision AI Architecture

Version: 2.2.0
Last updated: 2026-07-15

## Runtime Modes

The project now has two explicit runtime paths.

| Mode | Entry point | RabbitMQ | Database | Purpose |
|---|---|---:|---:|---|
| `standalone` | `scripts/upload_app.py` | off | off by default | DGX testing with direct Streamlit upload |
| `worker` | `app.workers.worker_main` | on | on | production queue processing |

Testing must use `RUN_MODE=standalone`, `ENABLE_RABBITMQ=false`, and `ENABLE_DATABASE=false`. RabbitMQ topology and worker code stay in the repo for production, but they are skipped during Streamlit testing.

## Standalone Testing Flow

```text
Streamlit upload
  -> DirectProcessor
  -> DocumentValidator
  -> PDFRenderer / image input
  -> ImagePreprocessor
  -> DocumentOCR
       -> pypdf text extraction for searchable PDFs, when enabled
       -> NVIDIA Nemotron Parse v1.2 for scanned-page OCR and layout
  -> YOLOAdapter
  -> BarcodeFallbackChain
  -> FieldExtractionService
  -> BusinessRuleEvaluator
  -> ConfidenceScoringService
  -> Streamlit result tabs
```

The only OCR model provider is `nemotron`. Streamlit calls the dedicated `nemotron` container so one process owns the model and GPU memory.

Nemotron uses `NEMOTRON_MODEL_DIR=/mnt/models/Nemotron-Parse-v1.2`, runs with local-only Transformers weights, and returns reading-order text, semantic classes, bounding boxes, and structured blocks. If it cannot load, OCR returns an explicit error and Streamlit shows the failure.

Field extraction and business-rule evaluation remain deterministic; no second VLM is loaded.

## Production Worker Flow

```text
RabbitMQ
  -> InvoiceRequestConsumer
  -> JobProcessor
  -> AIPipelineOrchestrator
  -> ImageServerClient
  -> DocumentValidator / converters / preprocessors
  -> DocumentOCR
  -> YOLOAdapter
  -> BarcodeFallbackChain
  -> field extraction / rules / confidence
  -> PostgreSQL result repositories
  -> outbox publisher
```

Production checks still required before enabling RabbitMQ in production:

- Create real Alembic migrations for the database schema.
- Run the Alembic migrations against a staging database.
- Run integration/load tests with the real RabbitMQ, PostgreSQL, image server, and document corpus.
- Calibrate field and YOLO thresholds using labeled production documents.

## Directory Map

```text
app/
  domain/              business entities, value objects, rules
  application/         use cases, DTOs, orchestration services
  infrastructure/
    barcode/           zxing-cpp, pyzbar, OpenCV barcode chain
    database/          SQLAlchemy models and repositories
    detection/         YOLO adapter and detection mapper
    document_converter PDF/image/Word conversion and preprocessing
    ocr/               DocumentOCR and Nemotron Parse adapter
    rabbitmq/          production broker adapters
    storage/           image server and temp file adapters
  interfaces/          FastAPI routes and schemas
  workers/             production worker entrypoint
  shared/              settings, logging, constants, utilities

scripts/
  upload_app.py        Streamlit testing UI
  direct_processor.py  direct upload pipeline
  result_adapter.py    UI result normalization
```

## DGX Spark Notes

The standalone Docker profile mounts `/mnt/models:/mnt/models:ro` so both model paths are visible in the container.

```bash
docker compose --profile standalone up -d --build
```

For local non-Docker testing:

```bash
streamlit run scripts/upload_app.py
```

The local Python environment must have the pinned Nemotron Transformers dependencies. DGX Docker uses the NGC PyTorch base image and mounts the model read-only from `/mnt/models/Nemotron-Parse-v1.2`.
