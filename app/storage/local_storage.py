import os
import shutil
import tempfile
from pathlib import Path

from app.config import config
from app.observability.logging import get_logger

logger = get_logger(__name__)


class LocalStorage:
    """Manages temporary file storage for document processing."""

    def __init__(self) -> None:
        self._base_dir = Path(config.TEMP_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._dirs: list[str] = []

    def create_transaction_dir(self, transaction_id: str) -> str:
        path = str(self._base_dir / transaction_id)
        os.makedirs(path, exist_ok=True)
        self._dirs.append(path)
        return path

    def create_document_dir(self, transaction_dir: str, document_id: str) -> str:
        path = os.path.join(transaction_dir, document_id)
        os.makedirs(path, exist_ok=True)
        return path

    def save_temp_file(self, content: bytes, dir_path: str, filename: str) -> str:
        path = os.path.join(dir_path, filename)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def cleanup_dir(self, dir_path: str | None = None) -> None:
        if dir_path:
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
            except OSError as e:
                logger.warning("cleanup_failed", path=dir_path, error=str(e))
        else:
            for d in list(self._dirs):
                shutil.rmtree(d, ignore_errors=True)
            self._dirs.clear()

    def cleanup_all(self) -> None:
        self.cleanup_dir()
