"""Golden regression tests for the two reference papers.

These bind to the real PDFs when they are present in ``tests/fixtures/pdfs``
and to generated surrogates otherwise.  ``test_which_source_is_in_use``
prints which one ran, so a green suite is never mistaken for proof that the
real documents were checked.

The expectations below are the papers' own structure, not the extractor's
current output: they are the thing the extractor has to keep satisfying.
"""

from __future__ import annotations

import pytest

from app.services import confidence, pipeline

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def bhum(request):
    path, is_real = request.getfixturevalue("bhum103l_pdf")
    return _run(path, is_real)


@pytest.fixture(scope="module")
def bcse(request):
    path, is_real = request.getfixturevalue("bcse308l_pdf")
    return _run(path, is_real)


def _run(path, is_real):
    result = pipeline.extract(str(path))
    max_marks = result.header.get("max_marks")
    max_marks = int(max_marks) if (max_marks or "").isdigit() else None
    score = confidence.score(
        header=result.header,
        questions=result.questions,
        max_marks=max_marks,
        summary=result.summary,
    )
    return {"result": result, "score": score, "is_real": is_real, "path": path,
            "max_marks": max_marks}


def test_which_source_is_in_use(bhum, bcse, capsys):
    """Make the provenance of the golden run visible in the test output."""
    with capsys.disabled():
        for name, case in (("BHUM103L", bhum), ("BCSE308L", bcse)):
            kind = "REAL PDF" if case["is_real"] else "synthetic surrogate"
            print(f"\n  [{name}] {kind}: {case['path'].name}")


# ==========================================================================
# BHUM103L - Microeconomics, CAT-1, scanned
# ==========================================================================


class TestBhum103lHeader:
    def test_course_code(self, bhum):
        assert bhum["result"].header.get("course_code") == "BHUM103L"

    def test_course_name(self, bhum):
        assert bhum["result"].header.get("course_name").lower() == "microeconomics"

    def test_exam_type_uses_arabic_numerals(self, bhum):
        assert bhum["result"].header.get("exam_type") == "Continuous Assessment Test-1"

    def test_semester(self, bhum):
        assert bhum["result"].header.get("semester") == "Winter Semester"

    def test_max_marks(self, bhum):
        assert bhum["max_marks"] == 50

    def test_duration(self, bhum):
        assert "90" in (bhum["result"].header.get("duration") or "")

    def test_exam_date(self, bhum):
        assert bhum["result"].header.get("exam_date") == "16-02-2024"

    def test_header_came_from_the_winning_extraction_level(self, bhum):
        """A scanned paper's header must come from the OCR text that won.

        This is the regression: the header used to be parsed from the native
        text layer regardless, which is empty on a scan.
        """
        result = bhum["result"]
        assert result.summary.source == "ocr"
        assert result.candidate.header is result.header
        assert len(result.header) >= 5


class TestBhum103lQuestions:
    def test_five_top_level_questions(self, bhum):
        assert len(bhum["result"].questions) == 5

    def test_questions_are_in_order(self, bhum):
        numbers = [q.number for q in bhum["result"].questions]
        assert numbers == ["1", "2", "3", "4", "5"]

    def test_each_question_carries_real_text(self, bhum):
        for question in bhum["result"].questions:
            assert len(question.text.split()) >= 8, question.label

    def test_question_text_comes_from_the_paper(self, bhum):
        joined = " ".join(q.text.lower() for q in bhum["result"].questions)
        assert "demand" in joined
        assert "elasticity" in joined

    def test_multipart_questions_have_subparts(self, bhum):
        with_children = [q for q in bhum["result"].questions if q.children]
        assert len(with_children) >= 4

    def test_subparts_are_labelled_under_their_parent(self, bhum):
        question_two = bhum["result"].questions[1]
        assert [c.label for c in question_two.children] == ["2(a)", "2(b)"]


class TestBhum103lMarks:
    EXPECTED = {"1": 10, "2": 10, "3": 10, "4": 10, "5": 10}
    SPLITS = {"2": [5, 5], "3": [7, 3], "4": [2, 8], "5": [7, 3]}

    def test_each_question_is_worth_ten(self, bhum):
        actual = {q.number: q.marks.total for q in bhum["result"].questions}
        assert actual == self.EXPECTED

    def test_split_marks_are_preserved_as_raw_text(self, bhum):
        raw = {q.number: q.marks.raw for q in bhum["result"].questions}
        assert raw["2"] == "5+5"
        assert raw["3"] == "7+3"
        assert raw["4"] == "2+8"

    def test_split_parts_are_distributed_to_subparts(self, bhum):
        for question in bhum["result"].questions:
            expected = self.SPLITS.get(question.number)
            if expected and question.children:
                assert [c.marks.total for c in question.children] == expected

    def test_total_matches_the_paper(self, bhum):
        assert bhum["score"].marks_extracted == 50

    def test_parent_totals_are_not_double_counted(self, bhum):
        questions = bhum["result"].questions
        parents = sum(q.marks.total for q in questions if q.marks.resolved)
        children = sum(
            c.marks.total for q in questions for c in q.children if c.marks.resolved
        )
        assert parents == 50
        assert children == 40  # Q1 has no subparts

    def test_no_question_exceeds_its_evidence(self, bhum):
        for question in bhum["result"].questions:
            if question.marks.resolved:
                assert question.marks.total <= 50
                assert question.marks.raw is not None


