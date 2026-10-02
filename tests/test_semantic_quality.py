"""Quality Contract v1 regression tests.

Deterministic protection for requirement-local evidence binding, executable
steps, observable expected results, literal preservation, guardrail isolation,
evidence-bound security, backfill parity, and the locked profile/coverage/
fixture contracts. No LLM is involved anywhere in this module.
"""

import json
from pathlib import Path
import re

import pytest

from coverage_planner import plan_coverage
from generation_orchestrator import generate_test_suite
from models.coverage_model import EvidenceAtom, ScenarioIntent
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from models.requirement_model import Requirement
from profiles import (
    CANONICAL_PROFILES,
    DEFAULT_PROFILE,
    PROFILE_ALIASES,
    resolve_profile,
)
from prompt_builder import build_batch_prompt
from requirement_analyzer import analyze_requirements
from semantic_quality import build_authorities, validate_content


FIXTURE = Path(__file__).parent / "fixtures" / "ui_partial_result_mock.json"


def atom(requirement_ref: str, number: int, text: str, kind: str = "explicit_behavior") -> EvidenceAtom:
    return EvidenceAtom(
        id=f"{requirement_ref}-E{number:02d}",
        requirement_ref=requirement_ref,
        kind=kind,
        text=text,
    )


def scenario(
    requirement_ref: str,
    number: int = 1,
    intent: str = "Verify the documented behavior.",
    category: str = "positive",
    technique: str = "EP",
    refs: tuple[str, ...] = (),
) -> ScenarioIntent:
    return ScenarioIntent(
        id=f"{requirement_ref}-S{number:02d}",
        requirement_ref=requirement_ref,
        category=category,
        technique=technique,
        intent=intent,
        evidence_refs=refs,
    )


def check(item: dict, scn: ScenarioIntent, atoms: list[EvidenceAtom]) -> str | None:
    authorities = build_authorities([scn], atoms)
    return validate_content(
        title=item["title"],
        preconditions=item["preconditions"],
        steps=item["steps"],
        expected_result=item["expected_result"],
        authority=authorities[scn.id],
    )


def item(
    steps: list[str],
    expected_result: str,
    title: str = "Case under test",
    preconditions: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "preconditions": preconditions or [],
        "steps": steps,
        "expected_result": expected_result,
    }


# ---------------------------------------------------------------------------
# TEST 1 — cross-requirement leakage
# ---------------------------------------------------------------------------

def test_cross_requirement_password_masking_is_rejected() -> None:
    atoms = [
        atom("REQ-A", 1, "Password values are not displayed as plain text."),
        atom("REQ-B", 1, "Successful login displays Dashboard."),
    ]
    req_b = scenario(
        "REQ-B",
        intent="Verify the Dashboard is displayed after successful login.",
        refs=("REQ-B-E01",),
    )
    leaking = item(
        steps=["Enter the password into the \"Password\" field."],
        expected_result="The password is not displayed as plain text after login.",
    )
    error = check(leaking, req_b, atoms)
    assert error is not None
    assert "masking" in error or "password" in error

    benign = item(
        steps=["Click the \"Login\" button."],
        expected_result="The \"Dashboard\" page is displayed after login.",
    )
    assert check(benign, req_b, atoms) is None

    # The identical masking content is valid only for the requirement whose
    # evidence actually states it.
    req_a = scenario(
        "REQ-A",
        intent="Verify the password is masked in the password field.",
        refs=("REQ-A-E01",),
    )
    assert check(leaking, req_a, atoms) is None


def test_foreign_requirement_literal_reproduced_verbatim_is_rejected() -> None:
    atoms = [
        atom("REQ-A", 1, 'The system shows "Invalid username or password" on failure.'),
        atom("REQ-B", 1, "Successful login displays Dashboard."),
        atom("REQ-B", 2, "The username field accepts text input."),
        atom("REQ-B", 3, "The password field accepts text input."),
    ]
    # REQ-B mentions the same entities, which is NOT authorization: shared UI
    # context never licenses another requirement's exact evidence.
    req_b = scenario(
        "REQ-B",
        intent="Verify the sign-in form fields behave as documented.",
        refs=("REQ-B-E01", "REQ-B-E02", "REQ-B-E03"),
    )
    leaking = item(
        steps=["Check the error message on the \"Login\" page."],
        expected_result='The system shows "Invalid username or password".',
    )
    error = check(leaking, req_b, atoms)
    assert error is not None
    assert "another requirement" in error


