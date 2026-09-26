# Contributing to AI Test Case Generator

## Contribution Policy

- This project accepts contributions by approval only.
- All pull requests must be reviewed and approved by `@hambaliFadib` before merging.
- Opening an issue first is required before submitting a pull request.
- Pull requests submitted without a linked issue will not be reviewed.

## How to Contribute

1. Open an issue describing what you want to fix or add.
2. Wait for approval or feedback from `@hambaliFadib`.
3. Fork the repository.
4. Create a branch:

   ```powershell
   git checkout -b fix/your-fix-name
   ```

5. Make your changes.
6. Test your changes manually against all input types (`.txt`, `.md`, `.docx`, `.pdf`).
7. Submit a pull request linked to the approved issue.

## Branch Naming Convention

```text
fix/short-description
feat/short-description
docs/short-description
refactor/short-description
```

## Code Standards

- Python 3.11+
- Type hints on all functions
- Docstrings on every class and public method
- No bare `except`; use explicit exception types
- Do not touch architecture layers without prior discussion
- Never commit API keys, `.env`, or other secrets
- Preserve the CSV schema unless a versioning discussion has been approved

## What Will NOT Be Accepted

- Pull requests without a linked issue
- Changes that collapse the layered architecture
- Hardcoded API keys or secrets
- Breaking changes to the CSV schema without versioning discussion
- Web UI additions; this is planned separately in the roadmap
