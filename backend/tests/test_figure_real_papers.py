"""Figure extraction against the supplied examination papers.

Each assertion below is a defect that reached the UI before this work, stated
as the geometry the paper actually has.  The suite prints which file it used,
so a pass is never mistaken for real-paper validation when a surrogate ran.
"""

from __future__ import annotations

import pdfplumber
import pytest
from PIL import Image

from app.services import figure_geometry as geo
from app.services import figure_detector, pipeline

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def bcse(request):
    path, is_real = request.getfixturevalue("bcse308l_pdf")
    trace = figure_detector.FigureTrace()
    result = pipeline.extract(str(path), figure_trace=trace)
    return {"result": result, "trace": trace, "is_real": is_real, "path": path}


@pytest.fixture(scope="module")
def bhum(request):
    path, is_real = request.getfixturevalue("bhum103l_pdf")
    trace = figure_detector.FigureTrace()
    result = pipeline.extract(str(path), figure_trace=trace)
    return {"result": result, "trace": trace, "is_real": is_real, "path": path}


def test_which_source_is_in_use(bcse, bhum, capsys):
    with capsys.disabled():
        print()
        for name, case in (("BCSE308L", bcse), ("BHUM103L", bhum)):
            kind = "REAL PDF" if case["is_real"] else "SYNTHETIC surrogate"
            print(f"  [figures/{name}] {kind}: {case['path']}")


class TestNoDuplicateRegions:
    def test_no_two_figures_overlap(self, bcse):
        """Previously two overlapping crops of the same router diagram."""
        figures = bcse["result"].figures
        for i in range(len(figures)):
            for j in range(i + 1, len(figures)):
                a, b = figures[i], figures[j]
                if a.page != b.page:
                    continue
                overlap = geo.describe(a.bbox, b.bbox)
                assert overlap.intersection == 0, (
                    f"figures {i} and {j} on page {a.page} overlap: "
                    f"iou={overlap.iou:.2f} containment={overlap.containment:.2f}"
                )

    def test_no_figure_contains_another(self, bcse):
        figures = bcse["result"].figures
        for i, a in enumerate(figures):
            for j, b in enumerate(figures):
                if i == j or a.page != b.page:
                    continue
                assert geo.describe(a.bbox, b.bbox).containment < 0.6

    def test_each_caption_is_claimed_once(self, bcse):
        captions = [f.caption for f in bcse["result"].figures if f.caption]
        assert len(captions) == len(set(captions))


class TestGeometryIsSane:
    def test_every_box_is_valid_and_inside_its_page(self, bcse):
        """A stored box ran past the sheet before clamping was applied."""
        with pdfplumber.open(bcse["path"]) as pdf:
            sizes = {i + 1: (float(p.width), float(p.height))
                     for i, p in enumerate(pdf.pages)}
        for f in bcse["result"].figures:
            width, height = sizes[f.page]
            assert geo.is_valid(f.bbox)
            assert 0 <= f.x0 < f.x1 <= width + 0.01
            assert 0 <= f.top < f.bottom <= height + 0.01

    def test_no_figure_is_a_thin_strip(self, bcse):
        for f in bcse["result"].figures:
            assert f.height >= figure_detector.MIN_INK_HEIGHT_PT
            assert f.width >= figure_detector.MIN_INK_WIDTH_PT

    def test_no_figure_covers_the_page(self, bcse):
        for f in bcse["result"].figures:
            assert f.area_ratio < figure_detector.MAX_INK_AREA_RATIO


class TestRealFiguresAreFound:
    def test_the_paper_s_three_figures_are_detected(self, bcse):
        if not bcse["is_real"]:
            pytest.skip("surrogate has a different figure set")
        assert len(bcse["result"].figures) == 3

    def test_each_numbered_caption_is_matched(self, bcse):
        if not bcse["is_real"]:
            pytest.skip("surrogate captions differ")
        captions = " ".join(f.caption or "" for f in bcse["result"].figures)
        for expected in ("Fig. 1", "Fig. 2", "Fig. 3"):
            assert expected in captions

    def test_figures_go_to_the_questions_that_reference_them(self, bcse):
        """Q10 cites Fig. 1, Q11 cites Fig. 2, Q12 cites Fig. 3."""
        if not bcse["is_real"]:
            pytest.skip("surrogate references differ")
        owners = {
            (f.caption or "").strip(): f.question_no
            for f in bcse["result"].figures
        }
        assert owners.get("Fig. 1") == "10"
        assert owners.get("Fig. 2") == "11"
        assert owners.get("Fig. 3") == "12"

    def test_the_congestion_graph_is_not_clipped_to_a_band(self, bcse):
        """It came out 85pt tall - half the axis - when bands were used."""
        if not bcse["is_real"]:
            pytest.skip("surrogate graph differs")
        graph = next(f for f in bcse["result"].figures
                     if (f.caption or "").startswith("Fig. 3"))
        assert graph.height > 140

    def test_the_router_diagram_is_one_region(self, bcse):
        if not bcse["is_real"]:
            pytest.skip("surrogate diagram differs")
        page2 = [f for f in bcse["result"].figures if f.page == 2]
        assert len(page2) == 2  # Fig. 1 and Fig. 2, not four fragments
        topology = next(f for f in page2
                        if (f.caption or "").startswith("Fig. 2"))
        assert topology.height > 180


