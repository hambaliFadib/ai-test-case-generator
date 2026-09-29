"""HTTP routes for generation, configuration, health, and CSV export."""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from config import SUPPORTED_PROVIDERS, load_settings
from csv_exporter import export_to_csv, export_traceable_to_csv
from coverage_planner import SUPPORTED_PROFILES
from generation_orchestrator import generate_test_suite
from input_resolver import resolve_input
from models.test_case_model import TestCase
from security_utils import redact_sensitive_detail
from validator import validate_test_cases


router = APIRouter()


class TextGenerationRequest(BaseModel):
    """Request body for generation from inline requirement text."""

    text: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    language: str = "manual"
    output_language: str = "en"
    profile: str = "balanced"


class ExportRequest(BaseModel):
    """Request body containing test cases to export as CSV."""

    test_cases: list[dict[str, Any]]
    filename: str = "test_cases"


@router.get("/health", response_model=None)
def health() -> dict[str, str]:
    """Return the web API health status and version."""

    return {"status": "ok", "version": "1.3.0"}


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
        return _generate(
            parsed_input,
            request.provider,
            request.model,
            request.language,
            request.output_language,
            request.profile,
        )
    except Exception as exc:
        return _error_response("Generation failed", exc)


@router.post("/generate/file", response_model=None)
async def generate_file(
    file: UploadFile = File(...),
    provider: str | None = Form(default=None),
    model: str | None = Form(default=None),
    language: str = Form(default="manual"),
    output_language: str = Form(default="en"),
    profile: str = Form(default="balanced"),
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
            return _generate(parsed_input, provider, model, language, output_language, profile)
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
            exporter = (
                export_traceable_to_csv
                if all(test_case.scenario_ref.strip() for test_case in cases)
                else export_to_csv
            )
            csv_path = exporter(cases, Path(temp_dir) / "test_cases.csv")
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
    output_language: str = "en",
    profile: str = "balanced",
) -> dict[str, Any]:
    """Run the shared Phase 3 generation engine for one Web request."""

    if output_language not in ("en", "id"):
        output_language = "en"  # safe fallback for unsupported output languages
    if profile not in SUPPORTED_PROFILES:
        supported = ", ".join(SUPPORTED_PROFILES)
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid profile", "detail": f"Choose one of: {supported}."},
        )
    settings = load_settings(provider_override=provider, model_override=model)
    result = generate_test_suite(
        parsed_input,
        settings,
        language_target=language,
        output_language=output_language,
        profile=profile,
    )
    payload = _serialize_result(result, profile)
    if result.status == "failed":
        payload["error"] = "Generation failed"
        return JSONResponse(status_code=500, content=payload)
    return payload


def _serialize_result(result: Any, profile: str) -> dict[str, Any]:
    """Expose stable, non-sensitive GenerationResult metadata to Web clients."""

    return {
        "status": result.status,
        "profile": profile,
        "requirement_count": result.requirement_count,
        "testable_requirement_count": result.testable_requirement_count,
        "excluded_requirement_count": result.excluded_requirement_count,
        "scenario_count": result.scenario_count,
        "generated_count": result.generated_count,
        "coverage_percentage": result.coverage_percentage,
        "batch_count": result.batch_count,
        "backfill_count": result.backfill_count,
        "missing_scenarios": list(result.missing_scenarios),
        "test_cases": [asdict(test_case) for test_case in result.test_cases],
        "unexpected_scenarios": list(result.unexpected_scenarios),
        "duplicate_scenarios": list(result.duplicate_scenarios),
        "initial_generated_count": result.initial_generated_count,
        "initial_missing_scenarios": list(result.initial_missing_scenarios),
        "diagnostics": [_redact(diagnostic) for diagnostic in result.diagnostics],
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

    return redact_sensitive_detail(detail)
