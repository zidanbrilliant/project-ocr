"""Run a repeatable local/DGX benchmark over a directory of sample documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
CORE_FIELDS = ("document_number", "transaction_amount", "transaction_date")


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


def evaluate_fields(result: dict, expected: dict) -> dict:
    fields = result.get("fields", {})
    checks: dict[str, bool] = {}
    for name in CORE_FIELDS:
        if name not in expected:
            continue
        actual = fields.get(name, {}).get("value")
        target = expected[name]
        target_value = target.get("value") if isinstance(target, dict) else target
        matches = _values_match(actual, target_value)
        if matches and isinstance(target, dict) and target.get("currency"):
            matches = fields.get(name, {}).get("currency") == target["currency"]
        checks[name] = matches
    return {"checks": checks, "all_core_fields_exact": bool(checks) and all(checks.values())}


def evaluate_candidate_recall(result: dict, expected: dict) -> dict[str, bool]:
    """Report whether the correct non-null value existed before final selection."""
    audit = result.get("field_candidate_audit", {})
    checks: dict[str, bool] = {}
    for name in CORE_FIELDS:
        if name not in expected:
            continue
        target = expected[name]
        target_value = target.get("value") if isinstance(target, dict) else target
        if target_value is None:
            continue
        expected_currency = target.get("currency") if isinstance(target, dict) else None
        checks[name] = any(
            _values_match(candidate.get("value"), target_value)
            and (not expected_currency or candidate.get("currency") == expected_currency)
            for candidate in audit.get(name, [])
            if isinstance(candidate, dict)
        )
    return checks


def _values_match(actual: object, expected: object) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 0.01
    return str(actual).strip().upper() == str(expected).strip().upper()


async def benchmark(
    input_dir: Path,
    doc_type: str,
    ground_truth: dict[str, dict] | None = None,
    include_trace: bool = False,
) -> dict:
    from scripts.direct_processor import DirectProcessor

    files = sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in SUPPORTED)
    if not files:
        raise SystemExit(f"No PDF/JPG/PNG files found in {input_dir}")

    processor = DirectProcessor()
    await processor.warmup()
    started = time.perf_counter()
    results = []
    total_pages = 0
    for path in files:
        document_started = time.perf_counter()
        result = await processor.process(path.read_bytes(), path.name, doc_type)
        pages = len(result.get("pages", []))
        total_pages += pages
        row = {
            "file": str(path),
            "status": result.get("status"),
            "pages": pages,
            "duration_ms": round((time.perf_counter() - document_started) * 1000),
            "error": result.get("error"),
        }
        expected = (ground_truth or {}).get(path.name)
        if expected is not None:
            row["evaluation"] = evaluate_fields(result, expected)
            row["candidate_recall"] = evaluate_candidate_recall(result, expected)
        if include_trace:
            row["trace"] = {
                "fields": result.get("fields", {}),
                "field_candidate_audit": result.get("field_candidate_audit", {}),
                "reasoning": result.get("reasoning", {}),
                "ocr_pages": [
                    {
                        key: page.get(key)
                        for key in (
                            "engine_name",
                            "raw_text",
                            "tokens_json",
                            "average_confidence",
                            "processing_time_ms",
                            "error",
                        )
                        if page.get(key) is not None
                    }
                    for page in result.get("_page_ocrs", [])
                ],
            }
        results.append(row)

    duration = time.perf_counter() - started
    labeled = [item["evaluation"] for item in results if "evaluation" in item]
    field_metrics = {
        name: {
            "evaluated": sum(name in item["checks"] for item in labeled),
            "exact_matches": sum(item["checks"].get(name, False) for item in labeled),
        }
        for name in CORE_FIELDS
    }
    for metric in field_metrics.values():
        metric["exact_match_rate"] = (
            round(metric["exact_matches"] / metric["evaluated"], 4) if metric["evaluated"] else None
        )

    candidate_metrics = {
        name: {
            "evaluated": sum(name in item.get("candidate_recall", {}) for item in results),
            "correct_candidates": sum(item.get("candidate_recall", {}).get(name, False) for item in results),
        }
        for name in CORE_FIELDS
    }
    for metric in candidate_metrics.values():
        metric["recall"] = (
            round(metric["correct_candidates"] / metric["evaluated"], 4) if metric["evaluated"] else None
        )

    return {
        "documents": len(files),
        "pages": total_pages,
        "duration_seconds": round(duration, 3),
        "documents_per_hour": round(len(files) / duration * 3600, 2),
        "pages_per_minute": round(total_pages / duration * 60, 2),
        "failed_documents": sum(bool(item["error"]) for item in results),
        "accuracy": {
            "labeled_documents": len(labeled),
            "field_metrics": field_metrics,
            "candidate_metrics": candidate_metrics,
            "all_core_fields_exact": sum(item["all_core_fields_exact"] for item in labeled),
            "all_core_fields_exact_rate": round(
                sum(item["all_core_fields_exact"] for item in labeled) / len(labeled), 4
            )
            if labeled
            else None,
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--doc-type", default="INV", choices=("INV", "DN"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    parser.add_argument("--ground-truth", type=Path, help="JSON/JSONL rows with file_name and fields")
    parser.add_argument("--include-trace", action="store_true", help="Include OCR, candidates, fields, and reasoning")
    args = parser.parse_args()
    ground_truth = load_ground_truth(args.ground_truth) if args.ground_truth else None
    report = asyncio.run(benchmark(args.input_dir, args.doc_type, ground_truth, args.include_trace))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
