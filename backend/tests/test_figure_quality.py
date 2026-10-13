"""Rejection rules: what is not a figure.

The classes here are the ones that previously reached the UI as figures -
scanner shadow, the page border, the masthead table - plus the cases that
must survive those rules: a sparse line graph, a diagram near the page edge,
a diagram covered in its own labels.
"""

import pytest

from app.services.figure_detector import (
    MAX_EDGE_INK,
    MAX_PROSE_COVERAGE,
    MIN_INK_HEIGHT_PT,
    MIN_INK_OCCUPANCY,
    MIN_INK_WIDTH_PT,
    MIN_REGION_INK_DENSITY,
    Figure,
    _reject_ink_region,
    drop_page_furniture,
)
from app.services.figure_ink import InkRegion
from app.services.questions import Question

PAGE_W, PAGE_H = 530.0, 792.0


def region(box, *, density=0.3, text=0.0, prose=0.0, rows=0.9, cols=0.9, edge=0.0):
    return InkRegion(box=box, density=density, text_coverage=text, cells=500,
                     content_box=box, row_occupancy=rows, col_occupancy=cols,
                     edge_ink=edge, prose_coverage=prose)


class TestRejected:
    def test_zero_area(self):
        assert "zero-area" in _reject_ink_region(region((50, 50, 50, 50)),
                                                 PAGE_W, PAGE_H)

    def test_inverted_box(self):
        assert _reject_ink_region(region((50, 50, 40, 40)), PAGE_W, PAGE_H)

    def test_thin_horizontal_strip_is_a_page_edge(self):
        reason = _reject_ink_region(region((0, 770, 500, 785)), PAGE_W, PAGE_H)
        assert "too short" in reason

    def test_narrow_sliver(self):
        reason = _reject_ink_region(region((0, 100, 20, 400)), PAGE_W, PAGE_H)
        assert "too narrow" in reason

    def test_page_border_line_is_rejected_by_ink_spread(self):
        """A border fills every row but almost no column.

        Density cannot catch this - on the supplied paper the blank bordered
        strip is *denser* than the real congestion graph - so the rule is
        spread across both axes.
        """
        reason = _reject_ink_region(
            region((0, 200, 120, 700), density=0.10, rows=1.0, cols=0.02),
            PAGE_W, PAGE_H,
        )
        assert "columns" in reason

    def test_shadow_along_the_top_is_rejected(self):
        reason = _reject_ink_region(
            region((0, 0, 500, 60), density=0.2, rows=0.03, cols=1.0),
            PAGE_W, PAGE_H,
        )
        assert "rows" in reason

    def test_margin_ink_is_rejected(self):
        reason = _reject_ink_region(
            region((0, 600, 200, 700), edge=MAX_EDGE_INK + 0.2), PAGE_W, PAGE_H
        )
        assert "margin" in reason

    def test_nearly_blank_region_is_rejected(self):
        reason = _reject_ink_region(
            region((100, 100, 400, 400), density=MIN_REGION_INK_DENSITY / 4),
            PAGE_W, PAGE_H,
        )
        assert "faint" in reason

    def test_prose_block_is_rejected(self):
        reason = _reject_ink_region(
            region((60, 100, 480, 300), prose=MAX_PROSE_COVERAGE + 0.3),
            PAGE_W, PAGE_H,
        )
        assert "prose" in reason

    def test_page_sized_region_is_rejected(self):
        reason = _reject_ink_region(region((0, 0, 528, 790)), PAGE_W, PAGE_H)
        assert "page" in reason


class TestAccepted:
    def test_a_sparse_line_graph_survives(self):
        """The congestion graph is mostly white space; it is still a figure."""
        assert _reject_ink_region(
            region((60, 63, 340, 228), density=0.07, text=0.07, prose=0.0,
                   rows=0.93, cols=0.97),
            PAGE_W, PAGE_H,
        ) is None

    def test_a_diagram_covered_in_its_own_labels_survives(self):
        """High text coverage, no prose: a topology full of IP addresses."""
        assert _reject_ink_region(
            region((71, 441, 346, 651), density=0.16, text=0.48, prose=0.05),
            PAGE_W, PAGE_H,
        ) is None

    def test_a_diagram_near_the_page_bottom_survives(self):
        """Edge proximity is evidence, not a veto - most ink is still inside."""
        assert _reject_ink_region(
            region((100, 650, 400, 780), edge=0.05), PAGE_W, PAGE_H
        ) is None

    def test_a_small_but_valid_figure_survives(self):
        assert _reject_ink_region(
            region((132, 282, 204, 374), density=0.15, text=0.22),
            PAGE_W, PAGE_H,
        ) is None

    @pytest.mark.parametrize("page", [(530.0, 792.0), (681.0, 1131.0), (300.0, 400.0)])
    def test_thresholds_do_not_depend_on_page_size(self, page):
        """A figure of the same physical size is judged the same on any sheet."""
        box = (100, 100, 100 + MIN_INK_WIDTH_PT + 20,
               100 + MIN_INK_HEIGHT_PT + 20)
        assert _reject_ink_region(region(box), *page) is None


class TestPageFurniture:
    def _questions(self):
        return [Question(number="1", text="first question", page=1, top=240.0),
                Question(number="2", text="second question", page=2, top=100.0)]

    def test_masthead_table_above_the_first_question_is_dropped(self):
        """The ruled Course Code / Max Marks block is a table, not a figure."""
        header = Figure(page=1, x0=26, top=86, x1=504, bottom=202, kind="ink")
        assert drop_page_furniture([header], self._questions()) == []

    def test_a_figure_below_the_first_question_is_kept(self):
        inside = Figure(page=1, x0=100, top=300, x1=400, bottom=450, kind="ink")
        assert drop_page_furniture([inside], self._questions()) == [inside]

    def test_a_figure_at_the_top_of_a_later_page_is_kept(self):
        """Page 2's top can legitimately hold a figure for a question above it."""
        top_of_page = Figure(page=2, x0=60, top=20, x1=400, bottom=90, kind="ink")
        assert drop_page_furniture([top_of_page], self._questions()) == [top_of_page]

    def test_a_figure_after_the_last_question_is_kept(self):
        trailing = Figure(page=2, x0=60, top=600, x1=400, bottom=700, kind="ink")
        assert drop_page_furniture([trailing], self._questions()) == [trailing]

    def test_without_questions_nothing_is_dropped(self):
        f = Figure(page=1, x0=0, top=0, x1=100, bottom=100, kind="ink")
        assert drop_page_furniture([f], []) == [f]

    def test_rejection_is_recorded_in_the_trace(self):
        from app.services.figure_detector import FigureTrace

        trace = FigureTrace()
        header = Figure(page=1, x0=26, top=86, x1=504, bottom=202, kind="ink")
        drop_page_furniture([header], self._questions(), trace=trace)
        assert trace.rejected
        assert "page furniture" in trace.rejected[0]["reason"]
