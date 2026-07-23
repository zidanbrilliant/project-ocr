"""Run a repeatable local/DGX benchmark over a directory of sample documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from app.application.services.local_execution_service import LocalExecutionService
from app.application.services.local_runtime import LocalDocument
from app.application.services.model_evaluation_service import (
    evaluate_candidate_recall,
    evaluate_fields,
    evaluate_yolo_validation,
    summarize_field_evaluations,
)
from app.shared.config.settings import settings

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
REQUIRED_YOLO_LABELS = {"barcode", "materai", "signature", "stamp"}


def load_ground_truth(path: Path) -> dict[str, dict]:
    """Load JSON/JSONL rows keyed by file_name; values are expected field values."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    payload = (
        json.loads(text)
        if path.suffix.lower() == ".json"
        else [json.loads(line) for line in text.splitlines() if line]
    )
    rows = payload.values() if isinstance(payload, dict) else payload
    return {
        str(row.get("file_name") or row.get("file") or row.get("document_name")): row.get("fields", row)
        for row in rows
        if isinstance(row, dict) and (row.get("file_name") or row.get("file") or row.get("document_name"))
    }


async def benchmark(
    input_dir: Path,
    doc_type: str,
    ground_truth: dict[str, dict] | None = None,
    include_trace: bool = False,
    limit: int | None = None,
    yolo_dataset_root: Path | None = None,
) -> dict:
    files = sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in SUPPORTED)
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"No PDF/JPG/PNG files found in {input_dir}")

    service = LocalExecutionService()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    labeled_rows: list[dict[str, Any]] = []
    total_pages = 0
    for index, path in enumerate(files, start=1):
        document_started = time.perf_counter()
        print(f"[{index}/{len(files)}] {path.name} | processing", flush=True)
        snapshot = await service.run_inline(
            [
                LocalDocument(
                    name=path.name,
                    content_type=mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                    content=path.read_bytes(),
                    doc_type=doc_type,
                )
            ]
        )
        envelope = snapshot.result or {}
        document = next(iter(envelope.get("documents", [])), {})
        pages = len(document.get("pages", []))
        total_pages += pages
        expected = (ground_truth or {}).get(path.name)
        evaluation = evaluate_fields(document, expected or {})
        row = {
            "file": str(path),
            "file_name": path.name,
            "status": document.get("processing_status", snapshot.status),
            "pages": pages,
            "duration_ms": round((time.perf_counter() - document_started) * 1000),
            "error": _snapshot_error(snapshot, envelope, document),
            "expected": expected,
            "actual": evaluation["actual"],
            "checks": evaluation["checks"],
        }
        if expected is not None:
            row["candidate_recall"] = evaluate_candidate_recall(document, expected)
            labeled_rows.append(row)
        if include_trace:
            row["trace"] = {
                "fields": document.get("fields", []),
                "field_candidate_audit": document.get("field_candidate_audit", {}),
                "reasoning": document.get("reasoning", {}),
                "ocr_pages": [
                    {
                        "page_number": page.get("page_number"),
                        **{
                            key: page.get("ocr", {}).get(key)
                            for key in (
                                "engine",
                                "raw_text",
                                "average_confidence",
                                "duration_ms",
                                "text_blocks",
                                "error",
                            )
                            if page.get("ocr", {}).get(key) is not None
                        },
                    }
                    for page in document.get("pages", [])
                ],
            }
        results.append(row)
        print(f"[{index}/{len(files)}] {path.name} | {row['duration_ms']} ms", flush=True)

    duration = time.perf_counter() - started
    report = {
        "documents": len(files),
        "pages": total_pages,
        "duration_seconds": round(duration, 3),
        "documents_per_hour": round(len(files) / duration * 3600, 2),
        "pages_per_minute": round(total_pages / duration * 60, 2),
        "failed_documents": sum(bool(item["error"]) for item in results),
        "accuracy": summarize_field_evaluations(
            labeled_rows,
            settings.FIELD_EXACT_MATCH_THRESHOLD,
        ),
        "results": results,
    }
    if yolo_dataset_root is not None:
        detector = service._processor._yolo
        try:
            report["yolo_validation"] = await evaluate_yolo_validation(
                detector,
                yolo_dataset_root / "val",
                REQUIRED_YOLO_LABELS,
            )
        except ValueError as error:
            report["yolo_validation"] = {
                "class_map": detector.class_map,
                "per_class": {},
                "aggregate_map50": 0.0,
                "evaluated_images": 0,
                "skipped_images": 0,
                "error": str(error),
                "acceptance": {
                    "passed": False,
                    "failed_classes": sorted(REQUIRED_YOLO_LABELS),
                    "aggregate_passed": False,
                    "threshold": settings.YOLO_AP50_THRESHOLD,
                },
            }
    return report


def _snapshot_error(
    snapshot: Any,
    envelope: dict[str, Any],
    document: dict[str, Any],
) -> str | None:
    if snapshot.error:
        return snapshot.error
    errors = document.get("errors") or envelope.get("errors") or []
    if not errors:
        return None
    first = errors[0]
    return str(first.get("message", first)) if isinstance(first, dict) else str(first)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--doc-type", default="INV", choices=("INV", "DN"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    parser.add_argument("--ground-truth", type=Path, help="JSON/JSONL rows with file_name and fields")
    parser.add_argument("--include-trace", action="store_true", help="Include OCR, candidates, fields, and reasoning")
    parser.add_argument("--limit", type=int, help="Process only the first N sorted files")
    parser.add_argument(
        "--yolo-dataset-root",
        type=Path,
        help="YOLO dataset root containing val/images and val/labels",
    )
    parser.add_argument(
        "--require-yolo-gate",
        action="store_true",
        help="Exit 2 after writing the report when a requested acceptance gate fails",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.require_yolo_gate and args.yolo_dataset_root is None:
        parser.error("--require-yolo-gate requires --yolo-dataset-root")
    ground_truth = load_ground_truth(args.ground_truth) if args.ground_truth else None
    report = asyncio.run(
        benchmark(
            args.input_dir,
            args.doc_type,
            ground_truth,
            args.include_trace,
            args.limit,
            args.yolo_dataset_root,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    if args.require_yolo_gate:
        field_failed = bool(args.ground_truth) and not report["accuracy"][
            "field_acceptance"
        ]["passed"]
        yolo_failed = not report["yolo_validation"]["acceptance"]["passed"]
        if field_failed or yolo_failed:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
