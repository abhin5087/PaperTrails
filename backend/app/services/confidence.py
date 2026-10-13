"""Extraction confidence and diagnostics.

Two rules shape this module.

*Confidence measures the extraction, not the scanner.*  A page can OCR at 95%
character confidence and still yield a useless question list, so the score is
built from structural evidence - how complete the header is, whether the
question numbering is contiguous, how much of the marks could actually be
resolved - with engine confidence as a supporting term only.

*Diagnostics describe what happened.*  Every message is derived from the real
extraction result.  OCR is reported as run, skipped, failed or unavailable
according to what the pipeline actually did, and an extraction with
unresolved fields is never presented as fully successful.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"
UNRESOLVED = "unresolved"
INFO = "info"

SEVERITY_ORDER = {ERROR: 0, WARNING: 1, UNRESOLVED: 2, INFO: 3}


@dataclass(frozen=True)
class Diagnostic:
    """One typed, actionable message about the extraction."""

    code: str
    severity: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field": self.field,
        }


@dataclass
class ExtractionSummary:
    """Everything the scorer needs, gathered by the pipeline."""

    pdf_type: str
    method: str
    source: str  # native_text | ocr | none
    ocr_attempted: bool = False
    ocr_available: bool = True
    ocr_used: bool = False
    ocr_config: str | None = None
    ocr_confidence: float | None = None
    ocr_error: str | None = None
    candidates_considered: int = 1
    corrections_applied: int = 0
    figures_detected: int = 0
    figures_cropped: int = 0
    figures_crop_attempted: bool = False
    recovered_labels: int = 0
    page_count: int = 1


def level_for(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


# --------------------------------------------------------------------------
# Component scores
# --------------------------------------------------------------------------

HEADER_FIELDS = ("course_code", "course_name", "exam_type", "semester", "max_marks")
HEADER_WEIGHT = 22
QUESTION_WEIGHT = 30
MARKS_WEIGHT = 25
TEXT_WEIGHT = 13
SOURCE_WEIGHT = 10


def _header_component(header, diagnostics: list[Diagnostic]) -> int:
    present = [f for f in HEADER_FIELDS if header.has(f)]
    missing = [f for f in HEADER_FIELDS if not header.has(f)]

    for name in missing:
        diagnostics.append(
            Diagnostic(
                code="header_field_missing",
                severity=UNRESOLVED,
                message=f"Header field '{name.replace('_', ' ')}' was not found.",
                field=name,
            )
        )

    for name, parsed in header.fields.items():
        if not parsed.confident:
            diagnostics.append(
                Diagnostic(
                    code="header_field_uncertain",
                    severity=WARNING,
                    message=(
                        f"Header field '{name.replace('_', ' ')}' read as "
                        f"'{parsed.value}' from '{parsed.raw}' after OCR repair; "
                        "verify against the paper."
                    ),
                    field=name,
                )
            )

    for note in header.unparsed:
        diagnostics.append(
            Diagnostic(code="header_unparsed", severity=WARNING, message=note)
        )

    return round(HEADER_WEIGHT * len(present) / len(HEADER_FIELDS))


def _sequence_gaps(questions) -> list[int]:
    numbers = []
    for question in questions:
        try:
            numbers.append(int(question.number))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return []
    expected = set(range(min(numbers), max(numbers) + 1))
    return sorted(expected - set(numbers))


def _question_component(questions, diagnostics: list[Diagnostic]) -> int:
    if not questions:
        diagnostics.append(
            Diagnostic(
                code="no_questions",
                severity=ERROR,
                message="No questions could be identified in this paper.",
            )
        )
        return 0

    score = QUESTION_WEIGHT

    # Contiguous numbering is the strongest evidence that boundaries are right.
    gaps = _sequence_gaps(questions)
    if gaps:
        score -= min(12, 3 * len(gaps))
        diagnostics.append(
            Diagnostic(
                code="question_sequence_gap",
                severity=WARNING,
                message=(
                    "Question numbering skips "
                    f"{', '.join(str(g) for g in gaps)}; a label may have been "
                    "missed or misread."
                ),
            )
        )

    empty = [q for q in questions if len(q.text.split()) < 4]
    if empty:
        score -= min(10, 2 * len(empty))
        diagnostics.append(
            Diagnostic(
                code="question_text_thin",
                severity=WARNING,
                message=(
                    f"{len(empty)} question(s) have almost no text: "
                    f"{', '.join(q.label for q in empty[:5])}."
                ),
            )
        )

    recovered = [q for q in questions if q.recovered_label]
    if recovered:
        score -= min(6, 2 * len(recovered))
        diagnostics.append(
            Diagnostic(
                code="label_recovered",
                severity=WARNING,
                message=(
                    "Question label(s) reconstructed from damaged text: "
                    f"{', '.join(q.label for q in recovered)}. Check the numbering."
                ),
            )
        )

    return max(0, score)


def _marks_component(questions, max_marks, diagnostics: list[Diagnostic]) -> tuple[int, int]:
    """Returns ``(component_score, resolved_total)``."""
    tops = list(questions)
    if not tops:
        return 0, 0

    resolved = [q for q in tops if q.marks.resolved and q.marks.total is not None]
    unresolved = [q for q in tops if q.marks.raw is not None and not q.marks.resolved]
    absent = [q for q in tops if q.marks.raw is None]

    # Parent totals only - subquestion marks are already inside them.
    total = sum(q.marks.total for q in resolved)

    for question in unresolved:
        diagnostics.append(
            Diagnostic(
                code="marks_unresolved",
                severity=UNRESOLVED,
                message=(
                    f"Question {question.label}: marks kept as raw text "
                    f"'{question.marks.raw}' - {question.marks.reason}."
                ),
                field=f"question:{question.label}",
            )
        )

    if absent:
        diagnostics.append(
            Diagnostic(
                code="marks_missing",
                severity=UNRESOLVED,
                message=(
                    f"No marks found for question(s) "
                    f"{', '.join(q.label for q in absent[:8])}."
                ),
            )
        )

    coverage = len(resolved) / len(tops)
    score = round(MARKS_WEIGHT * 0.6 * coverage)

    if max_marks is None:
        diagnostics.append(
            Diagnostic(
                code="max_marks_unknown",
                severity=UNRESOLVED,
                message="Paper total not found in the header, so marks could not "
                        "be cross-checked.",
                field="max_marks",
            )
        )
        return score, total

    remaining = MARKS_WEIGHT - round(MARKS_WEIGHT * 0.6)
    if total == max_marks and not unresolved and not absent:
        score += remaining
    elif total == max_marks:
        score += round(remaining * 0.7)
        diagnostics.append(
            Diagnostic(
                code="marks_total_matches_with_gaps",
                severity=WARNING,
                message=(
                    f"Resolved marks sum to {total}, matching the stated "
                    f"{max_marks}, but some marks remain unresolved."
                ),
            )
        )
    else:
        shortfall = max_marks - total
        severity = WARNING if shortfall > 0 else ERROR
        score += max(0, round(remaining * (1 - min(1.0, abs(shortfall) / max_marks))))
        diagnostics.append(
            Diagnostic(
                code="marks_total_mismatch",
                severity=severity,
                message=(
                    f"Resolved marks sum to {total} but the paper states "
                    f"{max_marks}"
                    + (
                        f" ({shortfall} unaccounted for)."
                        if shortfall > 0
                        else f" ({-shortfall} more than stated - a mark may be "
                             "double counted)."
                    )
                ),
            )
        )

    return score, total


def _text_component(questions, summary: ExtractionSummary,
                    diagnostics: list[Diagnostic]) -> int:
    if not questions:
        return 0

    lengths = [len(q.text.split()) for q in questions]
    median = statistics.median(lengths) if lengths else 0

    # A median around 12 words or more reads as coherent question text.
    coherence = min(1.0, median / 12.0)
    score = round(TEXT_WEIGHT * 0.65 * coherence)

    if median < 6:
        diagnostics.append(
            Diagnostic(
                code="text_fragmented",
                severity=WARNING,
                message=(
                    f"Question text looks fragmented (median {median:.0f} words); "
                    "the layout may not have been read correctly."
                ),
            )
        )

    engine = summary.ocr_confidence
    if engine is None:
        score += round(TEXT_WEIGHT * 0.35)
    else:
        score += round(TEXT_WEIGHT * 0.35 * min(1.0, engine / 90.0))
        if engine < 70:
            diagnostics.append(
                Diagnostic(
                    code="ocr_low_confidence",
                    severity=WARNING,
                    message=(
                        f"OCR reported {engine:.0f}% mean character confidence; "
                        "the scan quality is marginal."
                    ),
                )
            )

    return min(TEXT_WEIGHT, score)


def _source_component(summary: ExtractionSummary,
                      diagnostics: list[Diagnostic]) -> int:
    """Score and describe the text source.  This is where OCR gets reported
    accurately: what ran, what was chosen, and what failed."""
    if summary.source == "native_text":
        diagnostics.append(
            Diagnostic(
                code="native_text_used",
                severity=INFO,
                message="Extracted from the PDF's own text layer.",
            )
        )
        if summary.ocr_attempted and not summary.ocr_used:
            diagnostics.append(
                Diagnostic(
                    code="ocr_not_selected",
                    severity=INFO,
                    message=(
                        "OCR also ran but the native text layer produced the "
                        "better structure, so OCR output was not used."
                    ),
                )
            )
        return SOURCE_WEIGHT

    if summary.source == "ocr":
        diagnostics.append(
            Diagnostic(
                code="ocr_used",
                severity=INFO,
                message=(
                    "No usable text layer, so the page images were read with OCR"
                    + (f" (configuration '{summary.ocr_config}'" if summary.ocr_config
                       else "")
                    + (f", {summary.ocr_confidence:.0f}% mean confidence)."
                       if summary.ocr_confidence is not None else ")."
                       if summary.ocr_config else ".")
                ),
            )
        )
        if summary.candidates_considered > 1:
            diagnostics.append(
                Diagnostic(
                    code="ocr_candidates",
                    severity=INFO,
                    message=(
                        f"{summary.candidates_considered} extraction candidates "
                        "were compared before choosing this one."
                    ),
                )
            )
        if summary.corrections_applied:
            diagnostics.append(
                Diagnostic(
                    code="ocr_corrections",
                    severity=INFO,
                    message=(
                        f"{summary.corrections_applied} conservative OCR "
                        "correction(s) applied; the original text is retained."
                    ),
                )
            )
        return round(SOURCE_WEIGHT * 0.6)

    # Nothing worked.
    if not summary.ocr_available:
        diagnostics.append(
            Diagnostic(
                code="ocr_unavailable",
                severity=ERROR,
                message=(
                    "This is a scanned PDF with no text layer and no OCR engine is "
                    "installed, so no text could be read. Install Tesseract to "
                    "process scanned papers."
                    + (f" ({summary.ocr_error})" if summary.ocr_error else "")
                ),
            )
        )
    elif summary.ocr_attempted:
        diagnostics.append(
            Diagnostic(
                code="ocr_failed",
                severity=ERROR,
                message=(
                    "OCR ran on this scanned PDF but returned no usable text."
                    + (f" ({summary.ocr_error})" if summary.ocr_error else "")
                ),
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="no_text_source",
                severity=ERROR,
                message="No text could be extracted from this PDF.",
            )
        )
    return 0


def _figure_diagnostics(summary: ExtractionSummary,
                        diagnostics: list[Diagnostic]) -> None:
    if not summary.figures_detected:
        return

    diagnostics.append(
        Diagnostic(
            code="figures_detected",
            severity=INFO,
            message=(
                f"{summary.figures_detected} figure/diagram region(s) detected"
                + (f", {summary.figures_cropped} saved as images."
                   if summary.figures_crop_attempted else ".")
            ),
        )
    )
    if (
        summary.figures_crop_attempted
        and summary.figures_cropped < summary.figures_detected
    ):
        diagnostics.append(
            Diagnostic(
                code="figures_not_cropped",
                severity=WARNING,
                message=(
                    f"{summary.figures_detected - summary.figures_cropped} figure "
                    "region(s) could not be rendered to an image."
                ),
            )
        )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


@dataclass
class Score:
    total: int
    breakdown: dict[str, int]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    marks_extracted: int = 0

    @property
    def level(self) -> str:
        return level_for(self.total)

    @property
    def messages(self) -> list[str]:
        return [d.message for d in self.diagnostics]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "level": self.level,
            "breakdown": dict(self.breakdown),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def score(*, header, questions, max_marks: int | None,
          summary: ExtractionSummary) -> Score:
    """Score an extraction and explain it."""
    diagnostics: list[Diagnostic] = []
    breakdown: dict[str, int] = {}

    breakdown["header"] = _header_component(header, diagnostics)
    breakdown["questions"] = _question_component(questions, diagnostics)
    marks_score, marks_total = _marks_component(questions, max_marks, diagnostics)
    breakdown["marks"] = marks_score
    breakdown["text_quality"] = _text_component(questions, summary, diagnostics)
    breakdown["source"] = _source_component(summary, diagnostics)
    _figure_diagnostics(summary, diagnostics)

    total = max(0, min(100, sum(breakdown.values())))

    # An extraction holding unresolved material must not read as complete.
    unresolved = [d for d in diagnostics if d.severity in (ERROR, UNRESOLVED)]
    if unresolved and total > 90:
        total = 90

    diagnostics.sort(key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.code))

    return Score(total=total, breakdown=breakdown, diagnostics=diagnostics,
                 marks_extracted=marks_total)
