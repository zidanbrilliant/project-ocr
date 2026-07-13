import asyncio, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.infrastructure.database.session import async_session_factory
from app.infrastructure.database.models import (
    AIJob, AIFinalResult, AIOCRResult,
    AIDetectionResult, AIBarcodeResult, AIAuditLog,
)
from sqlalchemy import select, text, func


async def show_jobs(limit: int = 5):
    async with async_session_factory() as s:
        rows = await s.execute(
            select(AIJob).order_by(AIJob.created_at.desc()).limit(limit)
        )
        for j in rows.scalars():
            print(f"\n=== JOB {j.queue_id} ===")
            print(f"  DOC_NO={j.doc_no}  TYPE={j.doc_type}  STATUS={j.processing_status}")
            print(f"  RESULT={j.overall_result}  RETRY={j.retry_count}")
            print(f"  FILE={j.file_nm}  PAGES=?")

            # page count from final result
            fr = await s.execute(
                select(AIFinalResult).where(AIFinalResult.job_id == j.id)
            )
            fr_row = fr.scalar_one_or_none()
            if fr_row and fr_row.internal_result_json:
                pages = fr_row.internal_result_json.get("pages", [])
                print(f"  PAGES={len(pages)}  CONFIDENCE={fr_row.ai_confidence}")
                for p in pages:
                    print(f"    Page {p['page_number']}: OCR={p['ocr']['engine']} "
                          f"conf={p['ocr'].get('average_confidence')} "
                          f"detections={len(p['detections'])} "
                          f"barcode={'yes' if p['barcode'].get('barcode_decoded') else 'no'}")


async def show_detailed(job_queue_id: str):
    async with async_session_factory() as s:
        job = await s.execute(
            select(AIJob).where(AIJob.queue_id == job_queue_id)
        )
        j = job.scalar_one_or_none()
        if not j:
            print(f"Job not found: {job_queue_id}")
            return

        print(f"\n=== JOB {j.queue_id} ===")
        print(f"DOC_NO={j.doc_no}  TYPE={j.doc_type}  STATUS={j.processing_status}")
        print(f"RESULT={j.overall_result}  CONFIDENCE=?")

        fr = await s.execute(
            select(AIFinalResult).where(AIFinalResult.job_id == j.id)
        )
        fr_row = fr.scalar_one_or_none()
        if fr_row:
            print(f"CONFIDENCE={fr_row.ai_confidence}  LEVEL={fr_row.ai_confidence_level}")
            print(f"REMARK={fr_row.ai_return_remark}")
            pages = fr_row.internal_result_json.get("pages", []) if fr_row.internal_result_json else []
            for p in pages:
                print(f"\n  --- Page {p['page_number']} ---")
                ocr = p["ocr"]
                print(f"  OCR: engine={ocr.get('engine')}  conf={ocr.get('average_confidence')}")
                txt = (ocr.get("raw_text") or "")[:200]
                print(f"  Text: {txt}...")
                for d in p["detections"]:
                    print(f"  DETECT: {d.get('object_type')}  conf={d.get('confidence')}  "
                          f"bbox={d.get('bounding_box')}")
                bc = p["barcode"]
                if bc.get("barcode_decoded"):
                    print(f"  BARCODE: {bc.get('barcode_value')}  type={bc.get('barcode_type')}")

        # raw tables
        print(f"\n  --- Raw OCR Results ---")
        ocrs = await s.execute(
            select(AIOCRResult).where(AIOCRResult.job_id == j.id)
        )
        for o in ocrs.scalars():
            print(f"  page={o.page_number} engine={o.engine_name} conf={o.average_confidence}")

        print(f"\n  --- Raw Detection Results ---")
        dets = await s.execute(
            select(AIDetectionResult).where(AIDetectionResult.job_id == j.id)
        )
        for d in dets.scalars():
            print(f"  page={d.page_number} type={d.object_type} conf={d.confidence} result={d.result}")

        print(f"\n  --- Audit Log ---")
        logs = await s.execute(
            select(AIAuditLog).where(AIAuditLog.job_id == j.id)
        )
        for l in logs.scalars():
            print(f"  {l.action}  actor={l.actor}  at={l.created_at}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        asyncio.run(show_jobs(int(sys.argv[2]) if len(sys.argv) > 2 else 5))
    else:
        asyncio.run(show_detailed(cmd))
