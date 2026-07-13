import asyncio, sys
sys.path.insert(0, __file__.rsplit("\\", 2)[0])

from scripts.direct_processor import DirectProcessor


async def main(path: str):
    p = DirectProcessor()
    await p.warmup()
    with open(path, "rb") as f:
        r = await p.process(f.read(), path, "INV")
    assert r["status"] in ("OK", "NG"), f"bad status: {r['status']}"
    assert r.get("processing_time_ms", 0) > 0
    print(f"PASS: {r['status']} in {r['processing_time_ms']}ms, conf={r.get('confidence',{}).get('total',0)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
