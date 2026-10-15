# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Coverage planner preserves conditional "provides" behavior and gives explicit numeric boundaries precedence over presence classification.
- Explicit system actions, including modal predicates and predicates not enumerated in advance, are recognized as behavior without converting presence-only "provides" statements into actions.
- Expected-result echo detection recognizes single-letter option targets, plural passive wording, Indonesian action/result pairs, numbered or bulleted action steps, and save-action echoes.
- Coverage planner now distinguishes explicit actor actions from presence-only "provides" statements, preserving evidence refs while producing the appropriate behavior or visibility intent.
- Generated test cases with identical requirement-local preconditions, steps, and expected outcomes are rejected as duplicate content so the affected planned scenario remains eligible for bounded backfill.
- Semantic quality validation rejects an expected result that merely repeats a supported tester action instead of stating a separate observable outcome.

### Tests

- Added regression tests for "The user selects a period", presence-only "The system provides Logout", modal and unlisted system action predicates, Indonesian action echoes with list prefixes, save-action echoes, repeated action-only expected results, and requirement-local duplicate operational content.

## [1.3.2] - 2026-10-14

### Added

- Canonical coverage profiles `minimal`, `comprehensive`, and `extra`, with a shared `resolve_profile()` used by the CLI, Web API, and planner; legacy aliases `balanced` and `security` resolve to `comprehensive` and the default is now `comprehensive`
- Locked QA baseline evaluation with fixed, ordered, versioned rules: the authentication baseline (valid credentials, invalid username/password, both-invalid, empty fields, boundary, locked account, session, logout, MFA) plus authorization, CRUD, search, file-upload, API, error, state/session, confirmation, and navigation baselines
- `UnresolvedBaselineItem` (UBI) records: applicable baseline dimensions that lack sufficient product evidence or explicit product policy are retained in `unresolved_baseline` on the plan, the generation result, and the serialized API response — never dropped, never turned into scenarios
- Profile composition invariant `Minimal ⊆ Comprehensive ⊆ Extra` by `(category, technique, intent)`; security dimensions apply only in `comprehensive` and `extra`
- Contract test suite covering baseline applicability and evidence gates, no-invention corpus scanning, alias/default equivalence, deterministic planning, UBI contract and serialization, and the intact semantic gate
- Regression coverage added for requirement provenance, evidence-order preservation, quoted-literal ownership, scenario-specific masking guidance, and provider unavailability classification and recovery.

### Changed

- CLI `--profile` and the Web API now accept the canonical profiles and legacy aliases; unknown profiles fail with a message listing `minimal, comprehensive, extra`
- Serialized generation results expose the resolved canonical profile and the additive `unresolved_baseline` field; failed results carry an empty list
- Baseline dimensions are QA policy only: lockout thresholds, session timeouts, status codes, MFA prompts, and other concrete product semantics are never invented without explicit source evidence or product policy
- Evidence-first QA workbench redesign: navy accent (`#1E3A8A`), neutral surfaces with thin borders instead of shadows, simplified panel hierarchy, consistent radius and spacing. The navbar brand mark is temporarily removed while the project owner decides on the visual identity.
- Version synchronization: single source of truth in `app_version.py` (`APP_VERSION = "1.3.2"`); the FastAPI app metadata, `/api/health` response, and the Web UI version badge all read from it. The UI badge fetches the runtime version from `/api/health` instead of a hardcoded constant, and degrades gracefully if the request fails.
- Textual coverage feedback: the coverage indicator now states `Full coverage`, `Partial — N scenarios missing`, or `No coverage` alongside the bar, with planned/missing/shown counts and a button that opens the Evidence & diagnostics panel and jumps to the missing-scenarios list
- Workbench-level error region (`role="alert"`) so failed-with-cases generation reasons are visible after the compose panel collapses; CSV export success and failure messages are announced via `aria-live`
- Keyboard and touch accessibility: interactive targets raised to at least 44px, focus ring strengthened to meet 3:1 contrast in both themes, and motion timings standardized (hover/focus 140ms, content 180–200ms, drawer 200–240ms) with `prefers-reduced-motion` support

### Fixed

- Requirement provenance: constraints and evidence are now bounded to their owning requirement's document region, preventing evidence from a later requirement from contaminating an earlier requirement's constraint extraction.
- Constraint extraction now anchors to the exact statement line (via equality on cleaned markup) rather than the first line containing the statement as a substring, preventing constraint leakage when one requirement's statement appears as a substring within another line's text.
- Semantic quality literal-ownership validation now matches quoted UI literals against the scenario's own evidence atoms rather than performing bare-word substring matching, so an ordinary word like "Login" in evidence does not authorize a foreign quoted button literal from another requirement.
- Scenario authority model tightened: `own_texts` includes only atoms bound via `scenario.evidence_refs`, and `foreign_texts` includes same-requirement atoms not bound to the scenario, preventing sibling scenario evidence from authorizing literals in another scenario's test cases.
- Prompt guidance: password-specific masking guidance is only injected when the scenario's own authorized evidence explicitly prohibits displaying the password as plain text (co-occurrence check per evidence atom: "password" + "not &lt;verb&gt; ... as plain text" within the same atom), so evidence requiring a password to be displayed as plain text does not trigger masking guidance. Non-password non-disclosure evidence (e.g., an API token) receives neutral obfuscation guidance independently, and the presence of "password" in one evidence atom does not cause unrelated non-disclosure evidence to be interpreted as a password masking rule.
- Provider unavailability is classified solely from typed HTTP status (429 or 5xx), never from error-message text; a fully unavailable provider skips backfill instead of burning the retry budget on unrecoverable failures, while mixed-wave failures continue recovering through backfill.
- Decorative priority glyphs and the "AI"-styled brand mark removed; status is never conveyed by color alone
- Failed-with-cases error text was written to the compose error region after compose had collapsed, hiding the failure reason from the workbench
- Version badge was hardcoded to `v1.3.1` in JavaScript while the backend reported `1.3.0`, so displayed and API versions drifted
- Light-theme focus border (`#9BA8F8`) had only 2.25:1 contrast against white; now `#1E40AF` (≥3:1)

