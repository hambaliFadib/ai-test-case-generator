# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

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
