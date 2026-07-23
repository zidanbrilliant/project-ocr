# Vision AI - Invoice Verification Agent Service

AI service for Toyota invoice and delivery-note verification. Local Streamlit
and benchmark flows exercise the shared processing service without connecting
RabbitMQ or PostgreSQL.

## Local End-to-End Testing

Start the Streamlit background-job tester from the repository root:

```bash
streamlit run scripts/upload_app.py
```

Streamlit submits uploads to an in-memory local job, polls its progress, and
displays the validated canonical JSON result. This tests the local model
pipeline; it is not a RabbitMQ or PostgreSQL integration test.

Run the labeled field and YOLO validation benchmark with:

```bash
python scripts/benchmark_pipeline.py "dataset groundtruth" --ground-truth "dataset groundtruth/ground_truth.json" --yolo-dataset-root "dataset yolo" --output artifacts/benchmark-local.json --require-yolo-gate
```

The command writes `artifacts/benchmark-local.json` before returning the gate
result. Exit code `0` means all requested 85% field and 90% YOLO gates pass;
exit code `2` means the report was written but at least one requested gate
failed. Barcode decoding and color inspection remain output-only with
no acceptance gate until labeled ground truth exists.

## DGX Docker Testing

```bash
cp .env.example .env
docker compose --profile standalone up -d --build
```

Open `http://localhost:8502` locally, or `http://<DGX-IP>:8502` from your laptop, upload one or more PDF/JPG/PNG files, choose `INV` or `DN`, then click `Process`.

Default testing config:

- `RUN_MODE=standalone`
- `ENABLE_RABBITMQ=false`
- `ENABLE_DATABASE=false`
- `OCR_PROVIDER=nemotron`
- `NEMOTRON_SERVICE_URL=http://nemotron:8000` (in Compose)

Every Streamlit upload now shows the canonical result JSON in **Result JSON**,
offers it for download, and saves the same payload in `artifacts/results/`.
This is the payload shape intended for the RabbitMQ result flow; it is kept
additive so fields can evolve without breaking testing.

DGX Spark standalone Docker starts one shared NVIDIA Nemotron Parse service. The model
directory configured by `NEMOTRON_MODEL_DIR` must exist under `/mnt/models`.
Streamlit remains accessible and reports OCR unavailable when the model is absent.

## Pipeline

Streamlit upload -> document validation -> PDF/image rendering -> OCR provider -> YOLO detection -> barcode decode -> field extraction -> business rules -> canonical JSON -> UI result.

Production mode keeps the RabbitMQ worker path:

RabbitMQ -> request normalizer -> AI pipeline orchestrator -> PostgreSQL result/outbox -> result publisher.

## Main Adapters

- OCR: native PDF text extraction plus NVIDIA Nemotron Parse v1.2 for scanned pages
- Detection: Ultralytics YOLO
- Barcode: zxing-cpp, pyzbar, OpenCV fallback chain
- UI: Streamlit direct upload

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/api/v1/jobs/{queue_id}/status` | GET | Job status |
| `/api/v1/jobs/{queue_id}/result` | GET | Job result |
| `/api/v1/jobs/{queue_id}/reprocess` | POST | Reprocess job |
| `/metrics` | GET | Prometheus metrics |

## Test

```bash
python -m compileall app scripts
pytest tests/unit
```

Benchmark a labeled/sample corpus on DGX after the model paths are mounted:

```bash
docker compose --profile standalone exec streamlit python scripts/benchmark_pipeline.py samples
```
