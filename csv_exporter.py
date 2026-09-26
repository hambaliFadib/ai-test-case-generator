"""CSV export for validated test cases."""

import csv
from pathlib import Path

from models.csv_schema import CSV_COLUMNS
from models.test_case_model import TestCase
from validator import validate_test_cases


class CsvExportError(OSError):
    """Raised when test cases cannot be exported to CSV."""


def export_to_csv(test_cases: list[TestCase], output_path: str | Path) -> Path:
    """Validate test cases and write the exact CSV schema to disk."""

    validate_test_cases(test_cases)
    destination = Path(output_path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for test_case in test_cases:
                writer.writerow(_to_row(test_case))
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
        "language_target": test_case.language_target,
        "generated_at": test_case.generated_at,
    }


def _pipe_join(values: list[str]) -> str:
    """Serialize a multi-value field using the contract's pipe separator."""

    return "|".join(value.replace("|", "\\|") for value in values)