class TestBhum103lDiagnostics:
    def test_ocr_is_reported_as_having_run(self, bhum):
        codes = {d.code for d in bhum["score"].diagnostics}
        assert "ocr_used" in codes
        assert "ocr_unavailable" not in codes
        assert "ocr_failed" not in codes

    def test_no_stale_not_implemented_message(self, bhum):
        text = " ".join(d.message for d in bhum["score"].diagnostics).lower()
        assert "not yet implemented" not in text

    def test_multiple_candidates_were_compared(self, bhum):
        candidates = bhum["result"].diagnostics_source["candidates"]
        assert len([c for c in candidates if c["available"]]) >= 2
        assert sum(1 for c in candidates if c["selected"]) == 1

    def test_confidence_is_high(self, bhum):
        assert bhum["score"].total >= 80

    def test_no_phantom_figures_on_a_text_only_scan(self, bhum):
        assert bhum["result"].figures == []


# ==========================================================================
# BCSE308L - Computer Networks, FAT, diagram-heavy
# ==========================================================================


class TestBcse308lHeader:
    def test_course_code(self, bcse):
        assert bcse["result"].header.get("course_code") == "BCSE308L"

    def test_course_name(self, bcse):
        assert "COMPUTER NETWORKS" in bcse["result"].header.get("course_name").upper()

    def test_exam_type(self, bcse):
        assert bcse["result"].header.get("exam_type") == "Final Assessment Test"

    def test_semester(self, bcse):
        assert "Fall" in (bcse["result"].header.get("semester") or "")

    def test_max_marks(self, bcse):
        assert bcse["max_marks"] == 100

    def test_duration(self, bcse):
        assert "3" in (bcse["result"].header.get("duration") or "")


class TestBcse308lQuestions:
    def test_thirteen_top_level_questions(self, bcse):
        assert len(bcse["result"].questions) == 13

    def test_questions_are_in_order(self, bcse):
        numbers = [q.number for q in bcse["result"].questions]
        assert numbers == [str(n) for n in range(1, 14)]

    def test_question_text_comes_from_the_paper(self, bcse):
        joined = " ".join(q.text.lower() for q in bcse["result"].questions)
        for term in ("tcp", "router", "congestion", "dns"):
            assert term in joined

    def test_question_thirteen_has_subparts(self, bcse):
        assert len(bcse["result"].questions[-1].children) >= 2


class TestBcse308lMarks:
    def test_first_six_are_worth_five(self, bcse):
        for question in bcse["result"].questions[:6]:
            assert question.marks.total == 5, question.label

    def test_remaining_seven_are_worth_ten(self, bcse):
        for question in bcse["result"].questions[6:]:
            assert question.marks.total == 10, question.label

    def test_total_matches_the_paper(self, bcse):
        assert bcse["score"].marks_extracted == 100


class TestBcse308lDiagramNoise:
    """The regression that produced phantom questions from diagram text."""

    def test_ip_octets_never_become_questions(self, bcse):
        numbers = {q.number for q in bcse["result"].questions}
        for octet in ("16", "255", "192", "168", "0"):
            if octet not in {str(n) for n in range(1, 14)}:
                assert octet not in numbers

    def test_question_count_is_not_inflated_by_diagrams(self, bcse):
        assert len(bcse["result"].questions) == 13

    def test_ip_addresses_stay_in_their_question_text(self, bcse):
        joined = " ".join(q.text for q in bcse["result"].questions)
        assert "192.168" in joined

    def test_axis_ticks_do_not_create_questions(self, bcse):
        rejected = [
            c for c in bcse["result"].candidate.classified
            if c.kind != "question" and "rejected as question" in c.reason
        ]
        # Either nothing looked like a label, or everything that did was refused.
        numbers = [q.number for q in bcse["result"].questions]
        assert numbers == sorted(numbers, key=int)
        assert all(c.kind != "question" for c in rejected)


class TestBcse308lFigures:
    def test_both_diagrams_are_detected(self, bcse):
        assert len(bcse["result"].figures) >= 2

    def test_figures_are_attributed_to_questions(self, bcse):
        for figure in bcse["result"].figures:
            assert figure.question_no is not None

    def test_topology_and_graph_belong_to_different_questions(self, bcse):
        owners = [f.question_no for f in bcse["result"].figures]
        assert len(set(owners)) == len(owners)

    def test_figures_sit_under_plausible_questions(self, bcse):
        labels = {q.label for q in bcse["result"].questions}
        for figure in bcse["result"].figures:
            assert figure.question_no in labels


class TestBcse308lDiagnostics:
    def test_confidence_is_high(self, bcse):
        assert bcse["score"].total >= 80

    def test_source_is_reported_accurately(self, bcse):
        codes = {d.code for d in bcse["score"].diagnostics}
        if bcse["result"].summary.source == "native_text":
            assert "native_text_used" in codes
        else:
            assert "ocr_used" in codes


# ==========================================================================
# Properties that must hold for any paper
# ==========================================================================


class TestInvariants:
    @pytest.fixture(params=["bhum", "bcse"])
    def case(self, request):
        return request.getfixturevalue(request.param)

    def test_marks_are_never_invented(self, case):
        for question in case["result"].questions:
            if question.marks.total is not None:
                assert question.marks.raw, f"{question.label} has a mark with no source"

    def test_unresolved_marks_keep_their_raw_text(self, case):
        for question in case["result"].questions:
            if question.marks.raw and not question.marks.resolved:
                assert question.marks.total is None
                assert question.marks.reason

    def test_every_question_has_a_page(self, case):
        for question in case["result"].questions:
            assert question.page >= 1

    def test_breakdown_sums_to_total(self, case):
        assert sum(case["score"].breakdown.values()) == case["score"].total

    def test_extraction_detail_is_investigable(self, case):
        detail = case["result"].diagnostics_source
        assert detail["candidates"]
        for candidate in detail["candidates"]:
            assert "score" in candidate and "selected" in candidate
