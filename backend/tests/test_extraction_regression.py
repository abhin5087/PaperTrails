"""Golden regression tests for the two reference papers.

These bind to the real PDFs when they are present in ``tests/fixtures/pdfs``
and to generated surrogates otherwise.  ``test_which_source_is_in_use``
prints which one ran, so a green suite is never mistaken for proof that the
real documents were checked.

**The two sittings are not the same paper.**  The BHUM103L file supplied is
the *Final Assessment Test* for slot A1, 2023-2024: ten questions at ten
marks each, stated once as ``(10 X 10 = 100 Marks)``.  The surrogate models a
CAT-1 sitting: five questions at ten marks, printed per question.  Each set
of expectations therefore applies to the file actually in use, and the
shared expectations are the ones that hold for both.
"""

from __future__ import annotations

import pytest

from app.services import confidence, pipeline

pytestmark = pytest.mark.golden


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


@pytest.fixture(scope="module")
def bhum(request):
    path, is_real = request.getfixturevalue("bhum103l_pdf")
    return _run(path, is_real)


@pytest.fixture(scope="module")
def bcse(request):
    path, is_real = request.getfixturevalue("bcse308l_pdf")
    return _run(path, is_real)


def test_which_source_is_in_use(bhum, bcse, capsys):
    """Make the provenance of the golden run visible in the test output."""
    with capsys.disabled():
        print()
        for name, case in (("BHUM103L", bhum), ("BCSE308L", bcse)):
            kind = "REAL PDF" if case["is_real"] else "SYNTHETIC surrogate"
            print(f"  [{name}] {kind}: {case['path']}")


# ==========================================================================
# BHUM103L - Micro Economics
# ==========================================================================


class TestBhum103lSource:
    def test_is_a_scan_with_no_text_layer(self, bhum):
        """Both sittings are image-only, so OCR has to carry everything."""
        assert bhum["result"].summary.pdf_type == "scanned"
        assert bhum["result"].summary.source == "ocr"

    def test_header_came_from_the_winning_extraction_level(self, bhum):
        """A scan's header must come from the OCR text that actually won.

        This is the original regression: the header used to be parsed from
        the native text layer regardless, which is empty on a scan.
        """
        result = bhum["result"]
        assert result.candidate.header is result.header
        assert result.header.has("course_code")

    def test_multiple_candidates_were_compared(self, bhum):
        candidates = bhum["result"].diagnostics_source["candidates"]
        assert len([c for c in candidates if c["available"]]) >= 2
        assert sum(1 for c in candidates if c["selected"]) == 1


class TestBhum103lHeader:
    def test_course_code(self, bhum):
        """The real scan loses the trailing 'L' to a comma, so the code is
        read as BHUM103; the surrogate keeps it."""
        assert bhum["result"].header.get("course_code").startswith("BHUM103")

    def test_paper_total_is_one_hundred(self, bhum):
        if not bhum["is_real"]:
            pytest.skip("surrogate models the 50-mark CAT-1 sitting")
        assert bhum["max_marks"] == 100

    def test_total_comes_from_the_stated_distribution(self, bhum):
        if not bhum["is_real"]:
            pytest.skip("surrogate prints marks per question")
        field = bhum["result"].header.fields["max_marks"]
        assert field.source == "expression"
        assert bhum["result"].header.get("marks_distribution") == "10x10"


