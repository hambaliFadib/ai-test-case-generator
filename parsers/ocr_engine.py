"""OCR engine for scanned PDF documents."""

import os
from pathlib import Path


class OcrError(RuntimeError):
    """Raised when OCR extraction fails."""


class OcrEngine:
    """Extract text from scanned PDFs using Tesseract and Poppler."""

    def __init__(self) -> None:
        """Load environment configuration and configure a custom Tesseract path."""

        from dotenv import load_dotenv

        load_dotenv()
        tesseract_cmd = os.environ.get("TESSERACT_CMD")
        if tesseract_cmd:
            try:
                import pytesseract
            except ImportError as exc:
                raise OcrError("pytesseract is not installed.") from exc
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._poppler_path: str | None = os.environ.get("POPPLER_PATH") or None

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Convert PDF pages to images and OCR them in English and Indonesian."""

        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError
        except ImportError as exc:
            raise OcrError("pdf2image is not installed.") from exc

        try:
            import pytesseract
        except ImportError as exc:
            raise OcrError("pytesseract is not installed.") from exc

        try:
            images = convert_from_path(
                pdf_path,
                dpi=300,
                fmt="RGB",
                poppler_path=self._poppler_path,
            )
        except PDFInfoNotInstalledError as exc:
            raise OcrError("Poppler is not installed. pdf2image requires poppler.") from exc
        except Exception as exc:
            raise OcrError(f"Failed to convert PDF to images: {exc}") from exc

        if not images:
            raise OcrError(f"OCR returned no pages for '{pdf_path}'.")

        page_texts: list[str] = []
        for image in images:
            try:
                page_texts.append(
                    pytesseract.image_to_string(
                        image,
                        lang="eng+ind",
                        config="--psm 3",
                    )
                )
            except pytesseract.TesseractNotFoundError as exc:
                raise OcrError("Tesseract is not installed or not found in PATH.") from exc
            except Exception as exc:
                raise OcrError(f"Tesseract OCR failed on page: {exc}") from exc

        combined = "\n\n".join(page_texts).strip()
        if not combined:
            raise OcrError(f"OCR returned empty text for all pages in '{pdf_path}'.")
        return combined
