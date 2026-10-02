"""CLI entrypoint for the AI Test Case Generator."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from config import ConfigurationError, SUPPORTED_PROVIDERS, load_settings
from csv_exporter import CsvExportError, export_traceable_to_csv
from input_resolver import InputResolutionError, resolve_input
from generation_orchestrator import generate_test_suite
from models.test_case_model import TestCase
from profiles import CANONICAL_PROFILES, DEFAULT_PROFILE, resolve_profile
from security_utils import redact_sensitive_detail


def _profile_argument(value: str) -> str:
    """Resolve a CLI profile value, including legacy aliases."""

    try:
        return resolve_profile(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
    parser.add_argument(
        "--profile",
        type=_profile_argument,
        choices=CANONICAL_PROFILES,
        default=DEFAULT_PROFILE,
        help=(
            "Coverage profile used by the deterministic planner: "
            "minimal, comprehensive, or extra (legacy aliases balanced and "
            "security resolve to comprehensive)."
        ),
    )
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
        settings = load_settings(provider_override=args.provider, model_override=args.model)
        result = generate_test_suite(
            parsed_input,
            settings,
            language_target=args.language,
            profile=args.profile,
        )
        destination = None
        if result.test_cases:
            output_path = Path(args.output) if args.output else _default_output_path()
            destination = export_traceable_to_csv(result.test_cases, output_path)
    except (
        ConfigurationError,
        InputResolutionError,
        CsvExportError,
        ValueError,
    ) as exc:
        print(f"Error: {redact_sensitive_detail(str(exc))}", file=sys.stderr)
        return 1

    print(
        f"Status: {result.status}\n"
        f"Requirements parsed: {result.requirement_count}\n"
        f"Testable requirements: {result.testable_requirement_count}\n"
        f"Excluded/non-testable requirements: {result.excluded_requirement_count}\n"
        f"Planned scenarios: {result.scenario_count}\n"
        f"Generated test cases: {result.generated_count}\n"
        f"Coverage: {result.coverage_percentage:.2f}%\n"
        f"Initial batch count: {result.batch_count}\n"
        f"Backfill LLM calls: {result.backfill_count}\n"
        f"Missing scenario count: {len(result.missing_scenarios)}\n"
        f"Profile: {args.profile}\n"
        f"Provider: {settings.provider}; model: {settings.model}"
    )
    if args.verbose and result.missing_scenarios:
        print("Missing scenarios:")
        for scenario_id in result.missing_scenarios:
            print(f"  {scenario_id}")
    if args.verbose:
        print(f"Source: {parsed_input.source_name}")
    if destination is not None:
        print(f"Wrote {len(result.test_cases)} traceable test cases to {destination}")
    if result.status == "complete":
        return 0
    if result.status == "partial":
        return 2
    for diagnostic in result.diagnostics:
        print(f"Error: {redact_sensitive_detail(diagnostic)}", file=sys.stderr)
    return 1


def _default_output_path() -> Path:
    """Return the timestamped default output path."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return Path("output") / f"test_cases_{timestamp}.csv"


if __name__ == "__main__":
    raise SystemExit(main())