class TestBhum103lQuestions:
    def test_question_count(self, bhum):
        expected = 10 if bhum["is_real"] else 5
        assert len(bhum["result"].questions) == expected

    def test_questions_are_in_order(self, bhum):
        numbers = [int(q.number) for q in bhum["result"].questions]
        assert numbers == sorted(numbers)
        assert numbers[0] == 1

    def test_each_question_carries_real_text(self, bhum):
        for question in bhum["result"].questions:
            assert len(question.text.split()) >= 6, question.label

    def test_question_text_comes_from_the_paper(self, bhum):
        joined = " ".join(q.text.lower() for q in bhum["result"].questions)
        if bhum["is_real"]:
            # Topics actually set in the FAT A1 2023-2024 paper.
            for term in ("duopoly", "pareto", "equi-marginal", "budget line",
                         "lagrange", "elasticity"):
                assert term in joined, term
        else:
            assert "demand" in joined and "elasticity" in joined

    def test_instruction_numbering_does_not_become_questions(self, bhum):
        """The rubric's numbered instructions must not be read as questions."""
        joined = " ".join(q.text.lower() for q in bhum["result"].questions)
        assert "non programmable" not in joined
        assert "avoid bullet points" not in joined


class TestBhum103lMarks:
    def test_marks_sum_to_the_paper_total(self, bhum):
        assert bhum["score"].marks_extracted == bhum["max_marks"]

    def test_every_question_is_worth_ten(self, bhum):
        for question in bhum["result"].questions:
            assert question.marks.total == 10, question.label

    def test_distribution_derived_marks_are_labelled_as_such(self, bhum):
        """A value taken from the paper's banner must never look printed."""
        if not bhum["is_real"]:
            pytest.skip("surrogate prints marks per question")
        for question in bhum["result"].questions:
            assert question.marks.source == "distribution"
            assert question.marks.raw == "10 X 10 = 100"
            assert "stated distribution" in question.marks.reason

    def test_no_question_exceeds_its_evidence(self, bhum):
        for question in bhum["result"].questions:
            if question.marks.resolved:
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

    def test_confidence_is_at_least_medium(self, bhum):
        assert bhum["score"].total >= 50

    def test_no_phantom_figures_on_a_text_only_paper(self, bhum):
        """Neither sitting contains a diagram; page noise must not invent one."""
        assert bhum["result"].figures == []


# ==========================================================================
# BCSE308L - Computer Networks, FAT
# ==========================================================================


class TestBcse308lHeader:
    def test_course_code(self, bcse):
        assert bcse["result"].header.get("course_code") == "BCSE308L"

    def test_course_name(self, bcse):
        """Real paper prints 'Coerse itle COMPUTER NETIWORKS' - the label is
        damaged and the value is misspelt; both must still resolve."""
        name = bcse["result"].header.get("course_name")
        assert name is not None
        assert "COMPUTER NETWORKS" in name.upper()

    def test_exam_type(self, bcse):
        assert bcse["result"].header.get("exam_type") == "Final Assessment Test"

    def test_semester(self, bcse):
        assert "Fall" in (bcse["result"].header.get("semester") or "")

    def test_max_marks(self, bcse):
        assert bcse["max_marks"] == 100

    def test_duration(self, bcse):
        assert "3" in (bcse["result"].header.get("duration") or "")

    def test_part_banner_is_not_mistaken_for_the_paper_total(self, bcse):
        """'Part -A (6 X S Marks)' covers six questions, not the whole paper,
        and is not self-consistent, so it must not drive the marks."""
        if not bcse["is_real"]:
            pytest.skip("surrogate has no part banner")
        assert not bcse["result"].header.has("marks_distribution")


class TestBcse308lQuestions:
    def test_thirteen_top_level_questions(self, bcse):
        assert len(bcse["result"].questions) == 13

    def test_questions_are_in_order(self, bcse):
        numbers = [q.number for q in bcse["result"].questions]
        assert numbers == [str(n) for n in range(1, 14)]

    def test_question_text_comes_from_the_paper(self, bcse):
        joined = " ".join(q.text.lower() for q in bcse["result"].questions)
        for term in ("tcp", "router", "congestion", "http"):
            assert term in joined, term

    def test_question_thirteen_has_subparts(self, bcse):
        assert bcse["result"].questions[-1].children

    def test_zero_padded_labels_are_read(self, bcse):
        """The real paper numbers its questions 01., 02., ... not 1., 2."""
        if not bcse["is_real"]:
            pytest.skip("surrogate uses unpadded labels")
        assert bcse["result"].questions[0].number == "1"

    def test_garbled_label_is_recovered(self, bcse):
        """'1G.' is question 10 - the exact OCR damage in this paper."""
        if not bcse["is_real"]:
            pytest.skip("surrogate has no garbled label")
        question = next(q for q in bcse["result"].questions if q.number == "10")
        assert question.recovered_label is True


