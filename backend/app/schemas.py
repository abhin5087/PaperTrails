from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warning", "unresolved", "info"]


class DiagnosticOut(BaseModel):
    code: str
    severity: Severity
    message: str
    field: str | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_no: str
    parent_no: str | None = None
    text: str

    #: Resolved total.  ``None`` means it could not be read with confidence.
    marks: int | None
    #: Exactly what the paper printed, kept even when unresolved.
    marks_raw: str | None = None
    marks_parts: list[int] = []
    marks_resolved: bool = False
    marks_reason: str | None = None
    #: 'printed' or 'distribution' - where the value came from.
    marks_source: str = "printed"

    recovered_label: bool = False
    module: str | None
    co: str | None
    bl: str | None
    page: int | None


class FigureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page: int
    question_no: str | None
    kind: str
    caption: str | None
    width_px: int | None
    height_px: int | None
    note: str | None
    #: Detectors that contributed this figure's geometry.
    sources: list[str] = []
    #: Edges where the figure's content reaches its boundary.
    clipped_edges: list[str] = []
    #: Endpoint serving the cropped image, when one was produced.
    image_url: str | None = None


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
    exam_time: str | None = None
    marks_extracted: int
    extraction_method: str
    page_count: int = 0

    ocr_engine: str | None = None
    ocr_config: str | None = None
    ocr_confidence: float | None = None

    confidence_breakdown: dict[str, Any]
    notes: list[str]
    diagnostics: list[DiagnosticOut] = []
    header_detail: dict[str, Any] = {}
    extraction_detail: dict[str, Any] = {}

    questions: list[QuestionOut]
    figures: list[FigureOut] = []


class Stats(BaseModel):
    total_papers: int
    total_questions: int
    total_courses: int
    avg_confidence: int
