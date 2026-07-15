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
       -> PaddleOCR-VL or Qwen2.5-VL for page OCR
  -> YOLOAdapter
  -> BarcodeFallbackChain
  -> FieldExtractionService
  -> BusinessRuleEvaluator
  -> ConfidenceScoringService
  -> Streamlit result tabs
```

The selected OCR provider is controlled by `OCR_PROVIDER`. DGX Spark standalone Docker defaults to `paddleocr_vl`.

| Provider | Value | Model path |
|---|---|---|
| PaddleOCR-VL | `paddleocr_vl` | `PADDLEOCR_VL_MODEL_DIR=/mnt/models/PaddleOCR-VL-1.6` |
| Qwen2.5-VL | `qwen` | `VLM_MODEL_PATH=/mnt/models/Qwen2.5-VL-7B-Instruct-AWQ` |

Use `qwen` only when the Qwen/vLLM runtime is available.

EasyOCR is not part of the testing pipeline. If the selected provider cannot load, OCR returns an explicit error and the Streamlit UI shows the failure.

## Optional Reasoning

Qwen reasoning is controlled separately with `ENABLE_QWEN_REASONING`.

When disabled, the pipeline uses deterministic field extraction and business rules only. When enabled, `DirectProcessor` warms up a Qwen adapter and adds a `reasoning` block to the raw result based on page image, OCR text, extracted fields, and YOLO detections.

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

Known production hardening still required before enabling RabbitMQ in production:

- Create real Alembic migrations for the database schema.
- Ensure worker creates and commits `AIJob` before child result rows.
- Remove non-JSON values from RabbitMQ payload persistence.
- Use per-message database sessions and commits.
- Add integration tests with RabbitMQ/PostgreSQL.

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
    ocr/               DocumentOCR, PaddleOCR-VL, Qwen2.5-VL
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
docker compose --profile standalone up --build streamlit
```

For local non-Docker testing:

```bash
streamlit run scripts/upload_app.py
```

The local Python environment must already have the correct vLLM or PaddleOCR/PaddlePaddle packages for the selected provider. On DGX Spark `aarch64`, the default standalone provider is PaddleOCR-VL.