class TestBcse308lMarks:
    def test_first_six_are_worth_five(self, bcse):
        for question in bcse["result"].questions[:6]:
            assert question.marks.total == 5, question.label

    def test_remaining_seven_are_worth_ten(self, bcse):
        for question in bcse["result"].questions[6:]:
            assert question.marks.total == 10, question.label

    def test_total_matches_the_paper(self, bcse):
        assert bcse["score"].marks_extracted == 100

    def test_mismatched_delimiters_are_read(self, bcse):
        """The scan prints '(5]' and '[10)' - broken pairs must still parse."""
        if not bcse["is_real"]:
            pytest.skip("surrogate prints well-formed brackets")
        assert all(q.marks.resolved for q in bcse["result"].questions)


class TestBcse308lDiagramNoise:
    """The regression that produced phantom questions from diagram text."""

    def test_ip_octets_never_become_questions(self, bcse):
        numbers = {q.number for q in bcse["result"].questions}
        assert numbers == {str(n) for n in range(1, 14)}

    def test_question_count_is_not_inflated_by_diagrams(self, bcse):
        assert len(bcse["result"].questions) == 13

    def test_an_in_question_ip_block_is_kept(self, bcse):
        """Addresses that are part of the wording stay in the question."""
        joined = " ".join(q.text for q in bcse["result"].questions)
        expected = "128.64.0.0" if bcse["is_real"] else "192.168"
        assert expected in joined

    def test_numbering_stays_monotonic(self, bcse):
        numbers = [int(q.number) for q in bcse["result"].questions]
        assert numbers == sorted(numbers)


class TestBcse308lFigures:
    def test_diagrams_are_detected(self, bcse):
        assert len(bcse["result"].figures) >= 2

    def test_figures_are_attributed_to_questions(self, bcse):
        labels = {q.label for q in bcse["result"].questions}
        for figure in bcse["result"].figures:
            assert figure.question_no in labels

    def test_approximate_regions_say_so(self, bcse):
        """An ink region is a guess at the figure's bounds and must admit it."""
        for figure in bcse["result"].figures:
            if figure.kind == "ink":
                assert figure.note and "approximate" in figure.note


class TestBcse308lDiagnostics:
    def test_confidence_is_high(self, bcse):
        assert bcse["score"].total >= 80

    def test_source_is_reported_accurately(self, bcse):
        codes = {d.code for d in bcse["score"].diagnostics}
        if bcse["result"].summary.source == "native_text":
            assert "native_text_used" in codes
        else:
            assert "ocr_used" in codes

    def test_ocr_damage_in_the_text_layer_is_corrected(self, bcse):
        if not bcse["is_real"]:
            pytest.skip("surrogate text layer is clean")
        joined = " ".join(q.text for q in bcse["result"].questions)
        # 'diflerent', 'etwork' and 'Diferentiate' appear in the source scan.
        assert "diflerent" not in joined
        assert "Diferentiate" not in joined
        assert bcse["result"].candidate.corrections > 0


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

    def test_breakdown_explains_the_total(self, case):
        """The score must equal its own breakdown, cap included."""
        assert sum(case["score"].breakdown.values()) == case["score"].total

    def test_extraction_detail_is_investigable(self, case):
        detail = case["result"].diagnostics_source
        assert detail["candidates"]
        for candidate in detail["candidates"]:
            assert "score" in candidate and "selected" in candidate

    def test_marks_do_not_exceed_the_paper_total(self, case):
        assert case["score"].marks_extracted <= case["max_marks"]
