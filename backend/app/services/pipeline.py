"""Extraction pipeline.

The pipeline builds several independent *candidates* - the PDF's own text
layer, plus one per OCR configuration - and chooses between them.  The key
property is that **a candidate carries its own header**, parsed from the very
text that candidate produced.  Reading the header from
``pdf.pages[0].extract_text()`` regardless of which level won is what made a
scanned paper come back with an empty header while OCR had read it perfectly;
here that cannot happen, because there is no shared header to read.

Selection is on structural quality - contiguous question numbering, header
completeness, recovered marks, coherent text length - with engine confidence
as a supporting term.  Raw character confidence alone would happily pick a
fragmented page over a well-structured one.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from . import figure_detector, ocr as ocr_service, ocr_correction
from .confidence import ExtractionSummary
from .marks import from_distribution
from .header import Header, parse_header
from .questions import Classified, Line, Question, extract_questions

logger = logging.getLogger(__name__)

#: Below this many characters on page one, a text layer is not worth using.
MIN_NATIVE_CHARS = 40


@dataclass
class Candidate:
    """One complete attempt at reading the document."""

    name: str
    source: str  # native_text | ocr
    lines: list[Line] = field(default_factory=list)
    header: Header = field(default_factory=Header)
    questions: list[Question] = field(default_factory=list)
    classified: list[Classified] = field(default_factory=list)
    first_page_text: str = ""
    ocr_config: str | None = None
    ocr_confidence: float | None = None
    available: bool = True
    error: str | None = None
    corrections: int = 0
    score: float = 0.0
    score_detail: dict[str, float] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.available and bool(self.questions)


# --------------------------------------------------------------------------
# Candidate construction
# --------------------------------------------------------------------------


def _native_lines(pdf) -> list[Line]:
    lines: list[Line] = []
    for page_no, page in enumerate(pdf.pages, start=1):
        try:
            extracted = page.extract_text_lines()
        except Exception as exc:  # noqa: BLE001 - malformed page
            logger.warning("Native line extraction failed on page %s: %s", page_no, exc)
            continue
        for index, item in enumerate(extracted):
            text = (item.get("text") or "").strip()
            if not text:
                continue
            lines.append(
                Line(
                    text=text,
                    page=page_no,
                    index=index,
                    x0=item.get("x0"),
                    top=item.get("top"),
                    bottom=item.get("bottom"),
                    x1=item.get("x1"),
                )
            )
    return lines


def _page_one_text(lines: list[Line]) -> str:
    return "\n".join(ln.text for ln in lines if ln.page == 1)


def build_native_candidate(pdf, figure_spans=None, pdf_type: str = "vector") -> Candidate:
    """The PDF's own text layer.

    When that layer was itself produced by OCR - a scan shipped with a text
    layer, which is what ``ocr_text`` means - it carries OCR damage and gets
    the same conservative correction pass as text we OCR ourselves.  A true
    vector PDF's text is exact and is never rewritten.
    """
    lines = _native_lines(pdf)
    candidate = Candidate(name="native", source="native_text", lines=lines)

    if not lines:
        candidate.available = False
        candidate.error = "no text layer"
        return candidate

    if pdf_type == "ocr_text":
        corrected: list[Line] = []
        count = 0
        for line in lines:
            fixed = ocr_correction.correct_text(line.text)
            count += len(fixed.corrections)
            corrected.append(
                Line(text=fixed.corrected_text, page=line.page, index=line.index,
                     x0=line.x0, top=line.top, bottom=line.bottom, x1=line.x1)
            )
        lines = corrected
        candidate.lines = lines
        candidate.corrections = count

    candidate.first_page_text = _page_one_text(lines)
    if len(candidate.first_page_text) < MIN_NATIVE_CHARS:
        candidate.available = False
        candidate.error = "text layer too sparse to use"
        return candidate

    # Header comes from this candidate's own text, not from a shared source.
    candidate.header = parse_header(candidate.first_page_text)
    candidate.questions, candidate.classified = extract_questions(
        lines, figure_spans=figure_spans
    )
    return candidate


def build_ocr_candidates(pdf_path: str, figure_spans=None,
                         page_images=None) -> list[Candidate]:
    """One candidate per OCR configuration, each with its own header."""
    candidates: list[Candidate] = []

    if page_images is not None:
        results = [
            ocr_service.run_ocr(pdf_path, config, images=page_images)
            for config in ocr_service.OCR_CONFIGS
        ]
    else:
        results = ocr_service.run_all_configs(pdf_path)

    for result in results:
        candidate = Candidate(
            name=f"ocr:{result.config.name}",
            source="ocr",
            ocr_config=result.config.name,
            available=result.available,
            error=result.error,
        )

        if not result.available:
            candidates.append(candidate)
            continue

        corrected_lines: list[Line] = []
        correction_count = 0
        for line in result.lines:
            fixed = ocr_correction.correct_text(line.text)
            correction_count += len(fixed.corrections)
            corrected_lines.append(
                Line(
                    text=fixed.corrected_text,
                    page=line.page,
                    index=line.index,
                    x0=line.x0,
                    top=line.top,
                    bottom=line.bottom,
                    x1=line.x1,
                )
            )

        candidate.lines = corrected_lines
        candidate.corrections = correction_count
        candidate.ocr_confidence = result.mean_confidence
        candidate.first_page_text = _page_one_text(corrected_lines)

        if not candidate.first_page_text.strip():
            candidate.error = "OCR returned no text"
            candidates.append(candidate)
            continue

        candidate.header = parse_header(candidate.first_page_text)
        candidate.questions, candidate.classified = extract_questions(
            corrected_lines, figure_spans=figure_spans
        )
        candidates.append(candidate)

    return candidates


# --------------------------------------------------------------------------
# Candidate scoring
# --------------------------------------------------------------------------

#: Question text beyond this many words adds nothing - it stops a candidate
#: that swallowed a whole page of diagram noise from outscoring a clean one.
TEXT_LENGTH_CAP = 30


def score_candidate(candidate: Candidate) -> tuple[float, dict[str, float]]:
    """Rate a candidate on structure, not on character confidence."""
    detail: dict[str, float] = {}

    if not candidate.available:
        return 0.0, {"available": 0.0}

    questions = candidate.questions
    if not questions:
        return 0.0, {"questions": 0.0}

    # --- how many questions, and do they form a run? --------------------
    numbers: list[int] = []
    for question in questions:
        try:
            numbers.append(int(question.number))
        except (TypeError, ValueError):
            pass

    detail["question_count"] = min(1.0, len(questions) / 10.0) * 20.0

    if numbers:
        span = max(numbers) - min(numbers) + 1
        contiguity = len(set(numbers)) / span if span else 0.0
        starts_at_one = 1.0 if min(numbers) == 1 else 0.6
    else:
        contiguity, starts_at_one = 0.0, 0.5
    detail["sequence"] = contiguity * starts_at_one * 22.0

    # --- header completeness -------------------------------------------
    detail["header"] = candidate.header.completeness * 18.0

    # --- meaningful text, capped so noise cannot win --------------------
    word_counts = [len(q.text.split()) for q in questions]
    median_words = statistics.median(word_counts) if word_counts else 0
    detail["text"] = min(1.0, median_words / TEXT_LENGTH_CAP) * 14.0

    # Duplicated question text means the layout was read twice.
    texts = [q.text.strip().lower()[:80] for q in questions if q.text.strip()]
    duplicates = len(texts) - len(set(texts))
    detail["duplication_penalty"] = -min(10.0, duplicates * 3.0)

    # --- marks recovery -------------------------------------------------
    resolved = sum(1 for q in questions if q.marks.resolved)
    detail["marks"] = (resolved / len(questions)) * 14.0

    # --- fragmentation ---------------------------------------------------
    short_lines = sum(1 for ln in candidate.lines if len(ln.text.strip()) < 4)
    fragmentation = short_lines / len(candidate.lines) if candidate.lines else 0.0
    detail["fragmentation_penalty"] = -fragmentation * 10.0

    # --- questions that had to be reconstructed --------------------------
    recovered = sum(1 for q in questions if q.recovered_label)
    detail["recovery_penalty"] = -min(6.0, recovered * 2.0)

    # --- engine confidence: supporting evidence only ---------------------
    if candidate.ocr_confidence is not None:
        detail["ocr_confidence"] = min(1.0, candidate.ocr_confidence / 95.0) * 8.0
    else:
        detail["ocr_confidence"] = 8.0

    return sum(detail.values()), detail


def select_candidate(candidates: list[Candidate]) -> Candidate | None:
    """Pick the best candidate, preferring a native text layer on a tie."""
    scored = []
    for candidate in candidates:
        candidate.score, candidate.score_detail = score_candidate(candidate)
        scored.append(candidate)

    usable = [c for c in scored if c.usable]
    if not usable:
        # Nothing produced questions; fall back to whatever read any text,
        # so the header is at least available.
        with_text = [c for c in scored if c.available and c.first_page_text.strip()]
        if with_text:
            return max(with_text, key=lambda c: (len(c.header), c.score))
        return None

    best = max(usable, key=lambda c: c.score)

    # A native layer that scores within a point of the best OCR result is
    # preferred: it is exact where OCR is a reading.
    native = next((c for c in usable if c.source == "native_text"), None)
    if native is not None and best.source == "ocr" and native.score >= best.score - 1.0:
        return native

    return best


# --------------------------------------------------------------------------
# Full extraction
# --------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Everything the persistence layer needs."""

    candidate: Candidate
    candidates: list[Candidate]
    header: Header
    questions: list[Question]
    figures: list[figure_detector.Figure]
    summary: ExtractionSummary
    diagnostics_source: dict = field(default_factory=dict)
    page_count: int = 0

    @property
    def method(self) -> str:
        return self.candidate.name if self.candidate else "none"