# ---------------------------------------------------------------------------
# TEST 2 — security placeholder rejection
# ---------------------------------------------------------------------------

def test_security_category_alone_never_authorizes_security_content() -> None:
    atoms = [atom("REQ-C", 1, "The username accepts alphanumeric characters.")]
    security = scenario(
        "REQ-C",
        intent="Verify security behavior for the Username field.",
        category="security",
        technique="security",
        refs=("REQ-C-E01",),
    )

    hollow = item(
        steps=["Enter alphanumeric characters into the \"Username\" field."],
        expected_result="The \"Username\" field accepts alphanumeric characters.",
    )
    error = check(hollow, security, atoms)
    assert error is not None
    assert "hollow security" in error

    invented = item(
        steps=["Check the \"Password\" field display."],
        expected_result="The \"Password\" field is not displayed as plain text.",
    )
    error = check(invented, security, atoms)
    assert error is not None
    assert "masking" in error


def test_security_content_is_accepted_when_evidence_supports_the_predicate() -> None:
    atoms = [atom("REQ-D", 1, "Password values are not displayed as plain text.")]
    security = scenario(
        "REQ-D",
        intent="Verify the password field masks the supplied value.",
        category="security",
        technique="security",
        refs=("REQ-D-E01",),
    )
    concrete = item(
        steps=["Check the \"Password\" field display."],
        expected_result="The \"Password\" value is not displayed as plain text.",
    )
    assert check(concrete, security, atoms) is None


# ---------------------------------------------------------------------------
# TEST 3 — executable step validation
# ---------------------------------------------------------------------------

def test_vague_steps_are_rejected_and_concrete_steps_accepted() -> None:
    scn = scenario("REQ-S", intent="Verify the Login button submits the form.")
    atoms: list[EvidenceAtom] = []

    vague = item(
        steps=["Amati perilaku yang dinyatakan."],
        expected_result="The form is submitted.",
    )
    error = check(vague, scn, atoms)
    assert error is not None
    assert "meta" in error or "internal" in error

    targetless = item(
        steps=["Perform the documented action."],
        expected_result="The form is submitted.",
    )
    error = check(targetless, scn, atoms)
    assert error is not None
    assert "concrete" in error

    generic_security = item(
        steps=["Periksa perilaku keamanan."],
        expected_result="The form is submitted.",
    )
    error = check(generic_security, scn, atoms)
    assert error is not None
    assert "internal/meta" in error

    concrete = item(
        steps=["Klik tombol \"Login\"."],
        expected_result="Form login terkirim melalui tombol \"Login\".",
    )
    assert check(concrete, scn, atoms) is None


# ---------------------------------------------------------------------------
# TEST 4 — observable expected result
# ---------------------------------------------------------------------------

def test_expected_result_must_be_observable() -> None:
    scn = scenario("REQ-O", intent="Verify the Dashboard appears after login.")
    steps = ["Klik tombol \"Login\"."]

    vague_expected = item(steps=steps, expected_result="Perilaku sesuai kebutuhan.")
    error = check(vague_expected, scn, [])
    assert error is not None
    assert "internal/meta" in error

    fulfilled = item(steps=steps, expected_result="Perilaku terpenuhi.")
    error = check(fulfilled, scn, [])
    assert error is not None
    assert "internal/meta" in error

    non_observable = item(steps=steps, expected_result="The system behaves correctly.")
    error = check(non_observable, scn, [])
    assert error is not None
    assert "observable" in error

    observable = item(
        steps=steps,
        expected_result="Sistem menampilkan halaman \"Dashboard\".",
    )
    assert check(observable, scn, []) is None


# ---------------------------------------------------------------------------
# TEST 5 — literal preservation
# ---------------------------------------------------------------------------

def _literal_atoms() -> list[EvidenceAtom]:
    return [
        atom(
            "REQ-L",
            1,
            'System shows the message "Invalid username or password" when login fails.',
        ),
        atom("REQ-L", 2, 'The system confirms "Logged in successfully" after valid credentials.'),
    ]


def test_exact_literal_is_preserved_and_accepted() -> None:
    scn = scenario(
        "REQ-L",
        intent="Verify the invalid credentials error message for Login.",
        refs=("REQ-L-E01",),
    )
    exact = item(
        steps=["Check the error message on the \"Login\" page."],
        expected_result='The system shows "Invalid username or password" when credentials are invalid.',
    )
    assert check(exact, scn, _literal_atoms()) is None


