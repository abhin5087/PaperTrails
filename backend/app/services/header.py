"""Header metadata extraction - fixed VIT layout, plain regex."""

import re

HEADER_PATTERNS = {
    "course_code": r"\b([A-Z]{3,5}\d{3,4}[A-Z]?)\b",
    "exam_type": r"(CONTINUOUS ASSESSMENT TEST\s*[-\u2013]?\s*[IV]+|FINAL ASSESSMENT TEST)",
    "semester": r"(FALL|WINTER|SUMMER|WEEKEND)\s+SEMESTER\s+(\d{4}\s*[-\u2013]\s*\d{2,4})",
    "slot": r"SLOT\s*:?\s*([A-Z]\d\+?[A-Z0-9\+]*)",
    "max_marks": r"(?:Maximum\s+Marks|Max\.?\s*Marks)\s*:?\s*(\d+)",
    "duration": r"(?:Exam\s+Duration|Duration)\s*:?\s*([\w\s\.]{2,20})",
    "exam_date": r"(?:Date of Examination|Date)\s*:?\s*([\d]{1,2}[\.\-/][\d]{1,2}[\.\-/][\d]{2,4})",
}


def parse_header(text: str) -> dict:
    found: dict = {}
    for field, pattern in HEADER_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found[field] = " ".join(match.group(1).split())
            if field == "semester":
                found["academic_year"] = " ".join(match.group(2).split())
    return found