def apply_distribution_marks(header: Header, questions: list[Question]) -> bool:
    """Apply a paper-wide marks banner when nothing else states the marks.

    Some papers print the marks once - ``(10 X 10 = 100 Marks)`` - instead of
    beside each question.  That banner is the paper stating the value, so it
    is used, but only when it cannot be wrong:

    * the banner is self-consistent (checked when the header was parsed),
    * the paper has exactly as many top-level questions as the banner counts,
    * and not one question carries printed marks of its own.

    If any question has its own marks, the banner is ignored entirely - the
    printed values are the better evidence and mixing the two would invent
    numbers for whatever was missing.
    """
    distribution = header.get("marks_distribution")
    if not distribution or not questions:
        return False

    try:
        count_text, each_text = distribution.lower().split("x")
        count, each = int(count_text), int(each_text)
    except (ValueError, AttributeError):
        return False

    if count != len(questions):
        return False

    if any(q.marks.raw is not None for q in questions):
        return False

    raw = header.fields["marks_distribution"].raw
    for question in questions:
        question.marks = from_distribution(each, raw)

    return True


def detect_pdf_type(pdf) -> str:
    """vector | ocr_text | scanned, from page-one geometry."""
    page = pdf.pages[0]
    chars = len(page.chars)
    ruled = len(page.lines) + len(page.rects)

    if chars == 0:
        return "scanned"
    if ruled > 10:
        return "vector"
    return "ocr_text"


