from .models import Figure, Paper
from .schemas import DiagnosticOut, FigureOut, PaperDetail, PaperSummary, QuestionOut
from .services.confidence import level_for


def to_figure(f: Figure) -> FigureOut:
    return FigureOut(
        id=f.id,
        page=f.page,
        question_no=f.question_no,
        kind=f.kind,
        caption=f.caption,
        width_px=f.width_px,
        height_px=f.height_px,
        note=f.note,
        image_url=f"/api/figures/{f.id}/image" if f.image_path else None,
    )


def to_summary(p: Paper) -> PaperSummary:
    # Only top-level questions are counted; subquestions live inside them.
    top_level = [q for q in p.questions if not q.parent_no]

    return PaperSummary(
        id=p.id,
        course_code=p.course.code,
        course_name=p.course.name or p.course_name_raw,
        semester=p.semester,
        exam_type=p.exam_type,
        max_marks=p.max_marks,
        pdf_type=p.pdf_type,
        question_count=len(top_level),
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
        exam_time=p.exam_time,
        marks_extracted=p.marks_extracted,
        extraction_method=p.extraction_method,
        page_count=p.page_count or 0,
        ocr_engine=p.ocr_engine,
        ocr_config=p.ocr_config,
        ocr_confidence=p.ocr_confidence,
        confidence_breakdown=p.confidence_breakdown or {},
        notes=p.notes or [],
        diagnostics=[DiagnosticOut(**d) for d in (p.diagnostics or [])],
        header_detail=p.header_detail or {},
        extraction_detail=p.extraction_detail or {},
        questions=[QuestionOut.model_validate(q) for q in p.questions],
        figures=[to_figure(f) for f in p.figures],
    )
