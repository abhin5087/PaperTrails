from .models import Paper
from .schemas import PaperDetail, PaperSummary, QuestionOut
from .services.confidence import level_for


def to_summary(p: Paper) -> PaperSummary:
    return PaperSummary(
        id=p.id,
        course_code=p.course.code,
        course_name=p.course.name,
        semester=p.semester,
        exam_type=p.exam_type,
        max_marks=p.max_marks,
        pdf_type=p.pdf_type,
        question_count=len(p.questions),
        confidence=p.confidence,
        confidence_level=level_for(p.confidence),
        original_filename=p.original_filename,
        created_at=p.created_at,
    )


def to_detail(p: Paper) -> PaperDetail:
    return PaperDetail(
        **to_summary(p).model_dump(),
        academic_year=p.academic_year,
        slot=p.slot,
        duration=p.duration,
        exam_date=p.exam_date,
        marks_extracted=p.marks_extracted,
        extraction_method=p.extraction_method,
        confidence_breakdown=p.confidence_breakdown or {},
        notes=p.notes or [],
        questions=[QuestionOut.model_validate(q) for q in p.questions],
    )
