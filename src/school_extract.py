"""PDF text extraction for applicant documents.

Per-page strategy for mixed corpora: native text first (fast, exact); if a page
yields almost nothing it is treated as a scan and sent to OCR -- but OCR is
OPTIONAL. If pytesseract / the tesseract binary are absent, scanned pages are
returned empty and flagged, and the UI tells the reviewer to check manually.
Native-text PDFs (like the synthetic set) never touch OCR at all.
"""
from __future__ import annotations
import io

import fitz  # PyMuPDF

try:  # OCR is an optional capability, not a hard dependency
    import pytesseract
    from PIL import Image
    _OCR_OK = True
except Exception:  # pragma: no cover
    _OCR_OK = False

MIN_NATIVE_CHARS = 20   # below this, a page is treated as scanned


def ocr_available() -> bool:
    if not _OCR_OK:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_pages(file_bytes: bytes, ocr_dpi: int = 300) -> list[dict]:
    """PDF bytes -> [{'page': int (1-based), 'text': str, 'ocr': bool}, ...]"""
    pages: list[dict] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            used_ocr = False
            if len(text) < MIN_NATIVE_CHARS and ocr_available():
                zoom = ocr_dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img).strip()
                used_ocr = True
            pages.append({"page": i, "text": text, "ocr": used_ocr})
    finally:
        doc.close()
    return pages


def full_text(pages: list[dict]) -> str:
    return "\n".join(p["text"] for p in pages)
