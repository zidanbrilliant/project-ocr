import asyncio
import os
import tempfile
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from app.config import config
from app.inference.easyocr_runtime import EasyOCRRuntime
from app.inference.yolo_batcher import YoloBatcher, YoloRequest
from app.inference.yolo_runtime import YoloRuntime
from app.observability.logging import get_logger, setup_logging
from app.rendering.pdf_renderer import inspect_pdf, render_page
from app.storage.local_storage import LocalStorage

logger = get_logger(__name__)


class StreamlitProcessor:
    """Parallel processor for Streamlit. Uses: persistent pools, asyncio.gather, YOLO batcher."""

    def __init__(self) -> None:
        setup_logging()
        self._yolo_runtime = YoloRuntime()
        self._yolo_batcher: YoloBatcher | None = None
        self._easyocr_gpu = EasyOCRRuntime()
        self._render_pool: ProcessPoolExecutor | None = None
        self._storage = LocalStorage()
        self._warmed_up = False

    async def warmup(self) -> None:
        if self._warmed_up:
            return
        logger.info("streamlit_processor_warmup_start")

        try:
            self._yolo_runtime.load()
            self._yolo_runtime.warmup()
            logger.info("yolo_warmup_done")
        except Exception as e:
            logger.warning("yolo_warmup_failed", error=str(e))

        self._yolo_batcher = YoloBatcher(self._yolo_runtime)
        await self._yolo_batcher.start()

        self._easyocr_gpu.load()

        self._render_pool = ProcessPoolExecutor(max_workers=config.RENDER_PROCESS_WORKERS)

        self._warmed_up = True
        logger.info("streamlit_processor_warmup_done")

    async def process(self, file_bytes: bytes, filename: str, doc_type: str = "INV") -> dict[str, Any]:
        t0 = time.monotonic()
        queue_id = f"ST-{uuid.uuid4().hex[:8]}"
        doc_id = "DOC-001"

        result: dict[str, Any] = {
            "status": "error", "processing_time_ms": 0, "error": None,
            "pages": [], "detections": [], "detection_aggregated": {},
            "ocr": {}, "fields": {}, "confidence": {}, "remarks": "",
        }

        try:
            tmpdir = tempfile.mkdtemp(prefix="st_")
            file_path = os.path.join(tmpdir, filename)
            with open(file_path, "wb") as f:
                f.write(file_bytes)

            inspect = inspect_pdf(file_path)
            if inspect.get("status") == "FAILED":
                raise ValueError(f"PDF invalid: {inspect.get('error')}")

            page_infos = inspect.get("pages", [])
            doc_dir = os.path.join(tmpdir, doc_id)
            os.makedirs(doc_dir, exist_ok=True)

            # Render pages in parallel via persistent process pool
            render_args = [
                {"file_path": file_path, "page_index": pi["page_index"],
                 "document_id": doc_id, "output_dir": doc_dir, "dpi": config.PDF_DEFAULT_DPI}
                for pi in page_infos
            ]
            loop = asyncio.get_event_loop()
            page_metas = await loop.run_in_executor(
                None, lambda: list(self._render_pool.map(render_page, render_args))
            )

            # Decode page images for Streamlit preview
            preview_images = []
            for pm in page_metas:
                if pm.get("status") == "SUCCESS":
                    import cv2
                    img = cv2.imread(pm["image_path"])
                    if img is not None:
                        preview_images.append(img)
            result["pages"] = preview_images

            # Process all pages in PARALLEL via asyncio.gather
            async def process_page(pm: dict) -> dict:
                if pm.get("status") != "SUCCESS":
                    return {"page_index": pm["page_index"], "detections": [], "ocr": None}

                img_path = pm["image_path"]

                yolo_req = YoloRequest(
                    transaction_id=queue_id, document_id=doc_id,
                    document_index=0, page_index=pm["page_index"],
                    image_path=img_path,
                )
                yolo_dets = await self._yolo_batcher.submit(yolo_req)

                ocr_res = await asyncio.to_thread(self._easyocr_gpu.read, img_path)

                return {
                    "page_index": pm["page_index"],
                    "page_number": pm["page_number"],
                    "yolo_dets": yolo_dets,
                    "ocr": ocr_res,
                }

            page_results = await asyncio.gather(*[process_page(pm) for pm in page_metas])

            # Aggregate results
            all_dets = []
            agg_map: dict[str, dict] = {}
            last_ocr = None
            for pr in page_results:
                if pr.get("ocr"):
                    last_ocr = pr["ocr"]
                for d in pr.get("yolo_dets", []):
                    det_item = {
                        "object_type": d.get("label", ""),
                        "class_id": d.get("class_id"),
                        "confidence": round(d.get("confidence", 0) * 100, 2),
                        "bounding_box": d.get("bbox_pixel_xyxy", []),
                        "page_number": pr.get("page_number", 1),
                    }
                    all_dets.append(det_item)
                    key = d.get("label", "")
                    if key not in agg_map or d.get("confidence", 0) > agg_map[key].get("conf", 0):
                        agg_map[key] = {
                            "object_type": key,
                            "result": "OK" if d.get("confidence", 0) > 0.25 else "NG",
                            "confidence": round(d.get("confidence", 0) * 100, 2),
                        }

            result["detections"] = all_dets
            result["detection_aggregated"] = agg_map
            result["ocr"] = last_ocr or {}
            result["status"] = "OK"
            result["remarks"] = "Processing completed via parallel pipeline"
            result["processing_time_ms"] = int((time.monotonic() - t0) * 1000)

        except Exception as e:
            logger.exception("streamlit_process_failed")
            result["error"] = str(e)
            result["processing_time_ms"] = int((time.monotonic() - t0) * 1000)

        return result

    async def close(self) -> None:
        if self._yolo_batcher:
            await self._yolo_batcher.stop()
        if self._ocr_pool:
            self._ocr_pool.shutdown(wait=True)
        if self._render_pool:
            self._render_pool.shutdown(wait=True)
        self._storage.cleanup_all()
