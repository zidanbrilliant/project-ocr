from prometheus_client import Counter, Gauge, Histogram

transactions_received = Counter("ai_transactions_received_total", "Transactions received")
transactions_completed = Counter("ai_transactions_completed_total", "Transactions completed")
documents_processed = Counter("ai_documents_processed_total", "Documents processed")
pages_processed = Counter("ai_pages_processed_total", "Pages processed")
page_errors = Counter("ai_page_errors_total", "Page errors")
retries_total = Counter("ai_retries_total", "Retries")
dlq_messages = Counter("ai_dlq_messages_total", "DLQ messages")
detections_total = Counter("ai_detections_total", "Detections")

transaction_duration = Histogram("ai_transaction_duration_seconds", "Transaction duration", buckets=[1, 5, 10, 30, 60, 120, 300, 600])
download_duration = Histogram("ai_download_duration_seconds", "Download duration", buckets=[1, 5, 10, 30, 60])
render_duration = Histogram("ai_render_duration_seconds", "Render duration", buckets=[1, 5, 10, 30, 60, 120])
yolo_inference = Histogram("ai_yolo_inference_seconds", "YOLO inference duration", buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5])
ocr_inference = Histogram("ai_ocr_inference_seconds", "OCR inference duration", buckets=[0.5, 1, 2, 5, 10, 30, 60])
publish_duration = Histogram("ai_publish_duration_seconds", "Publish duration", buckets=[0.1, 0.5, 1, 2, 5])

jobs_in_progress = Gauge("ai_jobs_in_progress", "Jobs in progress")
pages_in_progress = Gauge("ai_pages_in_progress", "Pages in progress")
yolo_queue_depth = Gauge("ai_yolo_queue_depth", "YOLO queue depth")
ocr_queue_depth = Gauge("ai_ocr_queue_depth", "OCR queue depth")
gpu_memory_used = Gauge("ai_gpu_memory_used_bytes", "GPU memory used bytes")
gpu_utilization = Gauge("ai_gpu_utilization_percent", "GPU utilization percent")
