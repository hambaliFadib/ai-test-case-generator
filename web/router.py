"""HTTP routes for generation, configuration, health, and CSV export."""

from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from config import SUPPORTED_PROVIDERS, load_settings
from csv_exporter import export_to_csv
from deduplicator import deduplicate_test_cases
from input_resolver import resolve_input
from llm_adapter import create_adapter
from models.test_case_model import TestCase
from prompt_builder import build_prompt
from requirement_analyzer import analyze_requirements
from response_parser import parse_response
from validator import validate_test_cases


router = APIRouter()


class TextGenerationRequest(BaseModel):
    """Request body for generation from inline requirement text."""

    text: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    language: str = "manual"


class ExportRequest(BaseModel):
    """Request body containing test cases to export as CSV."""

    test_cases: list[dict[str, Any]]
    filename: str = "test_cases"


@router.get("/health", response_model=None)
def health() -> dict[str, str]:
    """Return the web API health status and version."""

    return {"status": "ok", "version": "1.2.0"}


@router.get("/config", response_model=None)
def config() -> dict[str, Any] | JSONResponse:
    """Return safe, non-secret LLM configuration for UI initialization."""

    try:
        settings = load_settings()
        return {
            "provider": settings.provider,
            "model": settings.model,
            "providers": list(SUPPORTED_PROVIDERS),
        }
    except Exception as exc:
        return _error_response("Configuration failed", exc, status_code=500)


@router.post("/generate/text", response_model=None)
def generate_text(request: TextGenerationRequest) -> dict[str, Any] | JSONResponse:
    """Generate test cases from inline requirement text."""

    try:
        parsed_input = resolve_input(inline_text=request.text)
        return _generate(parsed_input, request.provider, request.model, request.language)
    except Exception as exc:
        return _error_response("Generation failed", exc)


@router.post("/generate/file", response_model=None)
async def generate_file(
    file: UploadFile = File(...),
    provider: str | None = Form(default=None),
    model: str | None = Form(default=None),
    language: str = Form(default="manual"),
) -> dict[str, Any] | JSONResponse:
    """Generate test cases from a temporary uploaded DOCX, PDF, or Markdown file."""

    if not file.filename:
        return _error_response("Invalid upload", ValueError("An input filename is required."))
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".docx", ".pdf", ".md"}:
        return _error_response(
            "Invalid upload",
            ValueError("Supported upload formats are .docx, .pdf, and .md."),
        )

    try:
        content = await file.read()
        if not content:
            raise ValueError("Uploaded file is empty.")
        with tempfile.TemporaryDirectory(prefix="ai-tcg-upload-") as temp_dir:
            input_path = Path(temp_dir) / f"input{suffix}"
            input_path.write_bytes(content)
            parsed_input = resolve_input(input_path=input_path)
            return _generate(parsed_input, provider, model, language)
    except Exception as exc:
        return _error_response("Generation failed", exc)
    finally:
        await file.close()


@router.post("/export/csv", response_model=None)
def export_csv(request: ExportRequest) -> Response | JSONResponse:
    """Validate and return submitted test cases as a downloadable CSV file."""

    try:
        cases = [TestCase(**item) for item in request.test_cases]
        validate_test_cases(cases)
        safe_base = _safe_filename(request.filename)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        with tempfile.TemporaryDirectory(prefix="ai-tcg-export-") as temp_dir:
            csv_path = export_to_csv(cases, Path(temp_dir) / "test_cases.csv")
            csv_bytes = csv_path.read_bytes()
        headers = {
            "Content-Disposition": f'attachment; filename="{safe_base}_{timestamp}.csv"',
        }
        return Response(content=csv_bytes, media_type="text/csv", headers=headers)
    except Exception as exc:
        return _error_response("CSV export failed", exc)


def _generate(
    parsed_input: Any,
    provider: str | None,
    model: str | None,
    language: str,
) -> dict[str, Any]:
    """Run the shared requirement-to-test-case generation pipeline."""

    requirements = analyze_requirements(parsed_input)
    settings = load_settings(provider_override=provider, model_override=model)
    prompt = build_prompt(requirements, language_target=language)
    raw_response = create_adapter(settings).generate(prompt)
    generated_cases = parse_response(raw_response)
    validate_test_cases(generated_cases)
    unique_cases = deduplicate_test_cases(generated_cases)
    validate_test_cases(unique_cases)
    return {
        "test_cases": [asdict(test_case) for test_case in unique_cases],
        "count": len(unique_cases),
        "requirement_count": len(requirements),
    }


def _safe_filename(filename: str) -> str:
    """Return a safe filename stem without path separators or extensions."""

    stem = Path(filename or "test_cases").stem
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("._")
    return safe or "test_cases"


def _error_response(message: str, error: Exception, status_code: int = 400) -> JSONResponse:
    """Build a clear JSON error response with configured secrets redacted."""

    detail = _redact(str(error)) or message
    return JSONResponse(
        status_code=status_code,
        content={"error": message, "detail": detail},
    )


def _redact(detail: str) -> str:
    """Remove API key values from error details before returning them to clients."""

    redacted = detail
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(variable)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted
