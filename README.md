# AI Test Case Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![Version: 1.3.1](https://img.shields.io/badge/Version-1.3.1-blue.svg)](CHANGELOG.md) [![Contributions: By Approval Only](https://img.shields.io/badge/Contributions-By%20Approval%20Only-orange.svg)](CONTRIBUTING.md)

---

## What is this? / Apa ini?

**English** — A CLI and Web UI tool that accepts requirements documents (`.docx`, `.pdf`, `.md`, or plain text) and generates structured, categorized test cases using any LLM via BYOK (Bring Your Own Key). Output is CSV. Scanned PDF documents are supported through OCR (Tesseract).

**Bahasa Indonesia** — Tools CLI dan Web UI yang menerima dokumen requirement (`.docx`, `.pdf`, `.md`, atau plain text) dan menghasilkan test case terstruktur menggunakan LLM pilihan kamu (BYOK — Bring Your Own Key). Output berupa CSV. PDF hasil scan didukung melalui OCR (Tesseract).

---

## Features

- Flexible input: plain text, `.md`, `.docx`, `.pdf`
- Scanned PDF support via Tesseract OCR (auto-detected)
- BYOK: Anthropic, OpenAI, Ollama, and OpenCode-compatible providers
- Web UI: clean interface with a dark/light mode toggle
- CLI: full command-line support
- Test design techniques: EP, BVA, Negative, Edge, Security
- Structured requirement IDs and scenario-level traceability (`requirement_ref` + `scenario_ref`)
- Coverage profiles: `minimal`, `comprehensive` (default), and `extra`; legacy aliases `balanced` and `security` resolve to `comprehensive`
- QA baseline evaluation with `UnresolvedBaselineItem` records for applicable dimensions that lack product evidence
- Deterministic scenario planning with bounded prompt batches
- Coverage auditing and targeted backfill with `complete`, `partial`, or `failed` outcomes
- Deterministic validation (Python contract checks, not LLM trust)
- Deduplication before export
- Legacy 11-column CSV remains available; v1.3 production export uses a traceable 12-column schema
- Configuration via `.env` (no UI configuration panel)

---

## Architecture

```text
INPUT LAYER -> ANALYSIS LAYER -> GENERATION LAYER
      -> VALIDATION LAYER -> OUTPUT LAYER
```

- **Input layer** — `input_resolver.py` detects inline text or file paths; `parsers/` handles Markdown, DOCX, PDF (text-based and scanned), and plain text; `models/input_model.py` defines parsed input.
- **Analysis layer** — `requirement_analyzer.py` extracts requirements, acceptance criteria, constraints, and traceability IDs into `models/requirement_model.py`.
- **Generation layer** — `prompt_builder.py` builds the QA prompt, `llm_adapter.py` provides swappable BYOK providers, `response_parser.py` defensively parses responses, and `models/test_case_model.py` defines test cases.
- **Validation layer** — `validator.py` applies deterministic contract checks and `deduplicator.py` removes duplicate titles.
- **Output layer** — `csv_exporter.py` writes validated cases using the schema in `models/csv_schema.py`.

**Web UI layer (v1.3.1)**

```text
WEB UI -> same generation pipeline as the CLI
FastAPI backend (port 8001) + single-page HTML frontend
```

- FastAPI backend (`web/app.py`, `web/router.py`) serving a single-page HTML/CSS/JS frontend (`web/static/index.html`).
- Shares the same `generate_test_suite()` pipeline as the CLI — one engine, two entrypoints.
- Configuration via `.env` only: there is no configuration panel in the UI.

---

## Installation

### Prerequisites

- Python 3.11+
- pip
- Tesseract OCR — required for scanned PDFs only
- Poppler — required for scanned PDFs only (Windows)

### Steps

1. Clone the repository:

   ```powershell
   git clone https://github.com/hambaliFadib/ai-test-case-generator.git
   cd ai-test-case-generator
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Fill in the values in `.env` (see below).

---

## Configuration (`.env`)

All provider and model settings live in `.env`, for both the CLI and the Web UI. Start from the shareable template in [`.env.example`](.env.example).

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Yes | `anthropic` / `openai` / `ollama`. Defaults to `anthropic` when unset. |
| `LLM_MODEL` | Yes | Model string, e.g. `mimo-v2.5`, `claude-sonnet-4-6`, or `gpt-4o`. Defaults to `claude-sonnet-4-6` when unset. |
| `LLM_TIMEOUT_SECONDS` | No | Request timeout in seconds. Default: `120`. |
| `ANTHROPIC_API_KEY` | If `anthropic` | Anthropic API key. |
| `OPENAI_API_KEY` | If `openai` | OpenAI or OpenCode-compatible API key. |
| `OPENAI_BASE_URL` | No | Custom OpenAI-compatible base URL (e.g. OpenCode Zen). Defaults to `https://opencode.ai/zen/go/v1` when unset. |
| `OLLAMA_BASE_URL` | No | Ollama server URL. Default: `http://localhost:11434`. |
| `TESSERACT_CMD` | If OCR | Path to `tesseract.exe` (Windows). |
| `POPPLER_PATH` | If OCR | Path to the Poppler `bin/` directory (Windows). |

Never commit `.env` or expose API keys.

---

## Usage — CLI

```powershell
# From plain text
python main.py --text "As a user I want to log in so that I can access my account." --output output/test.csv

# From a .md file
python main.py --input requirements.md --output output/test.csv

# From a .docx file
python main.py --input requirements.docx --output output/test.csv

# From a .pdf file (text-based or scanned — auto-detected)
python main.py --input requirements.pdf --output output/test.csv
```

With verbose output:

```powershell
python main.py --input requirements.md `
               --output output/test.csv --verbose
```

Override provider and model (otherwise `.env` is used):

```powershell
python main.py --input requirements.md `
               --provider anthropic `
               --model claude-sonnet-4-6 `
               --output output/test.csv
```

Choose a deterministic coverage profile (defaults to `comprehensive`):

```powershell
python main.py --input requirements.md --profile extra --output output/test.csv
```

Canonical profiles:

| Profile | Meaning |
|---|---|
| `minimal` | Evidence-derived base coverage, QA baseline evaluation with materialized dimensions and unresolved-baseline records, and evidence backfill. No deeper profile overlay. |
| `comprehensive` | Everything in `minimal`, plus deeper functional, negative, boundary, and state coverage; low-level security coverage where source evidence or product policy supports it; and source-backed edge/exploratory coverage. Default. |
| `extra` | Everything in `comprehensive`, plus additional evidence-supported exploratory combinations and depth, bounded by the evidence/atomic planning pipeline. |

Profiles select coverage depth only — they never change which product behaviors are treated as true. Legacy aliases `balanced` and `security` resolve to `comprehensive` (CLI and Web API compatibility only; they are not canonical profiles). Unknown profiles are rejected with a message listing the canonical profiles. `Minimal ⊆ Comprehensive ⊆ Extra` holds for every plan.

The CLI exits with `0` for complete coverage, `2` for usable partial coverage, and `1` for failed generation. Its summary includes planned scenarios, generated cases, coverage percentage, initial batches, backfill calls, and missing scenario IDs (with `--verbose`).

Set a language target (optional; defaults to `manual`):

```powershell
python main.py --input requirements.md `
               --language python `
               --output output/test.csv
```

If `--output` is omitted, the CSV is written to `output/test_cases_<timestamp>.csv`.

---

## Usage — Web UI (v1.3.1)

Start the web server:

```powershell
python web_server.py
```

Open in the browser:

```text
http://localhost:8001
```

Features:

- Paste text or upload a file (`.docx`, `.pdf`, `.md`)
- Generate test cases with one click and choose a coverage profile
- Preview results in the browser with category badges
- Expand rows to see full steps and expected result
- Download CSV directly from the browser
- Dark/light mode toggle (preference saved in `localStorage`)
- Coverage status, planned/generated counts, percentage, backfill calls, and missing scenario IDs are shown in the results

Note: the Web UI and the CLI share the same `generate_test_suite()` pipeline. The Web UI always sends `language: "manual"`.

## Coverage and traceability

The analyzer preserves explicit requirement IDs and their full document blocks. The deterministic planner extracts source evidence atoms, maps them within their requirement, and turns each testable requirement into source-backed scenario intents. Typed semantic compatibility auditing rejects mappings that would turn presence evidence into behavior or promote guardrails into executable expectations. Each scenario retains evidence and constraint references for scenario-level traceability.

