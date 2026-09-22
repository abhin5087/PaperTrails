"""OCR-text PDF extraction for scanned/photographed exam papers.

The PDF can be a raster scan with an OCR text layer.  For that kind of paper,
pdfplumber's raw extracted text preserves the document's reading order better
than trying to infer table columns from x-coordinates.

This module therefore:
  1. Reads all OCR text lines across the whole document.
  2. Detects genuine question openers only when a numbered label is followed
     by punctuation (``01.``, ``02)``, etc.).
  3. Handles OCR-fused labels such as ``09.U sing``.
  4. Handles the document-specific ``1G.`` -> ``10.`` OCR error, but only
     when question 10 is the next expected question.
  5. Rejects diagram IP addresses such as ``16.0.0.1`` and graph-axis text
     such as ``1 2 3 4 ...`` as question openers.
  6. Ignores document header/footer content before the first question.
  7. Extracts marks / Module / CO / BL from the complete question body.
"""

import re

import pdfplumber


# Marks can appear as [5], (5 Marks), and OCR occasionally produces mixed
# delimiters such as (5] or [10).
MARKS_RE = re.compile(
    r"(?:\((\d{1,2})\s*Marks?\)|"
    r"\[(\d{1,2})\]|"
    r"[\(\[](\d{1,2})\s*(?:Marks?\s*)?[\)\]])",
    re.IGNORECASE,
)

CO_RE = re.compile(r"\bCO\s*(\d)\b", re.IGNORECASE)
BL_RE = re.compile(r"\bBL\s*(\d)\b", re.IGNORECASE)
MODULE_RE = re.compile(r"\bModule\s*[:\-]?\s*(\d)\b", re.IGNORECASE)

# IMPORTANT: do not allow a whitespace-only separator after the number.
# Otherwise a chart axis like "1 2 3 4 ..." can become a fake question.
QNO_RE = re.compile(r"^\s*(\d{1,2})\s*[\.)](.*)$")

# Known OCR error in this document: 10. -> 1G.
OCR_10_RE = re.compile(r"^\s*1[Gg]\s*[\.)](.*)$")

# A valid question body may begin with a normal letter, a parenthesized
# subpart "(i)" / "(a)", or a bracket.  A digit is deliberately rejected
# because it makes an IP address such as "16.0.0.1" look like "16.".
QUESTION_BODY_START_RE = re.compile(r"^[A-Za-z(\[]")

PAGE_FOOTER_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE)


def _is_valid_question_body(body: str) -> bool:
    """Reject numeric/diagram noise after a would-be question label."""
    body = body.lstrip()
    return not body or bool(QUESTION_BODY_START_RE.match(body))


def _match_question_label(
    line: str,
    expected_number: int | None = None,
) -> tuple[str, str] | None:
    """Return (question_number, body) when a line opens a real question.

    Supported examples:
      01. Enlist...
      09.U sing...
      10. You are...
      1G. You are...   -> 10. when 10 is expected
      13. (a) Illustrate...

    Rejected examples:
      16.0.0.1
      1 2 3 4 5 ...
    """
    match = QNO_RE.match(line)
    if match:
        number = match.group(1)
        body = match.group(2).strip()

        if _is_valid_question_body(body):
            return number, body

    # Narrow OCR tolerance: only fix the known 10-label corruption and only
    # when sequential numbering says question 10 is expected.
    match = OCR_10_RE.match(line)
    if match and expected_number == 10:
        body = match.group(1).strip()

        if _is_valid_question_body(body):
            return "10", body

    return None


def _extract_fields(
    text: str,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """Extract inline metadata and return cleaned question text."""
    marks_match = MARKS_RE.search(text)
    marks = None

    if marks_match:
        marks = next(
            (group for group in marks_match.groups() if group is not None),
            None,
        )

    module_match = MODULE_RE.search(text)
    module = module_match.group(1) if module_match else None

    co_match = CO_RE.search(text)
    co = f"CO{co_match.group(1)}" if co_match else None

    bl_match = BL_RE.search(text)
    bl = f"BL{bl_match.group(1)}" if bl_match else None

    cleaned = MARKS_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned, marks, module, co, bl


def _document_lines(pdf: "pdfplumber.PDF") -> list[dict]:
    """Read OCR lines in document reading order across every page.

    Using extract_text() here is intentional.  For this scanned VIT paper,
    it keeps lines such as "1G. You are..." together and avoids the spatial
    reordering that occurs when the OCR word layer is reconstructed purely by
    x/y coordinates around diagrams.
    """
    lines: list[dict] = []

    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            # Do not let page footer text become part of the preceding
            # question body.
            if PAGE_FOOTER_RE.fullmatch(line):
                continue

            lines.append(
                {
                    "page": page_no,
                    "text": line,
                }
            )

    return lines


def _lines_to_questions(lines: list[dict]) -> list[dict]:
    """Merge lines into sequential top-level questions."""
    questions: list[dict] = []
    current: dict | None = None
    expected_number = 1

    for line_info in lines:
        line = line_info["text"]
        page_no = line_info["page"]

        match = _match_question_label(line, expected_number)

        if match:
            if current is not None:
                questions.append(current)

            question_no, body = match

            current = {
                "question_no": question_no,
                "raw_text": body,
                "page": page_no,
            }

            try:
                expected_number = int(question_no) + 1
            except ValueError:
                expected_number += 1

            continue

        # Ignore header/boilerplate/diagram text before the first question.
        if current is None:
            continue

        current["raw_text"] = f'{current["raw_text"]} {line}'.strip()

    if current is not None:
        questions.append(current)

    result: list[dict] = []

    for question in questions:
        cleaned, marks, module, co, bl = _extract_fields(
            question["raw_text"]
        )

        result.append(
            {
                "question_no": question["question_no"],
                "text": cleaned,
                "marks": int(marks) if marks and marks.isdigit() else None,
                "module": module,
                "co": co,
                "bl": bl,
                "page": question["page"],
            }
        )

    return result


def _extract_by_position(pdf: "pdfplumber.PDF") -> list[dict]:
    """Compatibility wrapper: parse OCR text lines without column clustering."""
    return _lines_to_questions(_document_lines(pdf))


def _extract_by_regex(pdf: "pdfplumber.PDF") -> list[dict]:
    """Fallback path using the same robust line parser."""
    return _lines_to_questions(_document_lines(pdf))


def extract(pdf: "pdfplumber.PDF") -> tuple[list[dict], str]:
    """Return (questions, method)."""
    questions = _extract_by_position(pdf)

    if len(questions) >= 2:
        return questions, "position"

    return _extract_by_regex(pdf), "regex"
