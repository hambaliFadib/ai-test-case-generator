# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

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
