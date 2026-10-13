"""Confidence and diagnostics must describe what actually happened."""

import pytest

from app.services.confidence import ERROR, INFO, UNRESOLVED, WARNING, ExtractionSummary, score
from app.services.header import parse_header
from app.services.questions import Line, extract_questions

FULL_HEADER = """Course Code: BHUM103L
Course Name: Microeconomics
Continuous Assessment Test-1 - Winter Semester 2024-2025
Maximum Marks: 50"""


def questions_from(rows):
    built = [
        Line(text=t, page=1, index=i, x0=0.0, top=float(i * 14), bottom=float(i * 14 + 10))
        for i, t in enumerate(rows)
    ]
    return extract_questions(built)[0]


CLEAN = questions_from(
    [f"{n}. Explain in full the concept under discussion in part {n} here. 10"
     for n in range(1, 6)]
)


def summary(**kwargs):
    base = dict(pdf_type="scanned", method="ocr:psm6-block", source="ocr",
                ocr_attempted=True, ocr_available=True, ocr_used=True,
                ocr_config="psm6-block", ocr_confidence=95.0)
    base.update(kwargs)
    return ExtractionSummary(**base)


def codes(result):
    return {d.code for d in result.diagnostics}


class TestOcrDiagnosticHonesty:
    def test_ocr_that_ran_is_never_reported_as_unimplemented(self):
        """The old hardcoded 'OCR not yet implemented' note must be gone."""
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        text = " ".join(d.message for d in result.diagnostics).lower()
        assert "not yet implemented" not in text
        assert "not implemented" not in text

    def test_successful_ocr_is_reported_with_its_configuration(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        assert "ocr_used" in codes(result)
        message = next(d.message for d in result.diagnostics if d.code == "ocr_used")
        assert "psm6-block" in message
        assert "95" in message

    def test_native_text_is_reported_as_native(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50,
                       summary=summary(source="native_text", ocr_used=False,
                                       ocr_attempted=False, ocr_config=None,
                                       ocr_confidence=None, pdf_type="vector"))
        assert "native_text_used" in codes(result)
        assert "ocr_used" not in codes(result)

    def test_ocr_that_ran_but_lost_is_reported_as_not_selected(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50,
                       summary=summary(source="native_text", ocr_used=False,
                                       ocr_attempted=True, ocr_config=None,
                                       ocr_confidence=None))
        assert "ocr_not_selected" in codes(result)

    def test_missing_engine_is_reported_as_unavailable_not_as_failure(self):
        result = score(header=parse_header(FULL_HEADER), questions=[], max_marks=50,
                       summary=summary(source="none", ocr_used=False,
                                       ocr_available=False,
                                       ocr_error="Tesseract binary not found on PATH"))
        assert "ocr_unavailable" in codes(result)
        assert "ocr_failed" not in codes(result)
        message = next(d.message for d in result.diagnostics if d.code == "ocr_unavailable")
        assert "Install Tesseract" in message

    def test_engine_present_but_empty_output_is_reported_as_failure(self):
        result = score(header=parse_header(FULL_HEADER), questions=[], max_marks=50,
                       summary=summary(source="none", ocr_used=False,
                                       ocr_available=True,
                                       ocr_error="OCR returned no text"))
        assert "ocr_failed" in codes(result)
        assert "ocr_unavailable" not in codes(result)

    def test_low_engine_confidence_is_flagged(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary(ocr_confidence=55.0))
        assert "ocr_low_confidence" in codes(result)


class TestMarksDiagnostics:
    def test_matching_total_produces_no_mismatch(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        assert "marks_total_mismatch" not in codes(result)
        assert result.marks_extracted == 50

    def test_shortfall_is_explained_not_papered_over(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=70, summary=summary())
        assert "marks_total_mismatch" in codes(result)
        message = next(d.message for d in result.diagnostics
                       if d.code == "marks_total_mismatch")
        assert "20 unaccounted for" in message

    def test_excess_marks_is_an_error(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=30, summary=summary())
        diagnostic = next(d for d in result.diagnostics
                          if d.code == "marks_total_mismatch")
        assert diagnostic.severity == ERROR

    def test_unresolved_marks_are_surfaced_with_their_raw_text(self):
        questions = questions_from(["1. Derive the budget line for two goods. 743"])
        result = score(header=parse_header(FULL_HEADER), questions=questions,
                       max_marks=50, summary=summary())
        diagnostic = next(d for d in result.diagnostics if d.code == "marks_unresolved")
        assert "743" in diagnostic.message
        assert diagnostic.severity == UNRESOLVED

    def test_unknown_paper_total_is_unresolved_not_a_zero_score(self):
        result = score(header=parse_header("Course Code: BHUM103L"), questions=CLEAN,
                       max_marks=None, summary=summary())
        assert "max_marks_unknown" in codes(result)
        assert result.breakdown["marks"] > 0


class TestHeaderDiagnostics:
    def test_missing_fields_are_listed_individually(self):
        result = score(header=parse_header("Course Code: BHUM103L"), questions=CLEAN,
                       max_marks=None, summary=summary())
        missing = {d.field for d in result.diagnostics
                   if d.code == "header_field_missing"}
        assert {"exam_type", "semester", "max_marks"} <= missing

    def test_repaired_field_is_flagged_for_verification(self):
        header = parse_header("Course Code: BHUM1O3L\nMaximum Marks: 50")
        result = score(header=header, questions=CLEAN, max_marks=50, summary=summary())
        assert "header_field_uncertain" in codes(result)


class TestStructuralDiagnostics:
    def test_no_questions_is_an_error(self):
        result = score(header=parse_header(FULL_HEADER), questions=[], max_marks=50,
                       summary=summary())
        diagnostic = next(d for d in result.diagnostics if d.code == "no_questions")
        assert diagnostic.severity == ERROR
        assert result.breakdown["questions"] == 0

    def test_numbering_gap_is_reported(self):
        questions = questions_from([
            "1. Explain the first concept thoroughly in your own words. 10",
            "4. Explain the fourth concept thoroughly in your own words. 10",
        ])
        result = score(header=parse_header(FULL_HEADER), questions=questions,
                       max_marks=50, summary=summary())
        assert "question_sequence_gap" in codes(result)

    def test_recovered_labels_are_flagged(self):
        questions = questions_from([
            "1. Explain the sliding window protocol in your own words. 5",
            "Describe the operation of the distance vector algorithm. 10",
        ])
        result = score(header=parse_header(FULL_HEADER), questions=questions,
                       max_marks=50, summary=summary())
        assert "label_recovered" in codes(result)


class TestScoreBehaviour:
    def test_a_clean_extraction_scores_high(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        assert result.total >= 85
        assert result.level == "high"

    def test_unresolved_material_caps_the_score_below_full(self):
        """An extraction with open questions must not read as complete."""
        questions = questions_from([
            f"{n}. Explain in full the concept under discussion here now. 743"
            for n in range(1, 6)
        ])
        result = score(header=parse_header(FULL_HEADER), questions=questions,
                       max_marks=50, summary=summary())
        assert result.total <= 90

    def test_a_useful_extraction_is_not_failed_for_one_missing_field(self):
        header = parse_header("""Course Code: BHUM103L
Course Name: Microeconomics
Continuous Assessment Test-1 - Winter Semester 2024-2025""")
        result = score(header=header, questions=CLEAN, max_marks=None,
                       summary=summary())
        assert result.level in ("medium", "high")
        assert result.total >= 50

    def test_nothing_extracted_scores_low(self):
        result = score(header=parse_header(""), questions=[], max_marks=None,
                       summary=summary(source="none", ocr_used=False))
        assert result.level == "low"

    def test_breakdown_sums_to_the_total(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        assert sum(result.breakdown.values()) == result.total

    def test_diagnostics_are_ordered_by_severity(self):
        result = score(header=parse_header("Course Code: BHUM103L"), questions=[],
                       max_marks=None, summary=summary(source="none"))
        order = [d.severity for d in result.diagnostics]
        ranked = {ERROR: 0, WARNING: 1, UNRESOLVED: 2, INFO: 3}
        assert order == sorted(order, key=lambda s: ranked[s])

    def test_every_diagnostic_has_a_usable_shape(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN,
                       max_marks=50, summary=summary())
        for diagnostic in result.diagnostics:
            assert diagnostic.code and diagnostic.message
            assert diagnostic.severity in (ERROR, WARNING, UNRESOLVED, INFO)
            assert diagnostic.message[0].isupper() or diagnostic.message[0].isdigit()


class TestFigureDiagnostics:
    def test_detected_figures_are_reported(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN, max_marks=50,
                       summary=summary(figures_detected=2, figures_cropped=2,
                                       figures_crop_attempted=True))
        assert "figures_detected" in codes(result)

    def test_no_warning_when_cropping_was_never_attempted(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN, max_marks=50,
                       summary=summary(figures_detected=2, figures_cropped=0,
                                       figures_crop_attempted=False))
        assert "figures_not_cropped" not in codes(result)

    def test_failed_crops_are_warned_about(self):
        result = score(header=parse_header(FULL_HEADER), questions=CLEAN, max_marks=50,
                       summary=summary(figures_detected=2, figures_cropped=1,
                                       figures_crop_attempted=True))
        assert "figures_not_cropped" in codes(result)
