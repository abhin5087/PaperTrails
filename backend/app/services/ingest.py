"""Orchestrates: extract -> score -> persist.

The extraction itself lives in :mod:`.pipeline`; this module is responsible
for turning its result into database rows and a JSON sidecar, and for making
sure every field the pipeline produced actually survives the round trip.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import FIGURE_DIR, JSON_DIR, PDF_DIR
from ..models import Course, Figure, Paper, Question
from . import confidence, pipeline

logger = logging.getLogger(__name__)


def _save_upload(file_bytes: bytes, original_filename: str) -> Path:
    suffix = Path(original_filename).suffix or ".pdf"
    dest = PDF_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(file_bytes)
    return dest


def _get_or_create_course(db: Session, code: str | None, name: str | None) -> Course:
    code = (code or "UNKNOWN").strip() or "UNKNOWN"
    course = db.query(Course).filter(Course.code == code).one_or_none()

    if course is None:
        course = Course(code=code, name=name)
        db.add(course)
        db.flush()
    elif name and not course.name:
        # Fill in a name we did not have before; never overwrite a known one.
        course.name = name

    return course


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def run_pipeline(db: Session, file_bytes: bytes, original_filename: str) -> Paper:
    """Process an uploaded PDF and persist everything extracted from it."""
    pdf_path = _save_upload(file_bytes, original_filename)

    result = pipeline.extract(str(pdf_path), figures_dir=FIGURE_DIR)
    header = result.header
    max_marks = _as_int(header.get("max_marks"))

    score = confidence.score(
        header=header,
        questions=result.questions,
        max_marks=max_marks,
        summary=result.summary,
    )

    course = _get_or_create_course(db, header.get("course_code"),
                                   header.get("course_name"))

    paper = Paper(
        course_id=course.id,
        original_filename=original_filename,
        pdf_path=str(pdf_path),
        pdf_type=result.summary.pdf_type,
        extraction_method=result.method,
        exam_type=header.get("exam_type"),
        semester=header.get("semester"),
        academic_year=header.get("academic_year"),
        slot=header.get("slot"),
        max_marks=max_marks,
        duration=header.get("duration"),
        exam_date=header.get("exam_date"),
        exam_time=header.get("exam_time"),
        course_name_raw=header.get("course_name"),
        marks_extracted=score.marks_extracted,
        confidence=score.total,
        confidence_breakdown=score.breakdown,
        notes=score.messages,
        diagnostics=[d.to_dict() for d in score.diagnostics],
        header_detail=header.to_detail(),
        extraction_detail=result.diagnostics_source,
        ocr_engine=("tesseract" if result.summary.ocr_used else None),
        ocr_config=result.summary.ocr_config if result.summary.ocr_used else None,
        ocr_confidence=result.summary.ocr_confidence,
        page_count=result.page_count,
    )
    db.add(paper)
    db.flush()

    for row in pipeline.extract_rows(result.questions):
        db.add(
            Question(
                paper_id=paper.id,
                question_no=row["question_no"] or "?",
                parent_no=row["parent_no"],
                text=row["text"],
                marks=row["marks"],
                marks_raw=row["marks_raw"],
                marks_parts=row["marks_parts"],
                marks_resolved=row["marks_resolved"],
                marks_reason=row["marks_reason"],
                marks_source=row.get("marks_source", "printed"),
                recovered_label=row["recovered_label"],
                module=row.get("module"),
                co=row.get("co"),
                bl=row.get("bl"),
                page=row["page"],
            )
        )

    for figure in result.figures:
        db.add(
            Figure(
                paper_id=paper.id,
                page=figure.page,
                question_no=figure.question_no,
                kind=figure.kind,
                detector=figure.detector,
                caption=figure.caption,
                x0=figure.x0,
                top=figure.top,
                x1=figure.x1,
                bottom=figure.bottom,
                area_ratio=figure.area_ratio,
                image_path=figure.image_path,
                width_px=figure.width_px,
                height_px=figure.height_px,
                note=figure.note,
            )
        )

    json_path = JSON_DIR / f"paper_{paper.id}.json"
    try:
        json_path.write_text(
            json.dumps(
                {
                    "course_code": course.code,
                    "header": header.to_detail(),
                    "extraction": result.diagnostics_source,
                    "confidence": score.to_dict(),
                    "questions": pipeline.extract_rows(result.questions),
                    "figures": [f.to_dict() for f in result.figures],
                },
                indent=2,
            )
        )
        paper.json_path = str(json_path)
    except OSError as exc:  # noqa: BLE001 - a sidecar failure must not lose the paper
        logger.warning("Could not write JSON sidecar for paper %s: %s", paper.id, exc)

    db.commit()
    db.refresh(paper)
    return paper
