"""CSV export for validated test cases."""

import csv
from pathlib import Path

from models.csv_schema import CSV_COLUMNS, TRACEABLE_CSV_COLUMNS
from models.test_case_model import TestCase
from validator import validate_test_cases


class CsvExportError(OSError):
    """Raised when test cases cannot be exported to CSV."""


def export_to_csv(test_cases: list[TestCase], output_path: str | Path) -> Path:
    """Validate test cases and write the exact CSV schema to disk."""

    return _export(test_cases, output_path, CSV_COLUMNS, require_scenario_ref=False)


def export_traceable_to_csv(test_cases: list[TestCase], output_path: str | Path) -> Path:
    """Write the v1.3 traceable CSV schema used by production generation."""

    return _export(test_cases, output_path, TRACEABLE_CSV_COLUMNS, require_scenario_ref=True)


def _export(
    test_cases: list[TestCase],
    output_path: str | Path,
    columns: tuple[str, ...],
    *,
    require_scenario_ref: bool,
) -> Path:
    validate_test_cases(test_cases)
    if require_scenario_ref:
        missing = [index for index, test_case in enumerate(test_cases) if not test_case.scenario_ref.strip()]
        if missing:
            raise CsvExportError(
                "Traceable export requires scenario_ref for every test case "
                f"(missing at rows: {', '.join(str(index + 2) for index in missing)})."
            )
    destination = Path(output_path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for test_case in test_cases:
                row = _to_row(test_case)
                writer.writerow({column: row[column] for column in columns})
    except OSError as exc:
        raise CsvExportError(f"Could not write CSV output '{destination}': {exc}") from exc
    return destination


def _to_row(test_case: TestCase) -> dict[str, str]:
    """Convert a test case into the exact CSV column representation."""

    return {
        "id": test_case.id,
        "title": test_case.title,
        "category": test_case.category,
        "priority": test_case.priority,
        "preconditions": _pipe_join(test_case.preconditions),
        "steps": _pipe_join(test_case.steps),
        "expected_result": test_case.expected_result,
        "technique": test_case.technique,
        "requirement_ref": test_case.requirement_ref,
        "scenario_ref": test_case.scenario_ref,
        "language_target": test_case.language_target,
        "generated_at": test_case.generated_at,
    }


def _pipe_join(values: list[str]) -> str:
    """Serialize a multi-value field using the contract's pipe separator."""

    return "|".join(value.replace("|", "\\|") for value in values)
