import os
import tempfile
from pathlib import Path
from typing import Any

from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class TempFileManager:
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = base_dir or tempfile.gettempdir()
        self._dirs: list[str] = []

    def create_temp_dir(self, prefix: str = "vision_ai_") -> str:
        tmpdir = tempfile.mkdtemp(prefix=prefix, dir=self._base_dir)
        self._dirs.append(tmpdir)
        return tmpdir

    def save_temp_file(self, content: bytes, filename: str, prefix: str = "doc_") -> str:
        tmpdir = self.create_temp_dir(prefix=prefix)
        filepath = os.path.join(tmpdir, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        logger.debug("temp_file_saved", path=filepath, size=len(content))
        return filepath

    def cleanup(self, tmpdir: str | None = None) -> None:
        if tmpdir:
            self._remove_dir(tmpdir)
            if tmpdir in self._dirs:
                self._dirs.remove(tmpdir)
        else:
            for d in list(self._dirs):
                self._remove_dir(d)
            self._dirs.clear()

    def cleanup_all(self) -> None:
        self.cleanup()

    def _remove_dir(self, path: str) -> None:
        try:
            for root, dirs, files in os.walk(path, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(path)
        except OSError as e:
            logger.warning("temp_cleanup_failed", path=path, error=str(e))