Baseline evaluation keeps three layers distinct: the application-owned QA baseline policy (fixed, ordered, versioned rules such as the authentication baseline A1–A12), product evidence extracted from the source, and explicit product policy statements. A baseline dimension moves through `NOT_APPLICABLE → APPLICABLE_UNRESOLVED → MATERIALIZABLE → MATERIALIZED`; it materializes only when sufficient product evidence or explicit product policy supports it. Applicable dimensions that are unsupported are never dropped — they are retained as `UnresolvedBaselineItem` records in `unresolved_baseline` (planning) and in the serialized API result. UBIs are informational: they never become test cases, never receive scenario IDs, never enter the CSV, and do not affect `generated_count`, `coverage_percentage`, `missing_scenarios`, or generation status. Baseline dimensions are not permission to invent product behavior — lockout thresholds, session timeouts, HTTP status codes, MFA prompts, and similar concrete semantics are only planned when the source explicitly provides them.

Provider generation receives a minimal contract containing planned scenario intents and trace identifiers. Application-owned metadata is injected after parsing, and item-level response salvage/backfill remains bounded. Provider-authored `steps` and `expected_result` may operationalize the supplied scenario intent, but cannot introduce unsupported state changes, side effects, navigation outcomes, dialog behavior, persistence behavior, or other postconditions. Missing scenarios are sent through targeted backfill calls within a bounded retry budget. A result is `complete` only when every planned scenario is covered; valid but incomplete output is `partial`, and an unusable result is `failed`.

The Web API returns the status, requirement counts, planned and generated scenario counts, coverage percentage, initial batch count, backfill call count, missing IDs, the resolved canonical profile, the `unresolved_baseline` list, and traceable test cases. The production CLI and Web export use the v1.3 traceable CSV schema below.

---

## CSV Output Schema

| Column | Description |
|---|---|
| `id` | `TC-{YYYYMMDD}-{sequence}` |
| `title` | Short imperative test case title |
| `category` | `positive` / `negative` / `boundary` / `edge` / `security` |
| `priority` | `high` / `medium` / `low` |
| `preconditions` | Pipe-separated list |
| `steps` | Pipe-separated list |
| `expected_result` | Expected outcome |
| `technique` | `EP` / `BVA` / `negative` / `exploratory` / `security` |
| `requirement_ref` | Source requirement ID |
| `scenario_ref` | Deterministic planned scenario ID |
| `language_target` | `python` / `javascript` / `typescript` / `java` / `manual` (the Web UI always writes `manual`) |
| `generated_at` | ISO 8601 UTC timestamp |

Columns are written in this exact order:

```text
id,title,category,priority,preconditions,steps,expected_result,technique,requirement_ref,scenario_ref,language_target,generated_at
```

---

## Supported Providers

| Provider | `LLM_PROVIDER` | Key variable | Notes |
|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Claude models |
| OpenAI | `openai` | `OPENAI_API_KEY` | GPT models |
| OpenCode | `openai` | `OPENAI_API_KEY` | Set `OPENAI_BASE_URL` to the OpenCode endpoint |
| Ollama | `ollama` | - | Local models; set `OLLAMA_BASE_URL` |

---

## OCR Support (v1.1+)

Scanned PDFs are detected automatically: when a PDF yields fewer than 50 characters of extractable text, the OCR path is used instead.

Install:

- Tesseract OCR — https://github.com/UB-Mannheim/tesseract/wiki (select the Indonesian language pack during installation)
- Poppler for Windows — https://github.com/oschwartz10612/poppler-windows/releases

`.env` configuration:

```dotenv
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\Library\bin
```

OCR runs bilingually: English + Bahasa Indonesia (`eng+ind`).

---

## Roadmap

- [x] v1.0.0 — Core CLI tool
- [x] v1.1.0 — Scanned PDF OCR support
- [x] v1.2.0 — Web UI with dark/light mode
- [x] v1.3.0 — Deterministic coverage planning, completeness audit, backfill, Web/CLI integration, and traceable export
- [x] v1.3.1 — Source-evidence-complete planning, typed semantic auditing, and bounded provider generation
- [ ] v2.0 — Multi-requirement parallel generation
- [ ] v2.1 — Existing test framework context injection
- [ ] v2.2 — Language-aware generation (python -> pytest, js -> Jest, java -> JUnit)
- [ ] v2.3 — Configuration UI with BYOK API key input (provider + model selectable in the UI, key stored in session only)

---

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

Contributions are by approval only. An issue must be opened and approved first, and all pull requests require review and approval from [@hambaliFadib](https://github.com/hambaliFadib).

---

## License

MIT License — Copyright 2026 hambaliFadib
