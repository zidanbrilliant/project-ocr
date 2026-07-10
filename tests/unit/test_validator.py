import pytest

from app.infrastructure.document_converter.document_validator import DocumentValidator
from app.shared.exceptions.base import DocumentError


@pytest.fixture
def validator() -> DocumentValidator:
    return DocumentValidator()


def test_empty_file_raises(validator: DocumentValidator) -> None:
    with pytest.raises(DocumentError, match="corrupt"):
        validator.validate(b"", "test.pdf")


def test_invalid_extension(validator: DocumentValidator) -> None:
    with pytest.raises(DocumentError, match="Unsupported"):
        validator.validate(b"test", "test.txt")


def test_pdf_magic_validation(validator: DocumentValidator) -> None:
    with pytest.raises(DocumentError, match="corrupt"):
        validator.validate(b"not a pdf content", "test.pdf")


def test_valid_pdf_small(validator: DocumentValidator) -> None:
    content = b"%PDF-1.4\n1 0 obj<</Type /Page>>\n%%EOF"
    result = validator.validate(content, "test.pdf")
    assert result["readable"] is True
    assert result["extension"] == ".pdf"
    assert result["content_type"] == "application/pdf"
