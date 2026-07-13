import asyncio
import signal

from app.application.services.ai_pipeline_orchestrator import AIPipelineOrchestrator
from app.application.services.confidence_scoring_service import ConfidenceScoringService
from app.application.services.field_extraction_service import FieldExtractionService
from app.domain.services.business_rule_evaluator import BusinessRuleEvaluator
from app.domain.services.remark_policy import RemarkPolicy
from app.infrastructure.barcode.barcode_fallback_chain import BarcodeFallbackChain
from app.infrastructure.barcode.opencv_barcode_adapter import OpenCVBarcodeAdapter
from app.infrastructure.barcode.pyzbar_adapter import PyzbarAdapter
from app.infrastructure.barcode.zxing_adapter import ZXingAdapter
from app.infrastructure.database.repositories.ai_job_postgres_repository import AIJobPostgresRepository
from app.infrastructure.database.repositories.audit_log_postgres_repository import AuditLogPostgresRepository
from app.infrastructure.database.repositories.result_postgres_repository import ResultPostgresRepository
from app.infrastructure.database.session import async_session_factory
from app.infrastructure.detection.yolo_adapter import YOLOAdapter
from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.infrastructure.document_converter.image_preprocessor import ImagePreprocessor
from app.infrastructure.document_converter.pdf_renderer import PDFRenderer
from app.infrastructure.document_converter.word_converter import WordConverter
from app.infrastructure.ocr.document_ocr import DocumentOCR
from app.infrastructure.ocr.ocr_fallback_chain import OCRFallbackChain
from app.infrastructure.rabbitmq.connection import RabbitMQConnection
from app.infrastructure.rabbitmq.consumer import InvoiceRequestConsumer
from app.infrastructure.rabbitmq.publisher import ResultPublisher
from app.infrastructure.rabbitmq.retry import RetryHandler
from app.infrastructure.rabbitmq.topology import declare_topology
from app.infrastructure.storage.image_server_client import ImageServerClient
from app.infrastructure.storage.temp_file_manager import TempFileManager
from app.shared.config.settings import settings
from app.shared.logging.log_context import clear_context
from app.shared.logging.logger import get_logger, setup_logging
from app.workers.processors.job_processor import JobProcessor

logger = get_logger(__name__)
_shutdown = asyncio.Event()


def _signal_handler() -> None:
    logger.info("shutdown_signal_received")
    _shutdown.set()


class WorkerMain:
    def __init__(self) -> None:
        self._rmq = RabbitMQConnection()
        self._consumer: InvoiceRequestConsumer | None = None
        self._file_client: ImageServerClient | None = None

    async def run(self) -> None:
        setup_logging()
        logger.info("worker_starting", env=settings.APP_ENV)

        self._file_client = ImageServerClient()
        temp_mgr = TempFileManager()
        pdf_renderer = PDFRenderer()
        word_converter = WordConverter()
        preprocessor = ImagePreprocessor()
        validator = DocumentValidator()
        field_extractor = FieldExtractionService()
        rule_eval = BusinessRuleEvaluator()
        conf_scorer = ConfidenceScoringService()
        remark = RemarkPolicy()

        ocr_primary = DocumentOCR()
        try:
            await ocr_primary.warmup()
        except Exception as e:
            logger.warning("ocr_warmup_failed", error=str(e))
        ocr_chain = OCRFallbackChain(ocr_primary)

        yolo = YOLOAdapter()
        try:
            await yolo.warmup()
        except Exception as e:
            logger.warning("yolo_warmup_failed", error=str(e))

        barcode_chain = BarcodeFallbackChain(ZXingAdapter(), PyzbarAdapter(), OpenCVBarcodeAdapter())

        async with async_session_factory() as session:
            job_repo = AIJobPostgresRepository(session)
            result_repo = ResultPostgresRepository(session)
            audit = AuditLogPostgresRepository(session)
            publisher = ResultPublisher(self._rmq)
            retry = RetryHandler(self._rmq)

            orchestrator = AIPipelineOrchestrator(
                job_repo=job_repo, result_repo=result_repo, audit=audit,
                publisher=publisher, retry_handler=retry,
                file_client=self._file_client, temp_mgr=temp_mgr,
                pdf_renderer=pdf_renderer, word_converter=word_converter,
                preprocessor=preprocessor, ocr_chain=ocr_chain,
                yolo=yolo,
                barcode_chain=barcode_chain, validator=validator,
                field_extractor=field_extractor, rule_evaluator=rule_eval,
                confidence_scorer=conf_scorer,
                remark_policy=remark,
            )

            await declare_topology(self._rmq)
            processor = JobProcessor(orchestrator)
            self._consumer = InvoiceRequestConsumer(self._rmq)
            await self._consumer.start(processor.handle)

            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

            logger.info("worker_ready")
            await _shutdown.wait()
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("worker_shutting_down")
        if self._consumer:
            await self._consumer.stop()
        if self._file_client:
            await self._file_client.close()
        await self._rmq.close()
        clear_context()
        logger.info("worker_shutdown_complete")


def main() -> None:
    w = WorkerMain()
    asyncio.run(w.run())


if __name__ == "__main__":
    main()
