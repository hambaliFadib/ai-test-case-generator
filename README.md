# AI Test Case Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![Contributions: By Approval Only](https://img.shields.io/badge/Contributions-By%20Approval%20Only-orange.svg)](CONTRIBUTING.md)

## What is this?

AI Test Case Generator is a CLI tool that accepts requirements documents (`.docx`, `.pdf`, `.md`) or plain text and generates structured, categorized test cases using any supported LLM through BYOK (Bring Your Own Key). Validated test cases are exported to CSV for QA use.

## Apa ini? (Bahasa Indonesia)

AI Test Case Generator adalah alat CLI yang menerima dokumen requirement (`.docx`, `.pdf`, `.md`) atau teks biasa, lalu menghasilkan test case yang terstruktur dan dikategorikan menggunakan LLM yang didukung melalui BYOK (Bring Your Own Key). Test case yang telah divalidasi diekspor ke CSV untuk kebutuhan QA.

## Features

- Flexible input: plain text, `.md`, `.docx`, and `.pdf`
- BYOK: Anthropic, OpenAI, Ollama, and OpenCode-compatible providers
- Test design techniques: EP, BVA, Negative, Edge, and Security
- Deterministic validation using Python logic, not LLM trust
- Traceability: each test case is linked to a source requirement
- Deduplication before export
- CSV output with an exact 11-column schema

## Architecture

```text
INPUT LAYER -> ANALYSIS LAYER -> GENERATION LAYER
      -> VALIDATION LAYER -> OUTPUT LAYER
```

- **Input layer** — `input_resolver.py` detects inline text or file paths; `parsers/` handles Markdown, DOCX, PDF, and plain text; `models/input_model.py` defines parsed input.
- **Analysis layer** — `requirement_analyzer.py` extracts requirements, acceptance criteria, constraints, and traceability IDs into `models/requirement_model.py`.
- **Generation layer** — `prompt_builder.py` creates the QA prompt, `llm_adapter.py` provides swappable BYOK providers, `response_parser.py` defensively parses responses, and `models/test_case_model.py` defines test cases.
- **Validation layer** — `validator.py` applies deterministic contract checks and `deduplicator.py` removes duplicate titles.
- **Output layer** — `csv_exporter.py` writes validated cases using the schema in `models/csv_schema.py`.

## Installation

### Prerequisites

- Python 3.11+
- pip

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

4. Fill in the provider settings in `.env`.

## Configuration (`.env`)

Example configuration:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_TIMEOUT_SECONDS=120
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://opencode.ai/zen/go/v1
OLLAMA_BASE_URL=http://localhost:11434
```

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | Provider name: `anthropic`, `openai`, or `ollama`. |
| `LLM_MODEL` | Provider-specific model string, such as `claude-sonnet-4-6`, `gpt-4o`, or `mimo-v2.5`. |
| `LLM_TIMEOUT_SECONDS` | Request timeout in seconds; default is `120`. |
| `ANTHROPIC_API_KEY` | Required when `LLM_PROVIDER=anthropic`. |
| `OPENAI_API_KEY` | Required when `LLM_PROVIDER=openai`. |
| `OPENAI_BASE_URL` | Optional endpoint for OpenAI-compatible providers such as OpenCode/MiMo. |
| `OLLAMA_BASE_URL` | Required when `LLM_PROVIDER=ollama`; defaults to `http://localhost:11434`. |

Never commit `.env` or expose API keys. Use `.env.example` as the shareable template.

## Usage

From plain text:

```powershell
python main.py --text "As a user I want to log in so that I can access my account." --output output/test.csv
```

From a Markdown file:

```powershell
python main.py --input requirements.md --output output/test.csv
```

From a DOCX file:

```powershell
python main.py --input requirements.docx --output output/test.csv
```

From a PDF file:

```powershell
python main.py --input requirements.pdf --output output/test.csv
```

With verbose output:

```powershell
python main.py --input requirements.md --output output/test.csv --verbose
```

Override provider and model:

```powershell
python main.py --input requirements.md `
               --provider anthropic `
               --model claude-sonnet-4-6 `
               --output output/test.csv
```

Specify a language target:

```powershell
python main.py --input requirements.md `
               --language python `
               --output output/test.csv
```

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
| `language_target` | `python` / `javascript` / `typescript` / `java` / `manual` |
| `generated_at` | ISO 8601 UTC timestamp |

The columns are written in this exact order:

```text
id,title,category,priority,preconditions,steps,expected_result,technique,requirement_ref,language_target,generated_at
```

## Supported Providers

| Provider | `LLM_PROVIDER` | Key variable | Notes |
|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Claude models |
| OpenAI | `openai` | `OPENAI_API_KEY` | GPT models |
| OpenCode | `openai` | `OPENAI_API_KEY` | Set `OPENAI_BASE_URL` to the OpenCode endpoint |
| Ollama | `ollama` | - | Local models; set `OLLAMA_BASE_URL` |

## Roadmap

- [ ] v1.1 — PDF scanned document support (OCR)
- [ ] v1.2 — Web UI (optional, alongside CLI)
- [ ] v1.3 — Direct export to Jira/TestRail
- [ ] v2.0 — Multi-requirement parallel generation
- [ ] v2.1 — Existing test framework context injection

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

Contributions are by approval only. All pull requests require review and approval from [@hambaliFadib](https://github.com/hambaliFadib).

## License

MIT License — Copyright 2026 hambaliFadib
