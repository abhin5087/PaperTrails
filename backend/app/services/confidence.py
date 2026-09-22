"""Extraction confidence score: 0-100, plus which signals fed into it."""

REQUIRED_HEADER_FIELDS = ("course_code", "exam_type", "semester", "max_marks")


def level_for(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def score(
    *,
    pdf_type: str,
    header: dict,
    questions: list[dict],
    marks_extracted: int,
    max_marks: int | None,
) -> tuple[int, dict, list[str]]:
    notes: list[str] = []
    breakdown: dict[str, int] = {}

    # Header completeness - up to 25 points.
    present = sum(1 for f in REQUIRED_HEADER_FIELDS if header.get(f))
    header_score = round(25 * present / len(REQUIRED_HEADER_FIELDS))
    breakdown["header"] = header_score
    if present < len(REQUIRED_HEADER_FIELDS):
        missing = [f for f in REQUIRED_HEADER_FIELDS if not header.get(f)]
        notes.append(f"Header missing: {', '.join(missing)}")

    # Questions detected - up to 35 points.
    if not questions:
        breakdown["questions"] = 0
        notes.append("No questions detected")
    else:
        q_score = 35 if len(questions) >= 5 else round(35 * len(questions) / 5)
        breakdown["questions"] = q_score

    # Marks validation - up to 30 points.
    if max_marks is None:
        breakdown["marks_validation"] = 0
        notes.append("Could not verify marks: max marks not found in header")
    elif marks_extracted == max_marks:
        breakdown["marks_validation"] = 30
    else:
        diff = abs(max_marks - marks_extracted)
        breakdown["marks_validation"] = max(0, 30 - diff * 3)
        notes.append(
            f"Marks mismatch: extracted {marks_extracted}, paper states {max_marks}"
        )

    # PDF type penalty/bonus - up to 10 points.
    type_points = {"vector": 10, "ocr_text": 5, "scanned": 0}
    breakdown["pdf_type"] = type_points.get(pdf_type, 0)
    if pdf_type == "scanned":
        notes.append("Scanned image PDF: OCR not yet implemented")
    elif pdf_type == "ocr_text":
        notes.append("No ruled table found: used text-position extraction")

    total = sum(breakdown.values())
    return min(100, total), breakdown, notes
