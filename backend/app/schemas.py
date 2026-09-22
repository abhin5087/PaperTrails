from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_no: str
    text: str
    marks: int | None
    module: str | None
    co: str | None
    bl: str | None
    page: int | None


class PaperSummary(BaseModel):
    id: int
    course_code: str
    course_name: str | None
    semester: str | None
    exam_type: str | None
    max_marks: int | None
    pdf_type: str
    question_count: int
    confidence: int
    confidence_level: Literal["high", "medium", "low"]
    original_filename: str
    created_at: datetime


class PaperDetail(PaperSummary):
    academic_year: str | None
    slot: str | None
    duration: str | None
    exam_date: str | None
    marks_extracted: int
    extraction_method: str
    confidence_breakdown: dict[str, Any]
    notes: list[str]
    questions: list[QuestionOut]


class Stats(BaseModel):
    total_papers: int
    total_questions: int
    total_courses: int
    avg_confidence: int
