import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import numpy as np
import cv2

from scripts.direct_processor import DirectProcessor
from scripts.result_adapter import normalize_pipeline_result_for_ui

st.set_page_config(page_title="Vision AI", page_icon="🔍", layout="wide")

DOC_TYPES = {"INV": "Invoice", "DN": "Delivery Note"}

DEFAULT_STATE = {
    "raw_result": None,
    "ui_result": None,
    "processing_error": None,
    "processing_done": False,
    "processing_time_ms": None,
    "uploaded_file_hash": None,
    "selected_page_index": 0,
    "artifact_directory": None,
    "active_view": "Preview",
}


def init_state():
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_processing_state():
    for key in DEFAULT_STATE:
        st.session_state.pop(key, None)
    init_state()


_processor_instance = None

def get_processor():
    global _processor_instance
    if _processor_instance is None:
        from scripts.direct_processor import DirectProcessor
        _processor_instance = DirectProcessor()
    return _processor_instance


def draw_bboxes(img: np.ndarray, detections: list[dict], color=(0, 255, 0)) -> np.ndarray:
    vis = img.copy()
    for d in detections:
        bbox = d.get("bbox", [])
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            conf = d.get("confidence", 0)
            label = f"{d.get('label', '?')} {conf:.1f}%"
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            cv2.putText(vis, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return vis


async def main_ui():
    init_state()
    st.title("🔍 Vision AI — Document Inspector")

    with st.sidebar:
        st.subheader("Model Status")
        p = get_processor()
        
        # Check Qwen2.5-VL status
        qwen_avail = getattr(p._ocr._qwen, "_available", False)
        if qwen_avail:
            st.success("🤖 Qwen2.5-VL: Ready")
        else:
            qwen_err = getattr(p._ocr._qwen, "_load_error", "Not warmed up yet")
            st.error(f"🤖 Qwen2.5-VL: Not Available\n\n*Error: {qwen_err}*")

        # Check YOLO status
        yolo_avail = getattr(p._yolo, "_model", None) is not None
        if yolo_avail:
            st.success("🎯 YOLO: Ready")
        else:
            st.error("🎯 YOLO: Not Loaded")

        # Check EasyOCR fallback status
        easy_avail = getattr(p._ocr, "_easyocr_reader", None) is not None
        if easy_avail:
            st.success("📝 EasyOCR Fallback: Ready")
        else:
            st.warning("📝 EasyOCR Fallback: Not Available")

        st.markdown("---")
        if st.button("Clear Results", use_container_width=True):
            clear_processing_state()

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Upload Document")
        uploaded = st.file_uploader(
            "Choose PDF, JPG, or PNG",
            type=["pdf", "jpg", "jpeg", "png"],
        )
        doc_type = st.selectbox("Document Type", options=list(DOC_TYPES.keys()), format_func=lambda x: DOC_TYPES[x])

        if st.button("🚀 Process", type="primary", disabled=uploaded is None):
            with st.spinner("Processing..."):
                p = get_processor()
                
                # Check if Qwen or YOLO are not loaded. If so, force warmup.
                qwen_avail = getattr(p._ocr._qwen, "_available", False)
                yolo_avail = getattr(p._yolo, "_loaded", False)
                if not qwen_avail or not yolo_avail:
                    await p.warmup()

                uploaded_bytes = uploaded.getvalue()
                if not uploaded_bytes:
                    st.error("Empty file")
                    st.stop()

                file_hash = hashlib.sha256(uploaded_bytes).hexdigest()
                file_name = uploaded.name
                content_type = uploaded.type or ""
                file_size = len(uploaded_bytes)

                started = time.perf_counter()
                raw_result = await p.process(uploaded_bytes, file_name, doc_type)
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
                st.rerun()

    # Display results
    ui_result = st.session_state.get("ui_result")
    if ui_result is None:
        with col_right:
            st.info("Upload a document and click **Process**.")
        st.stop()

    with col_right:
        _display_results(ui_result)


def _display_results(ui_result: dict):
    pages = ui_result.get("pages", [])
    if not pages:
        st.error("No pages in result")
        return

    doc = ui_result.get("document", {})
    total_pages = len(pages)
    sel_idx = min(st.session_state.selected_page_index, total_pages - 1)

    sel_idx = st.selectbox(
        "Page",
        options=list(range(total_pages)),
        index=sel_idx,
        format_func=lambda i: f"Page {pages[i]['page_number']} of {total_pages}",
        key="selected_page_index",
    )
    sel_page = pages[sel_idx]

    st.caption(
        f"Status: {ui_result['status']} | "
        f"Time: {ui_result['processing_time_ms']}ms | "
        f"{doc.get('file_name', '')} | "
        f"{doc.get('size_kb', 0)} KB"
    )

    views = ["Preview", "OCR", "Detection", "Fields", "Confidence"]
    tabs = st.tabs(views)
    view_map = dict(zip(views, tabs))

    with view_map["Preview"]:
        _render_preview(sel_page, sel_idx, pages)

    with view_map["OCR"]:
        _render_ocr(sel_page, sel_idx)

    with view_map["Detection"]:
        _render_detection(sel_page, sel_idx, pages)

    with view_map["Fields"]:
        _render_fields(sel_page, sel_idx)

    with view_map["Confidence"]:
        _render_confidence(ui_result, sel_page)


def _render_preview(page: dict, idx: int, pages: list):
    cols = st.columns(4)
    cols[0].metric("Extension", page.get("extension", "?"))
    cols[1].metric("Pages", len(pages))
    cols[2].metric("Status", page.get("status", "?"))
    cols[3].metric("Page", page.get("page_number", "?"))

    preview = page.get("preview")
    if preview and preview.get("image_bytes"):
        st.image(preview["image_bytes"], caption=f"Page {page['page_number']}", width=800)
    else:
        st.caption(f"Page {page['page_number']}: No preview")


def _render_ocr(page: dict, idx: int):
    ocr = page.get("ocr", {})
    raw_text = ocr.get("raw_text", "")
    if not raw_text or raw_text == "(empty)":
        raw_text = ""

    if ocr.get("status") == "FAILED":
        err_msg = ocr.get("error") or "Check 'Model Status' in sidebar to see if Qwen is loaded."
        st.error(f"OCR Failed: {err_msg}")

    st.text_area("Raw Text", raw_text or "(empty)", height=300)
    cols = st.columns(3)
    cols[0].metric("Engine", ocr.get("engine", "?"))
    cols[1].metric("Avg Confidence", f"{ocr.get('avg_confidence', 0)}%")
    cols[2].metric("Status", ocr.get("status", "?"))

    blocks = ocr.get("blocks", [])
    if blocks:
        with st.expander(f"Blocks ({len(blocks)})"):
            st.json(blocks[:30])


def _render_detection(page: dict, idx: int, pages: list):
    dets = page.get("detections", [])
    agg = page.get("detection_aggregated", {})

    if agg:
        rows = []
        for obj_type, info in agg.items():
            rows.append({
                "Object": obj_type,
                "Result": info.get("result", "?"),
                "Confidence": f"{info.get('confidence', 0):.1f}%",
            })
        st.subheader("Detection Summary")
        st.table(rows)

    if dets:
        st.subheader("All Detections")
        rows2 = []
        for d in dets:
            rows2.append({
                "Label": d.get("label", "?"),
                "Confidence": f"{d.get('confidence', 0):.1f}%",
                "Page": d.get("page_number", idx + 1),
            })
        st.table(rows2)

    preview = page.get("preview")
    if preview and preview.get("image_bytes") is not None:
        img_bytes = preview["image_bytes"]
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            vis = draw_bboxes(img, dets)
            st.image(vis, caption=f"Detections — Page {page['page_number']}", width=800)
    elif isinstance(page.get("preview"), dict) and page["preview"].get("image_bytes"):
        pass
    else:
        st.caption("Preview not available for annotation")


def _render_fields(page: dict, idx: int):
    fields = page.get("fields", {})
    if fields:
        rows = []
        for name, fdata in fields.items():
            raw_val = fdata.get("value", "—")
            if isinstance(raw_val, (int, float)):
                raw_val = str(raw_val)
            raw_conf = fdata.get("confidence", "—")
            if isinstance(raw_conf, (int, float)):
                raw_conf = f"{raw_conf}%"
            rows.append({"Field": name, "Value": raw_val, "Confidence": raw_conf})
        st.table(rows)
    else:
        st.warning("No fields extracted")


def _render_confidence(ui_result: dict, page: dict):
    raw = ui_result.get("pipeline_raw", {})
    st.metric("Total Confidence", f"{raw.get('total_confidence', 'N/A')}%")
    st.metric("Has OCR", "✅" if raw.get("has_ocr") else "❌")
    st.metric("Has Detection", "✅" if raw.get("has_detection") else "❌")
    st.metric("Overall Status", ui_result.get("status", "?"))
    st.metric("Processing Time", f"{ui_result.get('processing_time_ms', 0)}ms")

    if page.get("detections"):
        avg_conf = sum(d.get("confidence", 0) for d in page["detections"]) / len(page["detections"])
        st.metric("Avg Detection Confidence", f"{avg_conf:.1f}%")


if __name__ == "__main__":
    asyncio.run(main_ui())