def test_corrupted_paraphrased_and_translated_literals_are_rejected() -> None:
    scn = scenario(
        "REQ-L",
        intent="Verify the login success confirmation.",
        refs=("REQ-L-E02",),
    )
    typo = item(
        steps=["Check the confirmation on the \"Login\" page."],
        expected_result='The system shows "Logged in successully".',
    )
    error = check(typo, scn, _literal_atoms())
    assert error is not None
    assert "literal" in error

    scn_message = scenario(
        "REQ-L",
        intent="Verify the invalid credentials error message for Login.",
        refs=("REQ-L-E01",),
    )
    paraphrase = item(
        steps=["Check the error message on the \"Login\" page."],
        expected_result='The system shows "Invalid user or password".',
    )
    error = check(paraphrase, scn_message, _literal_atoms())
    assert error is not None
    assert "literal" in error or "alternative" in error

    translation = item(
        steps=["Check the error message on the \"Login\" page."],
        expected_result='The system shows "Invalid username atau password".',
    )
    error = check(translation, scn_message, _literal_atoms())
    assert error is not None
    assert "literal" in error or "alternative" in error

    draft = item(
        steps=["Check the error message on the \"Login\" page."],
        expected_result='The system shows "Invalid username or password"; lebih tepatnya, the exact message appears.',
    )
    error = check(draft, scn_message, _literal_atoms())
    assert error is not None
    assert "internal/meta" in error or "literal" in error


# ---------------------------------------------------------------------------
# TEST 6 — alternative/hedged outcome rejection
# ---------------------------------------------------------------------------

def test_hedged_expected_outcomes_are_rejected() -> None:
    scn = scenario("REQ-H", intent="Verify the form is submitted.")
    steps = ["Klik tombol \"Submit\"."]

    hedged_id = item(steps=steps, expected_result="Ditolak atau dicegah.")
    error = check(hedged_id, scn, [])
    assert error is not None
    assert "alternative" in error

    hedged_en = item(
        steps=steps,
        expected_result="The form is submitted or an error is shown.",
    )
    error = check(hedged_en, scn, [])
    assert error is not None
    assert "alternative" in error

    determinate = item(steps=steps, expected_result="The form is submitted.")
    assert check(determinate, scn, []) is None


def test_evidence_defined_alternative_is_not_a_hedge() -> None:
    atoms = [atom("REQ-H2", 1, 'The picker accepts "Red" or "Blue".')]
    scn = scenario(
        "REQ-H2",
        intent="Verify the picker accepts the documented colors.",
        refs=("REQ-H2-E01",),
    )
    supported = item(
        steps=["Select an option in the \"Picker\" field."],
        expected_result='The picker accepts "Red" or "Blue".',
    )
    assert check(supported, scn, atoms) is None


# ---------------------------------------------------------------------------
# TEST 7 — guardrail/meta leakage
# ---------------------------------------------------------------------------

def test_guardrail_language_never_reaches_testcase_fields() -> None:
    scn = scenario("REQ-G", intent="Verify the form submits.")
    steps = ["Klik tombol \"Login\"."]

    samples = [
        'Form login dikirim; perilaku lain tidak diasumsikan.',
        "Form login dikirim; perilaku yang dijelaskan terpenuhi.",
        "Semantik yang tidak dinyatakan diabaikan.",
        "The behavior is fulfilled as stated.",
        "Hasil sesuai yang dinyatakan.",
        "The system behaves as described.",
    ]
    for expected in samples:
        error = check(item(steps=steps, expected_result=expected), scn, [])
        assert error is not None, expected
        assert "internal/meta" in error, expected

    meta_title = item(
        steps=steps,
        expected_result="The form is submitted.",
        title="Verify the described security behavior",
    )
    error = check(meta_title, scn, [])
    assert error is not None
    assert "internal/meta" in error

    meta_precondition = item(
        steps=steps,
        expected_result="The form is submitted.",
        preconditions=["The behavior described above is noted."],
    )
    error = check(meta_precondition, scn, [])
    assert error is not None
    assert "internal/meta" in error


# ---------------------------------------------------------------------------
# TEST 8 — explicit multi-evidence combination
# ---------------------------------------------------------------------------

