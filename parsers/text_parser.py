"""Parser for inline plain text requirements."""

from models.input_model import ParsedInput


class TextParseError(ValueError):
    """Raised when inline text is missing or blank."""


def parse_text(text: str, source_name: str = "inline text") -> ParsedInput:
    """Normalize inline requirement text into a parsed input model."""

    if not isinstance(text, str) or not text.strip():
        raise TextParseError("Requirement text must be a non-empty string.")
    return ParsedInput(source_type="text", source_name=source_name, text=text.strip())
