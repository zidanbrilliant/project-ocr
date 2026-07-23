import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import streamlit as st

from app.application.services.local_execution_service import LocalExecutionService
from app.application.services.local_runtime import LocalDocument
from app.shared.config.settings import settings
from scripts.direct_processor import DirectProcessor
from scripts.result_adapter import normalize_result_envelope_for_ui

st.set_page_config(page_title="Vision AI", page_icon="VI", layout="wide")

DOC_TYPES = {"INV": "Invoice", "DN": "Delivery Note"}


def init_state() -> None:
    if "local_job_id" not in st.session_state:
        st.session_state.local_job_id = None


def clear_processing_state() -> None:
    st.session_state.pop("local_job_id", None)


@st.cache_resource(show_spinner=False)
def get_processor() -> DirectProcessor:
    return DirectProcessor()


@st.cache_resource(show_spinner=False)
def get_local_service() -> LocalExecutionService:
    return LocalExecutionService(processor=get_processor())


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


def main_ui() -> None:
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
        uploaded = st.file_uploader(
            "Choose one or more PDF, JPG, or PNG files",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
        )
        doc_type = st.selectbox("Document Type", options=list(DOC_TYPES.keys()), format_func=lambda x: DOC_TYPES[x])

        if st.button("Process", type="primary", disabled=not uploaded, use_container_width=True):
            documents = [
                LocalDocument(item.name, item.type or "", item.getvalue(), doc_type)
                for item in uploaded
            ]
            st.session_state.local_job_id = get_local_service().submit(documents)
            st.rerun()
            return

    with col_right:
        job_id = st.session_state.get("local_job_id")
        if not job_id:
            st.info("Upload a document and click Process.")
            return

        try:
            snapshot = get_local_service().snapshot(job_id)
        except LookupError as error:
            st.error(str(error))
            return

        if snapshot.status in {"PENDING", "QUEUED", "RUNNING"}:
            st.info(
                f"Processing {snapshot.completed_documents}/{snapshot.total_documents} document(s)."
            )
            if st.button("Refresh progress"):
                st.rerun()
            return

        if snapshot.status == "FAILED":
            st.error(snapshot.error or "Local processing failed.")
            return

        if snapshot.result is None:
            st.error(f"Job {job_id} finished without a result.")
            return

        ui_results = normalize_result_envelope_for_ui(snapshot.result)
        if not ui_results:
            st.error("The completed result contains no documents.")
            return

        selected_document = st.selectbox(
            "Document",
            options=list(range(len(ui_results))),
            format_func=lambda index: ui_results[index]["document"].get("file_name", f"Document {index + 1}"),
        )
        ui_result = ui_results[selected_document]
        _display_results(ui_result)
        if len(ui_results) > 1:
            with st.expander("Combined RabbitMQ preview"):
                st.json(snapshot.result)


def _render_model_status(processor: DirectProcessor) -> None:
    ocr = processor._ocr
    nemotron = getattr(ocr, "_nemotron", None)
    if getattr(nemotron, "_available", False):
        st.success("Nemotron Parse: ready")
    else:
        st.warning(f"Nemotron Parse: not loaded ({getattr(nemotron, '_load_error', 'warmup pending')})")

    reasoning = processor._field_reasoning
    if reasoning.is_available:
        st.success("Qwen3.5-9B extraction: ready")
    else:
        st.warning(f"Qwen3.5-9B extraction: not loaded ({reasoning.load_error or 'warmup pending'})")

    yolo_loaded = getattr(processor._yolo, "_loaded", False)
    if yolo_loaded:
        st.success("YOLO: ready")
    else:
        st.warning("YOLO: not loaded")


def _display_results(ui_result: dict) -> None:
    errors = ui_result.get("errors") or []
    if errors:
        st.error(
            "\n".join(
                error.get("message", str(error)) if isinstance(error, dict) else str(error)
                for error in errors
            )
        )

    pages = ui_result.get("pages", [])
    if not pages:
        st.error("No pages in result.")
        st.json(ui_result["rabbitmq_preview"])
        return

    doc = ui_result.get("document", {})
    total_pages = len(pages)
    selected_index = st.selectbox(
        "Page",
        options=list(range(total_pages)),
        format_func=lambda i: f"Page {pages[i]['page_number']} of {total_pages}",
    )
    selected_page = pages[selected_index]

    st.caption(
        f"Status: {ui_result['status']} | "
        f"Time: {ui_result['processing_time_ms']}ms | "
        f"{doc.get('file_name', '')} | "
        f"{doc.get('size_kb', 0)} KB"
    )

    preview_tab, ocr_tab, detection_tab, fields_tab, summary_tab, confidence_tab, json_tab = st.tabs(
        ["Preview", "OCR", "Detection", "Fields", "Summary", "Confidence", "Result JSON"]
    )

    with preview_tab:
        _render_preview(selected_page, pages)
    with ocr_tab:
        _render_ocr(selected_page)
    with detection_tab:
        _render_detection(selected_page, selected_index)
    with fields_tab:
        _render_fields(selected_page)
    with summary_tab:
        _render_summary(ui_result)
    with confidence_tab:
        _render_confidence(ui_result, selected_page)
    with json_tab:
        st.json(ui_result["rabbitmq_preview"])
        st.download_button(
            "Download result JSON",
            data=json.dumps(ui_result["rabbitmq_preview"], indent=2, ensure_ascii=False),
            file_name="vision-ai-result.json",
            mime="application/json",
        )


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
                "Confidence": f"{confidence * 100:.1f}%" if isinstance(confidence, (int, float)) else confidence,
                "Status": field_data.get("status", "?"),
                "Selected by": field_data.get("reasoning_engine", "deterministic"),
                "Reason": field_data.get("reason_code", ""),
                "Evidence": field_data.get("source_text", ""),
                "Block": field_data.get("source_block_id", ""),
            }
        )
    st.table(rows)


def _render_summary(ui_result: dict) -> None:
    payload = ui_result["rabbitmq_preview"]
    document = payload["documents"][ui_result["document_index"]]
    reasoning = document.get("reasoning") or {}
    if reasoning.get("error"):
        st.error(f"Qwen reasoning unavailable: {reasoning['error']}")
    summary = document.get("document_summary") or {}
    st.metric("Result", summary.get("result", document.get("processing_result", "?")))
    st.write(summary.get("reason", "No summary available."))
    if summary.get("failed_items"):
        st.error("Failed: " + ", ".join(summary["failed_items"]))
    st.caption(f"Summary engine: {summary.get('engine', 'deterministic')}")


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
    main_ui()
