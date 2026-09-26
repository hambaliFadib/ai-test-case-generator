"""CLI entrypoint for the AI Test Case Generator."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from config import ConfigurationError, SUPPORTED_PROVIDERS, load_settings
from csv_exporter import CsvExportError, export_to_csv
from deduplicator import deduplicate_test_cases
from input_resolver import InputResolutionError, resolve_input
from llm_adapter import LLMError, create_adapter
from models.test_case_model import TestCase
from prompt_builder import build_prompt
from requirement_analyzer import RequirementAnalysisError, analyze_requirements
from response_parser import ParseError, ValidationError, parse_response
from validator import TestCaseValidationError, validate_test_cases


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(description="Generate QA test cases from requirements.")
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--input", dest="input_path", help="Requirement file (.docx, .pdf, or .md).")
    source.add_argument("--text", help="Inline requirement or user story text.")
    parser.add_argument(
        "--output",
        help="CSV output path.",
        default=None,
    )
    parser.add_argument(
        "--language",
        choices=TestCase.LANGUAGES,
        default="manual",
        help="Target test implementation language.",
    )
    parser.add_argument(
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        default=None,
        help="LLM provider override; otherwise LLM_PROVIDER is used.",
    )
    parser.add_argument("--model", default=None, help="LLM model override; otherwise LLM_MODEL is used.")
    parser.add_argument("--verbose", action="store_true", help="Print requirements and generation summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the end-to-end input, generation, validation, and CSV export workflow."""

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.input_path is None and args.text is None:
        parser.error("one of --input or --text is required")

    try:
        parsed_input = resolve_input(inline_text=args.text, input_path=args.input_path)
        requirements = analyze_requirements(parsed_input)
        settings = load_settings(provider_override=args.provider, model_override=args.model)
        prompt = build_prompt(requirements, language_target=args.language)
        adapter = create_adapter(settings)
        raw_response = adapter.generate(prompt)
        generated_cases = parse_response(raw_response)
        unique_cases = deduplicate_test_cases(generated_cases)
        validate_test_cases(unique_cases)
        output_path = Path(args.output) if args.output else _default_output_path()
        destination = export_to_csv(unique_cases, output_path)
    except (
        ConfigurationError,
        InputResolutionError,
        RequirementAnalysisError,
        LLMError,
        ParseError,
        ValidationError,
        TestCaseValidationError,
        CsvExportError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Source: {parsed_input.source_name}")
        print("Requirements:")
        for requirement in requirements:
            print(f"  {requirement.id}: {requirement.statement}")
        print(f"Generated cases: {len(generated_cases)}")
        print(f"After deduplication: {len(unique_cases)}")
        print(f"Provider: {settings.provider}; model: {settings.model}")
    print(f"Wrote {len(unique_cases)} validated test cases to {destination}")
    return 0


def _default_output_path() -> Path:
    """Return the timestamped default output path."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return Path("output") / f"test_cases_{timestamp}.csv"


if __name__ == "__main__":
    raise SystemExit(main())
