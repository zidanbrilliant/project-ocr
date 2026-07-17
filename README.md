# Vision AI - Invoice Verification Agent Service

AI service for Toyota invoice and delivery-note verification. The testing flow is Streamlit upload first; RabbitMQ and PostgreSQL are kept for production mode.

## Testing Mode

```bash
cp .env.example .env
docker compose --profile standalone up --build streamlit
```

Open `http://localhost:8501` on DGX, or `http://<DGX-IP>:8502` from your laptop, upload a PDF/JPG/PNG, choose `INV` or `DN`, then click `Process`.

Default testing config:

- `RUN_MODE=standalone`
- `ENABLE_RABBITMQ=false`
- `ENABLE_DATABASE=false`
- `OCR_PROVIDER=paddleocr_vl`
- `ENABLE_QWEN_REASONING=false`
- `QWEN_SERVICE_URL=http://qwen:8000`

Every Streamlit upload now shows the canonical result JSON in **Result JSON**,
offers it for download, and saves the same payload in `artifacts/results/`.
This is the payload shape intended for the RabbitMQ result flow; it is kept
additive so fields can evolve without breaking testing.

DGX Spark standalone Docker defaults to PaddleOCR-VL OCR.

## Pipeline

Streamlit upload -> document validation -> PDF/image rendering -> OCR provider -> YOLO detection -> barcode decode -> field extraction -> business rules -> canonical JSON -> UI result.

Production mode keeps the RabbitMQ worker path:

RabbitMQ -> request normalizer -> AI pipeline orchestrator -> PostgreSQL result/outbox -> result publisher.

## Main Adapters

- OCR: `DocumentOCR` with explicit provider `paddleocr_vl` or `qwen`
- PaddleOCR-VL: default standalone OCR adapter
- Qwen2.5-VL: optional reasoning adapter
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