def test_multi_evidence_content_requires_explicit_scenario_binding() -> None:
    atoms = [
        atom("REQ-X", 1, "Period Field accepts values up to 10."),
        atom("REQ-X", 2, "The password value is not displayed as plain text."),
    ]
    combined = item(
        steps=["Enter a password into the \"Password\" field."],
        expected_result=(
            "The \"Password\" value is not displayed as plain text and "
            "Period Field accepts values up to 10."
        ),
    )

    bound_to_both = scenario(
        "REQ-X",
        intent="Verify the combined Period Field and password display behavior.",
        refs=("REQ-X-E01", "REQ-X-E02"),
    )
    assert check(combined, bound_to_both, atoms) is None

    bound_to_one = scenario(
        "REQ-X",
        intent="Verify the Period Field accepts values up to 10.",
        refs=("REQ-X-E01",),
    )
    error = check(combined, bound_to_one, atoms)
    assert error is not None
    assert "masking" in error or "password" in error


# ---------------------------------------------------------------------------
# TEST 9 — backfill uses the identical semantic gate
# ---------------------------------------------------------------------------

def _parsed_input(requirement_count: int) -> ParsedInput:
    lines: list[str] = []
    for index in range(1, requirement_count + 1):
        lines.extend(
            [
                f"### REQ-{index:03d} — Requirement {index}",
                "The page displays a source-backed value.",
                "",
            ]
        )
    return ParsedInput("markdown", "semantic_quality.md", "\n".join(lines))


def _prompt_scenario_refs(prompt: str) -> list[str]:
    planned = prompt.split("Planned scenarios for this batch:", 1)[-1]
    return re.findall(r'"scenario_ref":\s*"([^"]+)"', planned)


class _Adapter:
    def __init__(self, responder) -> None:
        self.responder = responder
        self.prompts: list[str] = []

    def generate_result(self, prompt: str) -> LLMResult:
        self.prompts.append(prompt)
        return self.responder(prompt, len(self.prompts))


def test_backfill_cannot_bypass_the_semantic_quality_gate() -> None:
    def responder(prompt: str, _: int) -> LLMResult:
        items = []
        for ref in _prompt_scenario_refs(prompt):
            if ref.startswith("REQ-002"):
                items.append(
                    {
                        "scenario_ref": ref,
                        "title": f"Case for {ref}",
                        "preconditions": [],
                        "steps": ["Amati perilaku yang dinyatakan."],
                        "expected_result": "Perilaku terpenuhi.",
                    }
                )
            else:
                items.append(
                    {
                        "scenario_ref": ref,
                        "title": f"Case for {ref}",
                        "preconditions": [],
                        "steps": ["Check the \"Result\" field."],
                        "expected_result": "The \"Result\" field displays the source-backed value.",
                    }
                )
        return LLMResult(json.dumps(items), "fake")

    result = generate_test_suite(_parsed_input(2), None, adapter=_Adapter(responder))

    assert result.status == "partial"
    assert result.missing_scenarios == ["REQ-002-S01"]
    assert result.backfill_count == 2
    assert result.generated_count == 1
    diagnostics = " ".join(result.diagnostics)
    assert "semantic quality" in diagnostics
    assert "internal/meta" in diagnostics


# ---------------------------------------------------------------------------
# TEST 10 — no coverage regression
# ---------------------------------------------------------------------------

def test_coverage_status_and_count_semantics_are_unchanged() -> None:
    def responder(prompt: str, _: int) -> LLMResult:
        items = []
        for ref in _prompt_scenario_refs(prompt):
            if ref.startswith("REQ-002"):
                items.append(
                    {
                        "scenario_ref": ref,
                        "title": f"Case for {ref}",
                        "preconditions": [],
                        "steps": ["Amati perilaku yang dinyatakan."],
                        "expected_result": "Perilaku terpenuhi.",
                    }
                )
            else:
                items.append(
                    {
                        "scenario_ref": ref,
                        "title": f"Case for {ref}",
                        "preconditions": [],
                        "steps": ["Check the \"Result\" field."],
                        "expected_result": "The \"Result\" field displays the source-backed value.",
                    }
                )
        return LLMResult(json.dumps(items), "fake")

    result = generate_test_suite(_parsed_input(2), None, adapter=_Adapter(responder))

    assert result.scenario_count == 2
    assert result.generated_count == len(result.test_cases) == 1
    assert result.coverage_percentage == 50.0
    assert result.missing_scenarios == ["REQ-002-S01"]
    assert result.status == "partial"
    assert all(case.scenario_ref for case in result.test_cases)

    # UBI records never become test cases and never enter the counts.
    auth = ParsedInput(
        "markdown",
        "auth.md",
        "### REQ-AUTH-001 — Login\nUser enters invalid credentials and sees an error message.\n",
    )
    plan = plan_coverage(analyze_requirements(auth), profile="comprehensive")
    assert plan.unresolved_baseline
    scenario_ids = {
        scn.id
        for req_plan in plan.requirements
        for scn in req_plan.scenarios
    }
    for ubi in plan.unresolved_baseline:
        assert ubi.rule_key not in scenario_ids
        assert ubi.requirement_ref not in {case.scenario_ref for case in result.test_cases}


