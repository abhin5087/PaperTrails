"""PDF type detection: vector | ocr_text | scanned."""

import pdfplumber


def detect_pdf_type(pdf: "pdfplumber.PDF") -> str:
    page = pdf.pages[0]
    chars = len(page.chars)
    lines = len(page.lines) + len(page.rects)
    images = len(page.images)

    if chars == 0:
        return "scanned"
    if lines > 10:
        return "vector"
    if images > 0:
        return "ocr_text"
    return "ocr_text"


def diagnostics(pdf: "pdfplumber.PDF") -> dict:
    page = pdf.pages[0]
    return {
        "pages": len(pdf.pages),
        "characters_page1": len(page.chars),
        "table_lines_page1": len(page.lines) + len(page.rects),
        "images_page1": len(page.images),
    }
