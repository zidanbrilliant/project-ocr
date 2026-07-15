import asyncio
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import streamlit as st

from app.shared.config.settings import settings
from scripts.direct_processor import DirectProcessor
from scripts.result_adapter import normalize_pipeline_result_for_ui

st.set_page_config(page_title="Vision AI", page_icon="VI", layout="wide")

DOC_TYPES = {"INV": "Invoice", "DN": "Delivery Note"}

DEFAULT_STATE = {
    "raw_result": None,
    "ui_result": None,
    "processing_error": None,
    "processing_done": False,
    "processing_time_ms": None,
    "uploaded_file_hash": None,
    "selected_page_index": 0,
}


def init_state() -> None:
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_processing_state() -> None:
    for key in DEFAULT_STATE:
        st.session_state.pop(key, None)
    init_state()


@st.cache_resource(show_spinner=False)
def get_processor() -> DirectProcessor:
    return DirectProcessor()


def draw_bboxes(img: np.ndarray, detections: list[dict], color=(0, 160, 90)) -> np.ndarray:
    vis = img.copy()
    for detection in detections:
        bbox = detection.get("bbox", [])
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            conf = detection.get("confidence", 0)
            label = f"{detection.get('label', '?')} {conf:.1f}%"
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            cv2.putText(vis, label, (x1, max(y1 - 5, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return vis


async def main_ui() -> None:
    init_state()
    st.title("Vision AI Document Inspector")

    with st.sidebar:
        st.subheader("Runtime")
        st.caption(f"Mode: {settings.RUN_MODE}")
        st.caption(f"OCR Provider: {settings.OCR_PROVIDER}")
        st.caption(f"Database: {'enabled' if settings.ENABLE_DATABASE else 'disabled'}")
        st.caption(f"RabbitMQ: {'enabled' if settings.ENABLE_RABBITMQ else 'disabled'}")

        processor = get_processor()
        _render_model_status(processor)

        st.divider()
        if st.button("Clear Results", use_container_width=True):
            clear_processing_state()
            st.rerun()

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Upload Document")
        uploaded = st.file_uploader("Choose PDF, JPG, or PNG", type=["pdf", "jpg", "jpeg", "png"])
        doc_type = st.selectbox("Document Type", options=list(DOC_TYPES.keys()), format_func=lambda x: DOC_TYPES[x])

        if st.button("Process", type="primary", disabled=uploaded is None, use_container_width=True):
            await _process_uploaded_file(uploaded, doc_type)

    ui_result = st.session_state.get("ui_result")
    with col_right:
        if st.session_state.get("processing_error"):
            st.error(st.session_state.processing_error)

        if ui_result is None:
            st.info("Upload a document and click Process.")
            return

        _display_results(ui_result)


def _render_model_status(processor: DirectProcessor) -> None:
    ocr = processor._ocr
    provider = getattr(ocr, "_provider", settings.OCR_PROVIDER)

    if provider == "qwen":
        qwen = getattr(ocr, "_qwen", None)
        if getattr(qwen, "_available", False):
            st.success("Qwen2.5-VL OCR: ready")
        else:
            st.warning(f"Qwen2.5-VL OCR: not loaded ({getattr(qwen, '_load_error', 'warmup pending')})")

    if provider == "paddleocr_vl":
        paddle = getattr(ocr, "_paddle", None)
        if getattr(paddle, "_available", False):
            st.success("PaddleOCR-VL: ready")
        else:
            st.warning(f"PaddleOCR-VL: not loaded ({getattr(paddle, '_load_error', 'warmup pending')})")

    yolo_loaded = getattr(processor._yolo, "_loaded", False)
    if yolo_loaded:
        st.success("YOLO: ready")
    else:
        st.warning("YOLO: not loaded")


async def _process_uploaded_file(uploaded, doc_type: str) -> None:
    with st.spinner("Processing document..."):
        processor = get_processor()
        await processor.warmup()

        uploaded_bytes = uploaded.getvalue()
        if not uploaded_bytes:
            st.session_state.processing_error = "Uploaded file is empty."
            return

        file_hash = hashlib.sha256(uploaded_bytes).hexdigest()
        file_name = uploaded.name
        content_type = uploaded.type or ""
        file_size = len(uploaded_bytes)

        try:
            started = time.perf_counter()
            raw_result = await processor.process(uploaded_bytes, file_name, doc_type)
            elapsed = round((time.perf_counter() - started) * 1000)

            ui_result = normalize_pipeline_result_for_ui(
                raw_result=raw_result,
                file_name=file_name,
                content_type=content_type,
                file_size_bytes=file_size,
                processing_time_ms=elapsed,
            )

            st.session_state.raw_result = raw_result
            st.session_state.ui_result = ui_result
            st.session_state.processing_time_ms = elapsed
            st.session_state.processing_done = True
            st.session_state.processing_error = None
            st.session_state.uploaded_file_hash = file_hash
            st.session_state.selected_page_index = 0
        except Exception as exc:
            st.session_state.processing_error = str(exc)
        st.rerun()


def _display_results(ui_result: dict) -> None:
    pages = ui_result.get("pages", [])
    if not pages:
        st.error("No pages in result.")
        return

    doc = ui_result.get("document", {})
    total_pages = len(pages)
    selected_index = min(st.session_state.selected_page_index, total_pages - 1)
    selected_index = st.selectbox(
        "Page",
        options=list(range(total_pages)),
        index=selected_index,
        format_func=lambda i: f"Page {pages[i]['page_number']} of {total_pages}",
        key="selected_page_index",
    )
    selected_page = pages[selected_index]

    st.caption(
        f"Status: {ui_result['status']} | "
        f"Time: {ui_result['processing_time_ms']}ms | "
        f"{doc.get('file_name', '')} | "
        f"{doc.get('size_kb', 0)} KB"
    )

    preview_tab, ocr_tab, detection_tab, fields_tab, confidence_tab = st.tabs(
        ["Preview", "OCR", "Detection", "Fields", "Confidence"]
    )

    with preview_tab:
        _render_preview(selected_page, pages)
    with ocr_tab:
        _render_ocr(selected_page)
    with detection_tab:
        _render_detection(selected_page, selected_index)
    with fields_tab:
        _render_fields(selected_page)
    with confidence_tab:
        _render_confidence(ui_result, selected_page)


def _render_preview(page: dict, pages: list) -> None:
    cols = st.columns(4)
    cols[0].metric("Extension", page.get("extension", "?"))
    cols[1].metric("Pages", len(pages))
    cols[2].metric("Status", page.get("status", "?"))
    cols[3].metric("Page", page.get("page_number", "?"))

    preview = page.get("preview")
    if preview and preview.get("image_bytes"):
        st.image(preview["image_bytes"], caption=f"Page {page['page_number']}", width=800)
    else:
        st.caption(f"Page {page['page_number']}: no preview")


def _render_ocr(page: dict) -> None:
    ocr = page.get("ocr", {})
    raw_text = ocr.get("raw_text", "")
    if not raw_text or raw_text == "(empty)":
        raw_text = ""

    if ocr.get("status") == "FAILED":
        st.error(f"OCR failed: {ocr.get('error') or 'selected OCR provider returned no text'}")

    st.text_area("Raw Text", raw_text or "(empty)", height=320)
    cols = st.columns(3)
    cols[0].metric("Engine", ocr.get("engine", "?"))
    cols[1].metric("Avg Confidence", f"{ocr.get('avg_confidence', 0)}%")
    cols[2].metric("Status", ocr.get("status", "?"))

    blocks = ocr.get("blocks", [])
    if blocks:
        with st.expander(f"Blocks ({len(blocks)})"):
            st.json(blocks[:30])


def _render_detection(page: dict, idx: int) -> None:
    detections = page.get("detections", [])
    aggregated = page.get("detection_aggregated", {})

    if aggregated:
        st.subheader("Detection Summary")
        st.table(
            [
                {
                    "Object": obj_type,
                    "Result": info.get("result", "?"),
                    "Confidence": f"{info.get('confidence', 0):.1f}%",
                }
                for obj_type, info in aggregated.items()
            ]
        )

    if detections:
        st.subheader("All Detections")
        st.table(
            [
                {
                    "Label": detection.get("label", "?"),
                    "Confidence": f"{detection.get('confidence', 0):.1f}%",
                    "Page": detection.get("page_number", idx + 1),
                }
                for detection in detections
            ]
        )

    preview = page.get("preview")
    if preview and preview.get("image_bytes") is not None:
        arr = np.frombuffer(preview["image_bytes"], dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            st.image(draw_bboxes(img, detections), caption=f"Detections - Page {page['page_number']}", width=800)
            return
    st.caption("Preview not available for annotation.")


def _render_fields(page: dict) -> None:
    fields = page.get("fields", {})
    if not fields:
        st.warning("No fields extracted.")
        return

    rows = []
    for name, field_data in fields.items():
        value = field_data.get("value", "-")
        confidence = field_data.get("confidence", "-")
        rows.append(
            {
                "Field": name,
                "Value": str(value),
                "Confidence": f"{confidence}%" if isinstance(confidence, (int, float)) else confidence,
            }
        )
    st.table(rows)


def _render_confidence(ui_result: dict, page: dict) -> None:
    raw = ui_result.get("pipeline_raw", {})
    st.metric("Total Confidence", f"{raw.get('total_confidence', 'N/A')}%")
    st.metric("Has OCR", "yes" if raw.get("has_ocr") else "no")
    st.metric("Has Detection", "yes" if raw.get("has_detection") else "no")
    st.metric("Overall Status", ui_result.get("status", "?"))
    st.metric("Processing Time", f"{ui_result.get('processing_time_ms', 0)}ms")

    detections = page.get("detections") or []
    if detections:
        avg_conf = sum(d.get("confidence", 0) for d in detections) / len(detections)
        st.metric("Avg Detection Confidence", f"{avg_conf:.1f}%")


if __name__ == "__main__":
    asyncio.run(main_ui())
