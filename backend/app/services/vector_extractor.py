"""Vector PDF extraction - table objects do most of the work.

This is the original extract_questions.py logic, adapted to return
plain dicts instead of printing to stdout.
"""

import re

import pdfplumber

SUBPART = re.compile(r"(?=(?:^|\s)\(?([a-d]|i{1,3}|iv)\)\s)", re.MULTILINE)


def _clean(cell) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def _looks_like_header_row(row) -> bool:
    joined = " ".join(_clean(c).lower() for c in row)
    return "q.no" in joined or ("marks" in joined and "question" in joined)


def extract(pdf: "pdfplumber.PDF") -> list[dict]:
    rows = []
    for page_no, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables():
            for raw in table:
                if not raw or _looks_like_header_row(raw):
                    continue
                cells = [_clean(c) for c in raw]
                if not any(cells):
                    continue
                rows.append({"page": page_no, "cells": cells})

    questions: list[dict] = []
    last = {"label": "", "module": "", "co": "", "bl": ""}

    for row in rows:
        cells = row["cells"]
        label = cells[0] if len(cells) > 0 else ""
        body = cells[1] if len(cells) > 1 else ""
        rest = cells[2:] if len(cells) > 2 else []

        if not label and not body:
            continue

        if not label and questions:
            questions[-1]["text"] += " " + body
            continue

        module = marks = co = bl = ""
        for value in rest:
            if re.fullmatch(r"\d{1,2}", value) and not marks:
                marks = value
            elif re.fullmatch(r"\d", value) and not module:
                module = value
            elif re.fullmatch(r"CO\s*\d", value, re.IGNORECASE):
                co = value.replace(" ", "")
            elif re.fullmatch(r"(BL)?\s*\d", value, re.IGNORECASE) and not bl:
                bl = value

        label = label or last["label"]
        module = module or last["module"]
        co = co or last["co"]
        bl = bl or last["bl"]
        last = {"label": label, "module": module, "co": co, "bl": bl}

        pieces = [p.strip() for p in SUBPART.split(body) if p and p.strip()]
        parts = pieces if len(pieces) > 1 else [body]

        for index, part in enumerate(parts):
            suffix = f"({chr(97 + index)})" if len(parts) > 1 else ""
            inline = re.search(r"\((\d{1,2})\s*Marks?\)", part, re.IGNORECASE)
            questions.append({
                "question_no": f"{label}{suffix}",
                "text": re.sub(r"\(\d{1,2}\s*Marks?\)", "", part).strip(),
                "marks": inline.group(1) if inline else (marks or None),
                "module": module or None,
                "co": co or None,
                "bl": bl or None,
                "page": row["page"],
            })

    for q in questions:
        if isinstance(q["marks"], str) and q["marks"].isdigit():
            q["marks"] = int(q["marks"])
        elif not isinstance(q["marks"], int):
            q["marks"] = None

    return questions
