import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.inference.yolo_runtime import YoloRuntime
from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class YoloRequest:
    transaction_id: str
    document_id: str
    document_index: int
    page_index: int
    image_path: str
    future: asyncio.Future = field(default_factory=asyncio.Future)


class YoloBatcher:
    """Dynamic batching: collects requests, flushes by size or timeout."""

    def __init__(self, runtime: YoloRuntime) -> None:
        self._runtime = runtime
        self._queue: asyncio.Queue[YoloRequest] = asyncio.Queue(maxsize=config.YOLO_BATCH_SIZE * 4)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._batch_loop())
        logger.info("yolo_batcher_started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("yolo_batcher_stopped")

    async def submit(self, req: YoloRequest) -> list[dict[str, Any]]:
        await self._queue.put(req)
        return await req.future

    async def _batch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                batch: list[YoloRequest] = []
                first = await asyncio.wait_for(self._queue.get(), timeout=30)
                batch.append(first)
                deadline = time.monotonic() + (config.YOLO_MAX_BATCH_WAIT_MS / 1000)
                while len(batch) < config.YOLO_BATCH_SIZE and time.monotonic() < deadline:
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        req = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        batch.append(req)
                    except asyncio.TimeoutError:
                        break

                paths = [req.image_path for req in batch]
                try:
                    all_results = self._runtime.predict_batch(paths)
                    for req, page_results in zip(batch, all_results):
                        if not req.future.done():
                            req.future.set_result(page_results)
                except Exception as e:
                    logger.exception("yolo_batch_failed")
                    for req in batch:
                        if not req.future.done():
                            req.future.set_exception(e)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("yolo_batcher_loop_error")
                continue
