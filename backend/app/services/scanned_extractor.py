"""Scanned-image PDF path.

Placeholder for now: no text layer means no pdfplumber text/word extraction
will work, and this milestone does not wire up a vision/OCR model. Returns
an empty result with a clear note so the pipeline and UI can show a low
confidence score instead of silently failing.
"""


def extract(pdf) -> tuple[list[dict], str]:
    return [], "none"
