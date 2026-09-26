"""Parser for PDF requirement documents."""

from pathlib import Path

from models.input_model import ParsedInput


class PdfParseError(ValueError):
    """Raised when a PDF document cannot be parsed or is empty."""


def parse_pdf(path: str | Path) -> ParsedInput:
    """Extract text from every page of a PDF file."""

    file_path = Path(path)
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:
        raise PdfParseError("pypdf is required for PDF input.") from exc

    try:
        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (OSError, ValueError, KeyError, PdfReadError) as exc:
        raise PdfParseError(f"Could not parse PDF file '{file_path}': {exc}") from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    if not text:
        raise PdfParseError(f"PDF file '{file_path}' contains no extractable text.")
    return ParsedInput(
        source_type="pdf",
        source_name=str(file_path),
        text=text,
        metadata={"page_count": len(pages)},
    )
