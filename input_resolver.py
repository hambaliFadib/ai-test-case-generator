"""Resolve inline text and supported document paths into ParsedInput."""

from pathlib import Path

from models.input_model import ParsedInput
from parsers.docx_parser import parse_docx
from parsers.markdown_parser import parse_markdown
from parsers.pdf_parser import parse_pdf
from parsers.text_parser import parse_text


class InputResolutionError(ValueError):
    """Raised when input arguments are invalid or use an unsupported format."""


SUPPORTED_SUFFIXES: tuple[str, ...] = (".docx", ".pdf", ".md")


def resolve_input(
    inline_text: str | None = None,
    input_path: str | Path | None = None,
) -> ParsedInput:
    """Resolve exactly one inline text value or supported file path."""

    has_text = inline_text is not None
    has_path = input_path is not None
    if has_text == has_path:
        raise InputResolutionError("Provide exactly one of --text or --input.")

    if has_text:
        return parse_text(inline_text or "")

    file_path = Path(input_path or "")
    if not file_path.is_file():
        raise InputResolutionError(f"Input file does not exist: '{file_path}'.")
    suffix = file_path.suffix.lower()
    if suffix == ".md":
        return parse_markdown(file_path)
    if suffix == ".docx":
        return parse_docx(file_path)
    if suffix == ".pdf":
        return parse_pdf(file_path)
    supported = ", ".join(SUPPORTED_SUFFIXES)
    raise InputResolutionError(f"Unsupported input format '{suffix}'. Supported formats: {supported}.")