def extract(pdf_path: str, *, figures_dir: Path | None = None,
            figure_trace: "figure_detector.FigureTrace | None" = None,
            ) -> ExtractionResult:
    """Run the whole pipeline over one PDF."""
    path = str(pdf_path)

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        pdf_type = detect_pdf_type(pdf)
        page_sizes = {
            i + 1: (float(p.width), float(p.height)) for i, p in enumerate(pdf.pages)
        }

        native = build_native_candidate(pdf, pdf_type=pdf_type)
        candidates: list[Candidate] = [native]

        # OCR is attempted whenever the text layer is unusable, and also when
        # it is thin enough that OCR might legitimately do better.
        needs_ocr = (not native.usable) or pdf_type == "scanned"
        page_images = None
        ocr_attempted = False
        ocr_available = ocr_service.ocr_available()

        if needs_ocr:
            ocr_attempted = True
            if ocr_available:
                try:
                    page_images = ocr_service.render_pages(path, ocr_service.DEFAULT_DPI)
                except ocr_service.OcrUnavailable as exc:
                    logger.warning("Rasterisation failed: %s", exc)
            candidates.extend(build_ocr_candidates(path, page_images=page_images))
        elif pdf_type == "ocr_text":
            # The text layer is good enough to use, but the page is still a
            # picture: any diagram on it exists only in that picture, so the
            # page is rendered for figure detection even though OCR is not
            # needed for the text.
            try:
                page_images = ocr_service.render_pages(
                    path, figure_detector.CROP_DPI
                )
            except ocr_service.OcrUnavailable as exc:
                logger.warning("Rasterisation for figures failed: %s", exc)

        chosen = select_candidate(candidates)

        # Figures are detected against the chosen candidate's geometry so the
        # association uses the same coordinates as the question boundaries.
        lines = chosen.lines if chosen else []
        figures = figure_detector.detect_figures(
            pdf,
            trace=figure_trace,
            page_images=page_images,
            lines=lines,
            use_ink_detector=(
                pdf_type in ("scanned", "ocr_text") and page_images is not None
            ),
        )

    # Re-run boundary detection with the figure regions known, so that
    # anything sitting inside a diagram can no longer open a question.
    #
    # A figure region is only allowed to *refine* the result.  An
    # over-large or misplaced region would otherwise mask real question
    # text, so the re-run is discarded unless it keeps every question the
    # first pass found.
    if chosen is not None and figures:
        spans = [(f.page, f.top, f.bottom, f.x0, f.x1) for f in figures]
        refined, refined_classified = extract_questions(
            chosen.lines, figure_spans=spans
        )
        if len(refined) >= len(chosen.questions):
            chosen.questions, chosen.classified = refined, refined_classified
        else:
            logger.warning(
                "Figure regions would have dropped %s of %s questions on %s; "
                "keeping the unrefined extraction.",
                len(chosen.questions) - len(refined), len(chosen.questions), path,
            )

    if chosen is not None:
        # Masthead and header-table regions belong to the page, not to a
        # question, and are removed before anything is attributed or cropped.
        figures = figure_detector.drop_page_furniture(
            figures, chosen.questions, trace=figure_trace
        )
        figure_detector.associate_with_questions(figures, chosen.questions)

        # The trace's final list is written inside detect_figures, before
        # furniture is dropped and questions are attributed; refresh it so the
        # debug artefact matches what the paper actually ends up with.
        if figure_trace is not None:
            figure_trace.final = [f.to_dict() for f in figures]
        apply_distribution_marks(chosen.header, chosen.questions)

    crop_attempted = figures_dir is not None and bool(figures)
    if crop_attempted:
        figure_detector.crop_figures(
            path, figures, figures_dir, page_images=page_images,
            page_sizes=page_sizes,
        )

    header = chosen.header if chosen else Header()
    questions = chosen.questions if chosen else []

    summary = ExtractionSummary(
        pdf_type=pdf_type,
        method=chosen.name if chosen else "none",
        source=chosen.source if (chosen and chosen.usable) else (
            chosen.source if chosen else "none"
        ),
        ocr_attempted=ocr_attempted,
        ocr_available=ocr_available,
        ocr_used=bool(chosen and chosen.source == "ocr"),
        ocr_config=chosen.ocr_config if chosen else None,
        ocr_confidence=chosen.ocr_confidence if chosen else None,
        ocr_error=next(
            (c.error for c in candidates if c.source == "ocr" and c.error), None
        ),
        candidates_considered=sum(1 for c in candidates if c.available),
        corrections_applied=chosen.corrections if chosen else 0,
        figures_detected=len(figures),
        figures_cropped=sum(1 for f in figures if f.image_path),
        figures_crop_attempted=crop_attempted,
        recovered_labels=sum(1 for q in questions if q.recovered_label),
        page_count=page_count,
    )

    if chosen is None or not questions:
        summary.source = "none"

    return ExtractionResult(
        candidate=chosen,
        candidates=candidates,
        header=header,
        questions=questions,
        figures=figures,
        summary=summary,
        diagnostics_source={
            "pdf_type": pdf_type,
            "page_count": page_count,
            "candidates": [
                {
                    "name": c.name,
                    "available": c.available,
                    "error": c.error,
                    "questions": len(c.questions),
                    "header_fields": len(c.header),
                    "ocr_confidence": c.ocr_confidence,
                    "score": round(c.score, 2),
                    "score_detail": {k: round(v, 2) for k, v in c.score_detail.items()},
                    "selected": c is chosen,
                }
                for c in candidates
            ],
        },
        page_count=page_count,
    )


def extract_rows(questions: list[Question]) -> list[dict]:
    """Flatten questions (and their subquestions) into persistable rows."""
    from .questions import flatten

    return flatten(questions)
