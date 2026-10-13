"""Geometry and merge rules: the decisions behind duplicate and split figures.

These are pure-geometry tests, so they pin the rules exactly without
rendering a PDF.  Each case is one of the defect classes the merge stage
exists to resolve.
"""

import pytest

from app.services import figure_geometry as geo
from app.services.figure_detector import Figure
from app.services.figure_merge import (
    MergeResult,
    _should_merge,
    merge_detections,
)


def fig(page, box, kind="ink", **kw):
    return Figure(page=page, x0=box[0], top=box[1], x1=box[2], bottom=box[3],
                  kind=kind, detector=f"{kind}:test", **kw)


class TestOverlapMeasures:
    def test_identical_boxes(self):
        o = geo.describe((0, 0, 100, 100), (0, 0, 100, 100))
        assert o.iou == 1.0
        assert o.containment == 1.0

    def test_nested_box_has_low_iou_but_full_containment(self):
        """The case IoU alone gets wrong: a small crop inside a large one."""
        o = geo.describe((0, 0, 200, 200), (50, 50, 80, 80))
        assert o.iou < 0.05
        assert o.containment == pytest.approx(1.0)

    def test_disjoint_boxes_report_their_gap(self):
        o = geo.describe((0, 0, 100, 50), (0, 80, 100, 130))
        assert o.intersection == 0
        assert o.vertical_gap == pytest.approx(30.0)
        assert o.horizontal_alignment == pytest.approx(1.0)

    def test_side_by_side_boxes_report_horizontal_gap(self):
        o = geo.describe((0, 0, 50, 100), (70, 0, 120, 100))
        assert o.horizontal_gap == pytest.approx(20.0)

    def test_union_covers_both(self):
        assert geo.union((10, 10, 20, 20), (15, 5, 40, 18)) == (10, 5, 40, 20)

    def test_clamp_confines_to_the_page(self):
        """Detection can run past the sheet; a stored box never should."""
        assert geo.clamp((-5, 748, 527, 793.6), 533.6, 792.0) == (0.0, 748, 527, 792.0)

    def test_zero_area_boxes_are_invalid(self):
        assert not geo.is_valid((50, 50, 50, 50))
        assert not geo.is_valid((50, 50, 40, 60))
        assert geo.is_valid((50, 50, 60, 60))


class TestMergeRules:
    def test_exact_duplicate_merges(self):
        merged, rule = _should_merge((0, 0, 100, 100), (0, 0, 100, 100))
        assert merged and "containment" in rule

    def test_nested_duplicate_merges(self):
        merged, _ = _should_merge((0, 0, 200, 200), (50, 50, 80, 80))
        assert merged

    def test_partial_overlap_of_one_figure_merges(self):
        """The two overlapping halves seen on the real Computer Networks paper."""
        merged, _ = _should_merge((70.8, 446.9, 560, 574.9),
                                  (70.8, 530.7, 560, 650.8))
        assert merged

    def test_adjacent_fragments_merge_when_the_gap_has_ink(self):
        merged, rule = _should_merge((100, 100, 300, 150), (100, 158, 300, 210),
                                     gap_ink=0.08)
        assert merged and "fragment" in rule

    def test_adjacent_fragments_stay_separate_when_the_gap_is_blank(self):
        """Two diagrams close together are still two diagrams."""
        merged, rule = _should_merge((100, 100, 200, 150), (100, 165, 200, 215),
                                     gap_ink=0.0)
        assert not merged and "no ink" in rule

    def test_far_apart_never_merges(self):
        merged, rule = _should_merge((100, 100, 200, 150), (100, 400, 200, 450))
        assert not merged and rule == "disjoint"

    def test_misaligned_neighbours_do_not_merge(self):
        """Close vertically but in different columns: unrelated material."""
        merged, _ = _should_merge((0, 100, 60, 150), (400, 155, 460, 205),
                                  gap_ink=0.5)
        assert not merged

    def test_union_inflation_guard_keeps_diagonal_neighbours_apart(self):
        merged, rule = _should_merge((0, 0, 40, 40), (200, 45, 240, 85),
                                     gap_ink=0.9)
        assert not merged