class TestPageFurnitureIsNotAFigure:
    def test_the_masthead_table_is_not_reported(self, bcse):
        """The ruled Course Code / Max Marks block sits above question 1."""
        first = min((q for q in bcse["result"].questions if q.top is not None),
                    key=lambda q: (q.page, q.top))
        for f in bcse["result"].figures:
            before = f.page < first.page or (
                f.page == first.page and f.bottom <= first.top)
            assert not before, f"page furniture reported as a figure: {f.bbox}"

    def test_rejections_carry_reasons(self, bcse):
        assert bcse["trace"].rejected
        for entry in bcse["trace"].rejected:
            assert entry["reason"]

    def test_a_text_only_scan_yields_no_figures(self, bhum):
        """Scanner shadow and page edges must not become diagrams."""
        assert bhum["result"].figures == []


class TestFiguresDoNotDisturbQuestions:
    def test_question_count_is_unchanged(self, bcse):
        expected = 13
        assert len(bcse["result"].questions) == expected

    def test_marks_total_is_unchanged(self, bcse):
        total = sum(q.marks.total for q in bcse["result"].questions
                    if q.marks.resolved)
        assert total == 100

    def test_numbering_is_contiguous(self, bcse):
        numbers = [int(q.number) for q in bcse["result"].questions]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_no_question_text_was_swallowed(self, bcse):
        """A figure region must not erase the wording of its own question."""
        for q in bcse["result"].questions:
            assert len(q.text.split()) >= 3, f"Q{q.label} lost its text"

    def test_scanned_paper_keeps_its_questions(self, bhum):
        assert len(bhum["result"].questions) == 10
        total = sum(q.marks.total for q in bhum["result"].questions
                    if q.marks.resolved)
        assert total == 100


class TestDeterminism:
    def test_reprocessing_gives_identical_figures(self, bcse):
        """Same PDF, same figures - counts, boxes and owners."""
        again = pipeline.extract(str(bcse["path"]))
        before = [(f.page, tuple(round(v, 2) for v in f.bbox), f.question_no)
                  for f in bcse["result"].figures]
        after = [(f.page, tuple(round(v, 2) for v in f.bbox), f.question_no)
                 for f in again.figures]
        assert before == after


class TestCrops:
    def test_crops_are_real_images_of_the_right_size(self, bcse, tmp_path):
        figures = bcse["result"].figures
        with pdfplumber.open(bcse["path"]) as pdf:
            sizes = {i + 1: (float(p.width), float(p.height))
                     for i, p in enumerate(pdf.pages)}
        figure_detector.crop_figures(str(bcse["path"]), figures, tmp_path,
                                     page_sizes=sizes)
        for f in figures:
            assert f.image_path, f.note
            with Image.open(f.image_path) as image:
                assert image.width > 60 and image.height > 30
                # A blank crop is a failed crop.
                colours = image.convert("L").getcolors(maxcolors=256)
                assert colours is None or len(colours) > 4

    def test_crops_do_not_duplicate_each_other(self, bcse, tmp_path):
        """Distinct figures must not produce byte-identical images."""
        figures = bcse["result"].figures
        with pdfplumber.open(bcse["path"]) as pdf:
            sizes = {i + 1: (float(p.width), float(p.height))
                     for i, p in enumerate(pdf.pages)}
        figure_detector.crop_figures(str(bcse["path"]), figures, tmp_path,
                                     page_sizes=sizes)
        digests = set()
        for f in figures:
            data = open(f.image_path, "rb").read()
            assert data not in digests
            digests.add(data)


class TestDebugTrace:
    def test_trace_records_every_stage(self, bcse):
        trace = bcse["trace"]
        assert trace.raw, "no raw detections recorded"
        assert trace.final, "no final figures recorded"
        for entry in trace.raw:
            assert "detector" in entry and "bbox" in entry

    def test_trace_is_serialisable(self, bcse):
        import json

        json.dumps(bcse["trace"].to_dict())

    def test_more_raw_detections_than_final_figures(self, bcse):
        """Evidence the merge and rejection stages actually did something."""
        assert len(bcse["trace"].raw) >= len(bcse["result"].figures)
