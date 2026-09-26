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
    if len(text.strip()) >= 50:
        return ParsedInput(
            source_type="pdf",
            source_name=str(file_path),
            text=text,
            metadata={"page_count": len(pages)},
        )

    try:
        from parsers.ocr_engine import OcrEngine, OcrError

        engine = OcrEngine()
        ocr_text = engine.extract_text_from_pdf(file_path)
        return ParsedInput(
            source_type="pdf",
            source_name=f"{file_path.name} (OCR)",
            text=ocr_text,
            metadata={"page_count": len(pages), "ocr": True},
        )
    except OcrError as exc:
        raise ValueError(
            f"PDF '{file_path}' appears to be scanned but OCR failed: {exc}"
        ) from exc
