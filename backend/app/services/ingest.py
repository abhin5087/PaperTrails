"""Orchestrates: detect -> extract -> score -> persist."""

import json
import shutil
import uuid
from pathlib import Path

import pdfplumber
from sqlalchemy.orm import Session

from ..config import JSON_DIR, PDF_DIR
from ..models import Course, Paper, Question
from . import confidence, header as header_service
from . import ocr_text_extractor, scanned_extractor, vector_extractor
from .detector import detect_pdf_type, diagnostics


def _save_upload(file_bytes: bytes, original_filename: str) -> Path:
    suffix = Path(original_filename).suffix or ".pdf"
    dest = PDF_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(file_bytes)
    return dest


def _get_or_create_course(db: Session, code: str | None) -> Course:
    code = code or "UNKNOWN"
    course = db.query(Course).filter(Course.code == code).one_or_none()
    if course is None:
        course = Course(code=code)
        db.add(course)
        db.flush()
    return course


def run_pipeline(db: Session, file_bytes: bytes, original_filename: str) -> Paper:
    pdf_path = _save_upload(file_bytes, original_filename)

    with pdfplumber.open(pdf_path) as pdf:
        diag = diagnostics(pdf)
        pdf_type = detect_pdf_type(pdf)

        first_page_text = pdf.pages[0].extract_text() or ""
        meta = header_service.parse_header(first_page_text)

        if pdf_type == "vector":
            questions = vector_extractor.extract(pdf)
            method = "table"
        elif pdf_type == "ocr_text":
            questions, method = ocr_text_extractor.extract(pdf)
        else:
            questions, method = scanned_extractor.extract(pdf)

    marks_extracted = sum(
        q["marks"] for q in questions if isinstance(q["marks"], int)
    )
    max_marks = int(meta["max_marks"]) if meta.get("max_marks", "").isdigit() else None

    conf_score, breakdown, notes = confidence.score(
        pdf_type=pdf_type,
        header=meta,
        questions=questions,
        marks_extracted=marks_extracted,
        max_marks=max_marks,
    )

    course = _get_or_create_course(db, meta.get("course_code"))

    paper = Paper(
        course_id=course.id,
        original_filename=original_filename,
        pdf_path=str(pdf_path),
        pdf_type=pdf_type,
        extraction_method=method,
        exam_type=meta.get("exam_type"),
        semester=meta.get("semester"),
        academic_year=meta.get("academic_year"),
        slot=meta.get("slot"),
        max_marks=max_marks,
        duration=meta.get("duration"),
        exam_date=meta.get("exam_date"),
        marks_extracted=marks_extracted,
        confidence=conf_score,
        confidence_breakdown=breakdown,
        notes=notes,
    )
    db.add(paper)
    db.flush()

    for q in questions:
        db.add(Question(
            paper_id=paper.id,
            question_no=q["question_no"] or "?",
            text=q["text"],
            marks=q["marks"],
            module=q["module"],
            co=q["co"],
            bl=q["bl"],
            page=q["page"],
        ))

    json_path = JSON_DIR / f"paper_{paper.id}.json"
    json_path.write_text(json.dumps({
        "course_code": course.code,
        "exam_type": paper.exam_type,
        "semester": paper.semester,
        "max_marks": paper.max_marks,
        "diagnostics": diag,
        "questions": questions,
    }, indent=2))
    paper.json_path = str(json_path)

    db.commit()
    db.refresh(paper)
    return paper
