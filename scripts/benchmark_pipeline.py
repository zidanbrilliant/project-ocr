"""Run a repeatable local/DGX benchmark over a directory of sample documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from scripts.direct_processor import DirectProcessor

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}


async def benchmark(input_dir: Path, doc_type: str) -> dict:
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
        results.append(
            {
                "file": str(path),
                "status": result.get("status"),
                "pages": pages,
                "duration_ms": round((time.perf_counter() - document_started) * 1000),
                "error": result.get("error"),
            }
        )

    duration = time.perf_counter() - started
    return {
        "documents": len(files),
        "pages": total_pages,
        "duration_seconds": round(duration, 3),
        "documents_per_hour": round(len(files) / duration * 3600, 2),
        "pages_per_minute": round(total_pages / duration * 60, 2),
        "failed_documents": sum(bool(item["error"]) for item in results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--doc-type", default="INV", choices=("INV", "DN"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.input_dir, args.doc_type))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
