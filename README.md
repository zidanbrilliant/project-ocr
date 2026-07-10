# Vision AI — Invoice Verification Agent Service

AI Agent Service for Toyota invoice verification. Clean Architecture Python 3.11, PaddleOCR-VL 1.6, YOLO, RabbitMQ, PostgreSQL.

## Quick Start

```bash
cp .env.example .env
docker compose up -d postgres rabbitmq
alembic upgrade head
docker compose up app-api ai-worker
```

## Architecture

Clean Architecture (section 8 PRD): Domain → Application → Infrastructure → Interfaces/Workers.

Key adapters: PaddleOCR-VL 1.6 (primary), EasyOCR/Tesseract (fallback), Ultralytics YOLO, zxing-cpp/pyzbar/OpenCV (barcode).

## Pipeline

Receive msg → validate payload → download doc → validate doc → convert → OCR (PaddleOCR-VL) → YOLO detect → barcode decode → extract fields → business rules → confidence score → build result → publish → ack.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/api/v1/jobs/{queue_id}/status` | GET | Job status |
| `/api/v1/jobs/{queue_id}/result` | GET | Job result |
| `/api/v1/jobs/{queue_id}/reprocess` | POST | Reprocess job |
| `/api/v1/models/version` | GET | Model versions |
| `/metrics` | GET | Prometheus metrics |

## Config

All via env vars (see `.env.example`). Key vars: `DATABASE_URL`, `RABBITMQ_URL`, `YOLO_MODEL_PATH`, `OCR_USE_GPU`.

## Test

```bash
pytest tests/
```