# ---------------------------------------------------------------------------
# TEST 11 — profile regression
# ---------------------------------------------------------------------------

def test_canonical_profile_contract_is_unchanged() -> None:
    assert CANONICAL_PROFILES == ("minimal", "comprehensive", "extra")
    assert DEFAULT_PROFILE == "comprehensive"
    assert PROFILE_ALIASES == {"balanced": "comprehensive", "security": "comprehensive"}
    assert resolve_profile("balanced") == "comprehensive"
    assert resolve_profile("security") == "comprehensive"
    assert resolve_profile("extra") == "extra"
    with pytest.raises(ValueError):
        resolve_profile("balanced-profile")

    requirements = [
        Requirement(
            id="REQ-P-001",
            title="Search",
            statement="Search Content filters displayed rows.",
        ),
    ]

    def identities(profile: str):
        plan = plan_coverage(requirements, profile=profile)
        return {
            (scn.category, scn.technique, scn.intent)
            for req_plan in plan.requirements
            for scn in req_plan.scenarios
        }

    minimal = identities("minimal")
    comprehensive = identities("comprehensive")
    extra = identities("extra")
    assert minimal <= comprehensive <= extra
    assert identities("balanced") == comprehensive
    assert identities("security") == comprehensive
    assert not any(category == "security" for category, _, _ in minimal)
    assert any(category == "security" for category, _, _ in comprehensive)


# ---------------------------------------------------------------------------
# TEST 12 — fixture protection
# ---------------------------------------------------------------------------

def test_partial_result_fixture_remains_untouched() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # The legacy profile field must not be rewritten by the canonical-profile
    # or semantic-quality phases; the fixture documents API passthrough as-is.
    assert fixture["profile"] == "balanced"
    assert fixture["status"] == "partial"
    assert fixture["scenario_count"] == 205
    assert fixture["generated_count"] == 200
    assert len(fixture["missing_scenarios"]) == 6
    assert len(fixture["unexpected_scenarios"]) == 1


# ---------------------------------------------------------------------------
# Unsupported product facts require evidence (Rule I)
# ---------------------------------------------------------------------------

def test_unsupported_product_facts_require_evidence() -> None:
    scn = scenario("REQ-U", intent="Verify the API returns the documented response.")
    invented = item(
        steps=["Check the API response for a missing report."],
        expected_result="The request returns 404 when the report does not exist.",
    )
    error = check(invented, scn, [])
    assert error is not None
    assert "HTTP status code" in error

    atoms = [atom("REQ-U2", 1, "The API returns 404 when the report does not exist.")]
    scn2 = scenario(
        "REQ-U2",
        intent="Verify the documented 404 response for a missing report.",
        refs=("REQ-U2-E01",),
    )
    supported = item(
        steps=["Check the API response for a missing report."],
        expected_result="The request returns 404 when the report does not exist.",
    )
    assert check(supported, scn2, atoms) is None


# ---------------------------------------------------------------------------
# Prompt carries the scenario authority boundary
# ---------------------------------------------------------------------------

def test_batch_prompt_declares_scenario_authority_and_evidence_boundary() -> None:
    requirement = Requirement(
        id="REQ-A",
        title="Login",
        statement="Successful login displays Dashboard.",
    )
    scn = scenario(
        "REQ-A",
        intent="Verify the Dashboard is displayed after successful login.",
        refs=("REQ-A-E01",),
    )
    atoms = [atom("REQ-A", 1, "Successful login displays Dashboard.")]

    prompt = build_batch_prompt([requirement], [scn], evidence_atoms=atoms)

    assert "SCENARIO AUTHORITY" in prompt
    assert '"authorized_evidence"' in prompt
    assert "Successful login displays Dashboard." in prompt
    assert "forbidden as claims for this scenario" in prompt
    assert "determinate observable outcome" in prompt
    assert "Preserve exact source literals" in prompt
    # The scenario JSON stays last so prompt tools can split on the marker.
    assert "Planned scenarios for this batch:" in prompt
    assert prompt.strip().endswith("]")
