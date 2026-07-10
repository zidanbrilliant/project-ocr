import asyncio
import concurrent.futures
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.config import config
from app.inference.yolo_batcher import YoloBatcher, YoloRequest
from app.inference.yolo_runtime import YoloRuntime
from app.inference.ocr_runtime import init_ocr_worker, run_ocr
from app.observability.logging import get_logger, bind_context, clear_context, setup_logging
from app.observability.metrics import (
    transactions_received, transactions_completed,
    documents_processed, pages_processed, page_errors,
    jobs_in_progress, pages_in_progress,
    yolo_queue_depth, ocr_queue_depth,
)
from app.observability.tracing import set_trace_id, get_trace_id
from app.postprocessing.coordinate_mapper import convert_bbox
from app.rendering.pdf_renderer import inspect_pdf, render_page
from app.storage.local_storage import LocalStorage

logger = get_logger(__name__)


class TransactionProcessor:
    def __init__(
        self,
        yolo_runtime: YoloRuntime,
        yolo_batcher: YoloBatcher,
        ocr_pool: ProcessPoolExecutor,
        render_pool: ProcessPoolExecutor | None,
        storage: LocalStorage,
    ) -> None:
        self._yolo_runtime = yolo_runtime
        self._yolo_batcher = yolo_batcher
        self._ocr_pool = ocr_pool
        self._render_pool = render_pool
        self._storage = storage

        self._document_sem = asyncio.Semaphore(config.DOCUMENT_CONCURRENCY)
        self._download_sem = asyncio.Semaphore(config.DOWNLOAD_CONCURRENCY)

    async def process_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = set_trace_id()
        queue_id = payload.get("QUEUE_ID") or str(uuid.uuid4())
        trans_id = payload.get("PV_NO", queue_id)
        bind_context(transaction_id=trans_id, queue_id=queue_id, trace_id=trace_id)

        jobs_in_progress.inc()
        transactions_received.inc()
        t_start = time.monotonic()

        result: dict[str, Any] = {
            "schema_version": "1.0.0",
            "pipeline_version": "vision-pipeline-2026.07",
            "queue_id": queue_id,
            "transaction_id": trans_id,
            "correlation_id": trans_id,
            "status": "SUCCESS",
            "received_at": datetime.now(tz=timezone.utc).isoformat(),
            "completed_at": "",
            "processing_time_ms": 0,
            "validation_summary": {
                "total_documents": 0,
                "successful_documents": 0,
                "partial_documents": 0,
                "failed_documents": 0,
                "total_pages": 0,
                "successful_pages": 0,
                "failed_pages": 0,
                "is_complete": False,
            },
            "models": {
                "object_detection": {"name": "document-yolo", "version": "sesi_4", "device": "cuda"},
                "ocr": {"name": config.OCR_ENGINE, "version": "1.0", "device": "gpu" if config.OCR_USE_GPU else "cpu"},
            },
            "documents": [],
            "errors": [],
            "trace": {"trace_id": trace_id, "request_id": queue_id},
        }

        trans_dir = self._storage.create_transaction_dir(trans_id)

        try:
            async with asyncio.timeout(config.TRANSACTION_TIMEOUT_SECONDS):
                documents = self._parse_documents(payload)
                result["validation_summary"]["total_documents"] = len(documents)

                doc_tasks = [
                    self._process_document(doc, trans_dir, trans_id)
                    for doc in documents
                ]
                doc_results = await asyncio.gather(*doc_tasks, return_exceptions=True)

                for doc_idx, doc_res in enumerate(doc_results):
                    if isinstance(doc_res, Exception):
                        result["documents"].append({
                            "document_id": documents[doc_idx].get("document_id", f"DOC-{doc_idx:03d}"),
                            "document_index": doc_idx,
                            "status": "FAILED",
                            "errors": [{"stage": "PROCESSING", "code": "INTERNAL_ERROR", "message": str(doc_res)}],
                        })
                        result["validation_summary"]["failed_documents"] += 1
                    else:
                        result["documents"].append(doc_res)

            # Calculate summary
            summary = result["validation_summary"]
            for doc in result["documents"]:
                s = doc.get("status", "FAILED")
                if s == "SUCCESS":
                    summary["successful_documents"] += 1
                elif s == "PARTIAL_SUCCESS":
                    summary["partial_documents"] += 1
                else:
                    summary["failed_documents"] += 1
                for page in doc.get("pages", []):
                    summary["total_pages"] += 1
                    if page.get("status") == "SUCCESS":
                        summary["successful_pages"] += 1
                    else:
                        summary["failed_pages"] += 1
            summary["is_complete"] = summary["failed_pages"] == 0

            # Determine overall status
            if summary["failed_documents"] == summary["total_documents"]:
                result["status"] = "FAILED"
            elif summary["failed_documents"] > 0 or summary["failed_pages"] > 0:
                result["status"] = "PARTIAL_SUCCESS"

        except asyncio.TimeoutError:
            result["status"] = "FAILED"
            result["errors"].append({"stage": "TRANSACTION", "code": "TIMEOUT", "message": f"Transaction exceeded {config.TRANSACTION_TIMEOUT_SECONDS}s"})
        except Exception as e:
            logger.exception("transaction_failed")
            result["status"] = "FAILED"
            result["errors"].append({"stage": "TRANSACTION", "code": "INTERNAL_ERROR", "message": str(e)})

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        result["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        result["processing_time_ms"] = elapsed_ms

        jobs_in_progress.dec()
        transactions_completed.inc()
        logger.info("transaction_complete", status=result["status"], duration_ms=elapsed_ms)
        clear_context()
        return result

    def _parse_documents(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract documents from payload. Single-doc or multi-doc format."""
        docs = payload.get("documents", [])
        if not docs:
            docs = [{
                "document_id": "DOC-001",
                "doc_no": payload.get("DOC_NO", ""),
                "doc_type": payload.get("DOC_TYPE", "INV"),
                "doc_seq": payload.get("DOC_SEQ", 1),
                "file_name": payload.get("FILE_NM", ""),
                "source_uri": payload.get("PATH_FILE", ""),
            }]
        for i, d in enumerate(docs):
            d.setdefault("document_index", i)
        return docs

    async def _process_document(self, doc: dict[str, Any], trans_dir: str, trans_id: str) -> dict[str, Any]:
        async with self._document_sem:
            doc_id = doc.get("document_id", f"DOC-{doc['document_index']:03d}")
            doc_dir = self._storage.create_document_dir(trans_dir, doc_id)
            bind_context(document_id=doc_id)

            doc_result: dict[str, Any] = {
                "document_id": doc_id,
                "document_index": doc["document_index"],
                "doc_no": doc.get("doc_no", ""),
                "doc_type": doc.get("doc_type", ""),
                "file_name": doc.get("file_name", ""),
                "source_uri": doc.get("source_uri", ""),
                "status": "SUCCESS",
                "page_count": 0,
                "processing_time_ms": 0,
                "pages": [],
                "errors": [],
            }
            t_doc_start = time.monotonic()

            try:
                file_bytes = await self._download_document(doc["source_uri"])
                file_path = self._storage.save_temp_file(file_bytes, doc_dir, doc.get("file_name", "document.pdf"))
                documents_processed.inc()

                inspect_result = inspect_pdf(file_path)
                if inspect_result.get("status") == "FAILED":
                    raise ValueError(f"PDF inspect failed: {inspect_result.get('error')}")

                page_infos = inspect_result.get("pages", [])
                doc_result["page_count"] = len(page_infos)

                # Render pages via ProcessPoolExecutor
                render_tasks = []
                for pi in page_infos:
                    render_tasks.append({
                        "file_path": file_path,
                        "page_index": pi["page_index"],
                        "document_id": doc_id,
                        "output_dir": doc_dir,
                        "dpi": config.PDF_DEFAULT_DPI,
                    })

                loop = asyncio.get_event_loop()
                pool = self._render_pool or ProcessPoolExecutor(max_workers=config.RENDER_PROCESS_WORKERS)
                need_cleanup = self._render_pool is None
                try:
                    page_metas = await loop.run_in_executor(
                        None, lambda: list(pool.map(render_page, render_tasks))
                    )
                finally:
                    if need_cleanup:
                        pool.shutdown(wait=False)

                pages_in_progress.inc(len(page_metas))

                # Process each page through YOLO + OCR
                page_results = await self._process_pages(page_metas, doc_id, doc["document_index"], trans_id)

                for pr in page_results:
                    doc_result["pages"].append(pr)
                    if pr.get("status") == "SUCCESS":
                        pages_processed.inc()
                    else:
                        page_errors.inc()

                doc_result["status"] = "SUCCESS" if all(p.get("status") == "SUCCESS" for p in page_results) else "PARTIAL_SUCCESS"
                if not page_results:
                    doc_result["status"] = "FAILED"

            except Exception as e:
                logger.exception("document_failed", document_id=doc_id)
                doc_result["status"] = "FAILED"
                doc_result["errors"].append({"stage": "PROCESSING", "code": "INTERNAL_ERROR", "message": str(e)})

            elapsed = int((time.monotonic() - t_doc_start) * 1000)
            doc_result["processing_time_ms"] = elapsed
            pages_in_progress.dec(doc_result["page_count"] or 0)
            return doc_result

    async def _download_document(self, uri: str) -> bytes:
        async with self._download_sem:
            import httpx
            async with httpx.AsyncClient(timeout=config.DOWNLOAD_TIMEOUT_SECONDS) as client:
                resp = await client.get(uri)
                resp.raise_for_status()
                return resp.content

    async def _process_pages(
        self,
        page_metas: list[dict[str, Any]],
        doc_id: str,
        doc_idx: int,
        trans_id: str,
    ) -> list[dict[str, Any]]:
        page_results: list[dict[str, Any]] = [None] * len(page_metas)

        async def process_one_page(page_meta: dict[str, Any], p_idx: int) -> dict[str, Any]:
            bind_context(page_number=page_meta["page_number"])
            pr: dict[str, Any] = {
                "page_index": page_meta["page_index"],
                "page_number": page_meta["page_number"],
                "status": "FAILED",
                "image": {
                    "width": page_meta.get("image_width", 0),
                    "height": page_meta.get("image_height", 0),
                    "dpi": page_meta.get("dpi", config.PDF_DEFAULT_DPI),
                    "rotation": page_meta.get("rotation", 0),
                },
                "timings_ms": {},
                "detections": [],
                "ocr": None,
                "errors": [],
            }

            try:
                t = pr["timings_ms"]
                img_path = page_meta["image_path"]

                # YOLO (batched GPU)
                t_yolo_start = time.monotonic()
                yolo_req = YoloRequest(
                    transaction_id=trans_id,
                    document_id=doc_id,
                    document_index=doc_idx,
                    page_index=page_meta["page_index"],
                    image_path=img_path,
                )
                yolo_dets = await self._yolo_batcher.submit(yolo_req)
                t["yolo_queue_wait"] = int((time.monotonic() - t_yolo_start) * 1000)
                t["yolo_inference"] = 0  # part of batch time

                # OCR (process pool)
                t_ocr_start = time.monotonic()
                ocr_result = await asyncio.get_event_loop().run_in_executor(
                    self._ocr_pool, run_ocr, img_path
                )
                t["ocr_inference"] = int((time.monotonic() - t_ocr_start) * 1000)

                # Postprocess: coordinate mapping
                iw = page_meta.get("image_width", 1)
                ih = page_meta.get("image_height", 1)
                pw = page_meta.get("page_width_pt", 595.0)
                ph = page_meta.get("page_height_pt", 842.0)
                rot = page_meta.get("rotation", 0)

                detections_out = []
                for d in yolo_dets:
                    bbox = convert_bbox(d.get("bbox_pixel_xyxy", []), iw, ih, pw, ph, rot)
                    detections_out.append({
                        "class_id": d["class_id"],
                        "label": d["label"],
                        "confidence": d["confidence"],
                        "bbox": bbox,
                    })
                pr["detections"] = detections_out
                pr["ocr"] = ocr_result
                pr["status"] = "SUCCESS"

            except Exception as e:
                logger.exception("page_failed", page_number=page_meta.get("page_number"))
                pr["status"] = "FAILED"
                pr["errors"].append({"stage": "PROCESSING", "code": "PAGE_ERROR", "message": str(e)})

            return pr

        tasks = [process_one_page(pm, i) for i, pm in enumerate(page_metas)]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x["page_index"])
        return results
