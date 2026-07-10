import asyncio
import signal
from concurrent.futures import ProcessPoolExecutor

from app.config import config
from app.inference.easyocr_runtime import EasyOCRRuntime
from app.inference.yolo_batcher import YoloBatcher
from app.inference.yolo_runtime import YoloRuntime
from app.observability.logging import get_logger, setup_logging
from app.observability.metrics import gpu_memory_used, gpu_utilization
from app.orchestration.transaction_processor import TransactionProcessor
from app.storage.local_storage import LocalStorage

logger = get_logger(__name__)

_shutdown = asyncio.Event()


def _signal_handler() -> None:
    logger.info("shutdown_signal_received")
    _shutdown.set()


class DocumentWorker:
    def __init__(self) -> None:
        self._yolo_runtime = YoloRuntime()
        self._yolo_batcher: YoloBatcher | None = None
        self._easyocr_gpu = EasyOCRRuntime()
        self._render_pool: ProcessPoolExecutor | None = None
        self._storage = LocalStorage()
        self._processor: TransactionProcessor | None = None

    async def start(self) -> None:
        setup_logging()
        logger.info("worker_starting", env=config.APP_ENV)

        self._yolo_runtime.load()
        self._yolo_runtime.warmup()

        self._yolo_batcher = YoloBatcher(self._yolo_runtime)
        await self._yolo_batcher.start()

        self._easyocr_gpu.load()

        self._render_pool = ProcessPoolExecutor(max_workers=config.RENDER_PROCESS_WORKERS)

        self._processor = TransactionProcessor(
            yolo_runtime=self._yolo_runtime,
            yolo_batcher=self._yolo_batcher,
            ocr_pool=None,
            render_pool=self._render_pool,
            storage=self._storage,
        )

        logger.info("worker_ready")

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        await _shutdown.wait()
        await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("worker_shutting_down")
        if self._yolo_batcher:
            await self._yolo_batcher.stop()
        self._easyocr_gpu.shutdown()
        if self._render_pool:
            self._render_pool.shutdown(wait=True)
        self._storage.cleanup_all()
        logger.info("worker_shutdown_complete")


async def main() -> None:
    worker = DocumentWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