class TestMergeDetections:
    def test_duplicate_detections_collapse_to_one(self):
        figures = [fig(1, (10, 10, 110, 110), "vector"),
                   fig(1, (12, 11, 108, 112), "ink")]
        out = merge_detections(figures)
        assert len(out) == 1

    def test_merged_figure_records_both_sources(self):
        """A lower-priority detector still contributed - say so."""
        out = merge_detections([fig(1, (10, 10, 110, 110), "vector"),
                                fig(1, (12, 11, 108, 112), "ink")])
        assert set(out[0].sources) == {"vector", "ink"}

    def test_precise_detector_names_the_result(self):
        out = merge_detections([fig(1, (10, 10, 110, 110), "vector"),
                                fig(1, (12, 11, 108, 112), "ink")])
        assert out[0].kind == "vector"

    def test_merged_geometry_is_the_union(self):
        """Neither detector's geometry is discarded."""
        out = merge_detections([fig(1, (10, 10, 100, 100), "vector"),
                                fig(1, (20, 20, 140, 130), "ink")])
        assert out[0].bbox == (10, 10, 140, 130)

    def test_three_fragments_of_one_figure_collapse(self):
        figures = [fig(1, (100, 100, 300, 150)),
                   fig(1, (100, 152, 300, 205)),
                   fig(1, (100, 207, 300, 260))]
        out = merge_detections(figures, continuity=lambda *_: 0.1)
        assert len(out) == 1
        assert out[0].bbox == (100, 100, 300, 260)

    def test_two_separate_diagrams_stay_separate(self):
        figures = [fig(1, (60, 100, 260, 200)), fig(1, (60, 230, 260, 330))]
        out = merge_detections(figures, continuity=lambda *_: 0.0)
        assert len(out) == 2

    def test_figures_on_different_pages_never_merge(self):
        out = merge_detections([fig(1, (10, 10, 110, 110)),
                                fig(2, (10, 10, 110, 110))])
        assert len(out) == 2

    def test_merging_is_deterministic_regardless_of_input_order(self):
        boxes = [(100, 100, 300, 150), (100, 152, 300, 205), (500, 400, 560, 460)]
        forward = merge_detections([fig(1, b) for b in boxes],
                                   continuity=lambda *_: 0.1)
        backward = merge_detections([fig(1, b) for b in reversed(boxes)],
                                    continuity=lambda *_: 0.1)
        assert [f.bbox for f in forward] == [f.bbox for f in backward]

    def test_repeated_merging_is_idempotent(self):
        once = merge_detections([fig(1, (10, 10, 110, 110)),
                                 fig(1, (12, 11, 108, 112))])
        twice = merge_detections(once)
        assert [f.bbox for f in once] == [f.bbox for f in twice]

    def test_decisions_are_recorded_for_debugging(self):
        result = MergeResult()
        merge_detections([fig(1, (10, 10, 110, 110)), fig(1, (12, 11, 108, 112))],
                         result=result)
        assert result.decisions
        assert any(d.merged for d in result.decisions)
        assert all("rule" in d.to_dict() for d in result.decisions)

    def test_single_figure_passes_through(self):
        out = merge_detections([fig(1, (10, 10, 110, 110))])
        assert len(out) == 1

    def test_empty_input(self):
        assert merge_detections([]) == []


class TestClippingEvidence:
    def test_content_touching_an_edge_is_reported(self):
        edges = geo.touches_edges((0, 0, 100, 100), (0, 50, 60, 100))
        assert "left" in edges and "bottom" in edges
        assert "top" not in edges and "right" not in edges

    def test_content_well_inside_reports_nothing(self):
        assert geo.touches_edges((0, 0, 100, 100), (20, 20, 80, 80)) == []