### Known issues (deferred to v1.3.3)

Non-blocking; deferred by owner decision for the v1.3.2 release:

- Coverage planner classification: `_looks_like_behavior()` can classify wording such as "The user selects a period." as observational/static evidence rather than an executable behavior scenario, and wording such as "The system provides Logout." can be classified as behavior rather than presence/visibility evidence.
- Test-case output quality: some invalid-credential cases may have duplicative content; some password-masking cases may have duplicative content; some expected results may repeat an action rather than clearly state the expected observable outcome.

## [1.3.1] - 2026-09-30

### Fixed

- Hardened the provider response contract so generated steps and expected results stay within the supplied scenario intent.
- Added item-level response salvage while preserving batch traceability and bounded backfill.
- Closed source-evidence coverage gaps with deterministic requirement-local mapping.
- Added typed semantic compatibility auditing for evidence and scenario intents.
- Prevented guardrails and unsupported behavior from becoming executable expectations.
- Preserved literal UI labels and explicit sample values in generated observable results.
- Tightened presence-only generation so it remains observational.

### Changed

- Coverage completeness now validates planned scenario coverage and deterministic source-evidence mapping.
- Planner and auditor semantics are stricter while retaining the traceable CSV and public integration contract.

## [1.3.0] - 2026-09-29

### Added

- Structured requirement parsing with explicit IDs and atomic/evidence-boundary behavior
- Deterministic coverage profiles, scenario planning, and bounded batch generation
- Scenario traceability, completeness auditing, and targeted backfill
- CLI and Web API integration through `generate_test_suite()`
- Coverage status and missing-scenario summaries in the Web UI
- v1.3 traceable CSV export with `requirement_ref` and `scenario_ref`

### Changed

- CLI exit codes now distinguish complete (`0`), failed (`1`), and partial (`2`) generation

## [1.2.3] - 2026-09-27

### Changed

- Web UI: removed the Configuration section from the UI
- Provider, model, and language are now configured via `.env` only
- Language target hardcoded to `"manual"` in all API calls
- Web UI redesigned with an Impeccable MCP audit (0 findings)
- Dark/light mode toggle with `localStorage` persistence
- Header and content container alignment fixed

## [1.2.2] - 2026-09-27

### Fixed

- Header aligned with the content container (max-width: 780px)
- Dark/light mode manual toggle added to the header
- `localStorage` persistence for the theme preference

## [1.2.1] - 2026-09-27

### Fixed

- `load_dotenv()` called before FastAPI startup
- `OPENAI_BASE_URL` and `x-opencode-session` now correctly loaded for Web UI requests

## [1.2.0] - 2026-09-27

### Added

- Web UI via FastAPI and vanilla HTML/CSS/JS on port 8001
- Text paste and `.docx` / `.pdf` / `.md` file upload input
- Provider, model, and language configuration controls
- Live test-case preview with expandable row details
- Category badges and CSV download from the browser
- API health, configuration, generation, and CSV export endpoints
- `web_server.py` entrypoint for starting the web UI

### Changed

- `requirements.txt`: added `fastapi`, `uvicorn`, and `python-multipart`

### Notes

- The existing CLI remains intact and unchanged
- The Web UI and CLI share the same generation pipeline

## [1.1.0] - 2026-09-26

### Added

- Scanned PDF support via Tesseract OCR (`pytesseract` + `pdf2image`)
- Auto-detection: text-based PDFs use the existing parser; scanned PDFs route to OCR
- Bilingual OCR: English and Bahasa Indonesia (`eng+ind`)
- `TESSERACT_CMD` environment variable for a custom Tesseract executable path
- `POPPLER_PATH` environment variable for a custom Poppler binary path
- `OcrError` with explicit messages for missing dependencies
- `(OCR)` source label in verbose output when the OCR path is used

### Changed

- `parsers/pdf_parser.py`: added OCR fallback for scanned PDFs
- `requirements.txt`: added `pytesseract`, `pdf2image`, and `Pillow`

### Notes

- Requires Tesseract OCR to be installed separately
- Requires Poppler to be installed separately on Windows
- Text-based PDF behavior remains backward compatible

## [1.0.0] - 2026-09-26

### Added

- Flexible input: plain text, `.md`, `.docx`, and `.pdf`
- BYOK support for Anthropic, OpenAI, Ollama, and OpenCode-compatible providers
- Five-layer architecture: Input, Analysis, Generation, Validation, and Output
- Test design techniques: EP, BVA, Negative, Edge, and Security
- Deterministic validation using Python logic rather than LLM trust
- Defensive JSON parsing with explicit error reporting
- Requirement traceability with sequential requirement IDs
- Title-based deduplication before export
- CSV export with the exact 11-column schema
- System-generated IDs using `TC-{YYYYMMDD}-{sequence}`
- System-generated UTC ISO 8601 timestamps
- CLI flags: `--input`, `--text`, `--output`, `--provider`, `--model`, `--language`, and `--verbose`
- Environment-based configuration without hardcoded secrets
- `.env.example` configuration template
- Bilingual open-source README documentation

