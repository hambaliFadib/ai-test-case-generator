"""Parser for Markdown requirement documents."""

from pathlib import Path

from models.input_model import ParsedInput


class MarkdownParseError(ValueError):
    """Raised when a Markdown file cannot be read or is empty."""


def parse_markdown(path: str | Path) -> ParsedInput:
    """Read a UTF-8 Markdown file and return normalized document content."""

    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MarkdownParseError(f"Could not read Markdown file '{file_path}': {exc}") from exc
    except UnicodeError as exc:
        raise MarkdownParseError(f"Markdown file '{file_path}' is not valid UTF-8.") from exc
    if not text.strip():
        raise MarkdownParseError(f"Markdown file '{file_path}' is empty.")
    return ParsedInput(
        source_type="markdown",
        source_name=str(file_path),
        text=text.strip(),
        metadata={"suffix": file_path.suffix.lower()},
    )
