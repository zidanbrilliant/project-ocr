import os
import subprocess
import tempfile

from app.shared.exceptions.base import DocumentError
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


class WordConverter:
    LIBREOFFICE_CMD = "soffice"

    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        try:
            subprocess.run(
                [self.LIBREOFFICE_CMD, "--version"],
                capture_output=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            raise DocumentError("LibreOffice not available for DOC/DOCX conversion.")

        tmpdir = tempfile.mkdtemp(prefix="word_conv_")
        input_path = os.path.join(tmpdir, filename)
        output_dir = os.path.join(tmpdir, "output")

        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(input_path, "wb") as f:
                f.write(content)

            result = subprocess.run(
                [
                    self.LIBREOFFICE_CMD,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", output_dir,
                    input_path,
                ],
                capture_output=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise DocumentError(f"Word conversion failed: {result.stderr.decode(errors='replace')[:200]}")

            pdf_files = [f for f in os.listdir(output_dir) if f.endswith(".pdf")]
            if not pdf_files:
                raise DocumentError("Word conversion produced no PDF output.")

            pdf_path = os.path.join(output_dir, pdf_files[0])
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

            return pdf_content

        except subprocess.TimeoutExpired:
            raise DocumentError("Word conversion timed out.")
        finally:
            for root, dirs, files in os.walk(tmpdir, topdown=False):
                for name in files: os.remove(os.path.join(root, name))
                for name in dirs: os.rmdir(os.path.join(root, name))
            os.rmdir(tmpdir)
