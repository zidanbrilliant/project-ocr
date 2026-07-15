# Vision AI - Invoice Verification Agent Service

AI service for Toyota invoice and delivery-note verification. The testing flow is Streamlit upload first; RabbitMQ and PostgreSQL are kept for production mode.

## Testing Mode

```bash
cp .env.example .env
docker compose --profile standalone up --build streamlit
```

Open `http://localhost:8501`, upload a PDF/JPG/PNG, choose `INV` or `DN`, then click `Process`.

Default testing config:

- `RUN_MODE=standalone`
- `ENABLE_RABBITMQ=false`
- `ENABLE_DATABASE=false`
- `OCR_PROVIDER=paddleocr_vl`
- `PADDLEOCR_VL_MODEL_DIR=/mnt/models/PaddleOCR-VL-1.6`

DGX Spark standalone Docker defaults to PaddleOCR-VL. To switch OCR to Qwen, set:

```env
OCR_PROVIDER=qwen
```

To keep PaddleOCR-VL as OCR and still enable optional Qwen reasoning after OCR/YOLO:

```env
OCR_PROVIDER=paddleocr_vl
ENABLE_QWEN_REASONING=true
```

## Pipeline

Streamlit upload -> document validation -> PDF/image rendering -> preprocessing -> OCR provider -> YOLO detection -> barcode decode -> field extraction -> business rules -> confidence score -> UI result.

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
