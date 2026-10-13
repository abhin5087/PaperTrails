"""Figure detection, association and cropping."""

import pdfplumber
import pytest
from PIL import Image

from app.services import figure_detector
from app.services.figure_detector import (
    Figure,
    associate_with_questions,
    attach_captions,
    crop_figures,
    detect_figures,
    grow_to_labels,
)
from app.services.questions import Line, extract_questions


def native_lines(pdf):
    out = []
    for page_no, page in enumerate(pdf.pages, start=1):
        for index, item in enumerate(page.extract_text_lines()):
            out.append(
                Line(text=item["text"], page=page_no, index=index, x0=item["x0"],
                     top=item["top"], bottom=item["bottom"], x1=item["x1"])
            )
    return out


@pytest.fixture
def networks(vector_pdf):
    """Vector-detector mechanics, on the fixture with exact known geometry."""
    path = vector_pdf
    with pdfplumber.open(path) as pdf:
        lines = native_lines(pdf)
        figures = detect_figures(pdf, lines=lines)
        grow_to_labels(figures, lines)
        attach_captions(figures, lines)
        sizes = {i + 1: (float(p.width), float(p.height))
                 for i, p in enumerate(pdf.pages)}
    questions, _ = extract_questions(lines)
    associate_with_questions(figures, questions)
    return {"path": path, "figures": figures, "questions": questions, "sizes": sizes,
            "lines": lines}


class TestDetection:
    def test_vector_diagrams_are_found(self, networks):
        assert len(networks["figures"]) >= 2
        assert all(f.kind == "vector" for f in networks["figures"])

    def test_figures_have_real_extent(self, networks):
        for figure in networks["figures"]:
            assert figure.width > 0 and figure.height > 0
            assert 0 < figure.area_ratio < 1

    def test_captions_are_attached(self, networks):
        captions = [f.caption for f in networks["figures"] if f.caption]
        assert any("topology" in c.lower() for c in captions)
        assert any("congestion" in c.lower() for c in captions)

    def test_figure_bounds_cover_their_label_text(self, networks):
        """A topology crop is useless without its IP labels."""
        topology = networks["figures"][0]
        ip_lines = [
            ln for ln in networks["lines"]
            if "10.0.0.1" in ln.text and ln.page == topology.page
        ]
        assert ip_lines, "fixture should carry IP labels"
        assert topology.bottom >= ip_lines[0].bottom


class TestAssociation:
    def test_each_figure_is_attributed_to_a_question(self, networks):
        for figure in networks["figures"]:
            assert figure.question_no is not None

    def test_topology_belongs_to_the_subnetting_question(self, networks):
        topology = next(f for f in networks["figures"]
                        if f.caption and "topology" in f.caption.lower())
        owner = next(q for q in networks["questions"]
                     if q.label == topology.question_no)
        assert "192.168" in owner.text or "address" in owner.text.lower()

    def test_a_figure_is_not_handed_to_an_unrelated_question(self, networks):
        owners = {f.question_no for f in networks["figures"]}
        assert len(owners) == len(networks["figures"])

    def test_figure_between_stem_and_subparts_goes_to_the_parent(self):
        """A figure printed above the subparts belongs to the question itself."""
        lines = [
            Line(text="13. Answer the following about congestion control here.",
                 page=1, index=0, x0=0.0, top=10.0, bottom=20.0),
            Line(text="(a) Explain slow start using the graph shown above.",
                 page=1, index=1, x0=40.0, top=80.0, bottom=90.0),
        ]
        questions, _ = extract_questions(lines)
        figure = Figure(page=1, x0=30, top=30, x1=300, bottom=70, kind="vector")
        associate_with_questions([figure], questions)
        assert figure.question_no == "13"

    def test_no_questions_leaves_figures_unattributed(self):
        figure = Figure(page=1, x0=0, top=0, x1=10, bottom=10, kind="vector")
        associate_with_questions([figure], [])
        assert figure.question_no is None


class TestCropping:
    def test_crops_are_real_images(self, networks, tmp_path):
        crop_figures(str(networks["path"]), networks["figures"], tmp_path,
                     page_sizes=networks["sizes"])
        for figure in networks["figures"]:
            assert figure.image_path, figure.note
            with Image.open(figure.image_path) as image:
                assert image.width > 50 and image.height > 20
                # A blank crop is a failed crop.
                assert len(image.convert("L").getcolors(maxcolors=256) or []) > 1

    def test_crop_dimensions_are_recorded(self, networks, tmp_path):
        crop_figures(str(networks["path"]), networks["figures"], tmp_path,
                     page_sizes=networks["sizes"])
        for figure in networks["figures"]:
            assert figure.width_px and figure.height_px

    def test_crop_failure_is_recorded_not_raised(self, networks, tmp_path):
        broken = Figure(page=99, x0=0, top=0, x1=10, bottom=10, kind="vector")
        crop_figures(str(networks["path"]), [broken], tmp_path,
                     page_sizes=networks["sizes"])
        assert broken.image_path is None
        assert broken.note and "page out of range" in broken.note

    def test_empty_region_is_skipped_safely(self, networks, tmp_path):
        empty = Figure(page=1, x0=50, top=50, x1=50, bottom=50, kind="vector")
        crop_figures(str(networks["path"]), [empty], tmp_path,
                     page_sizes=networks["sizes"])
        assert empty.image_path is None

    def test_no_figures_is_not_an_error(self, tmp_path):
        crop_figures("missing.pdf", [], tmp_path)


class TestPapersWithoutFigures:
    def test_a_text_only_scan_reports_no_figures(self, generated_pdfs):
        """Header text must never be reported as a diagram."""
        from app.services import pipeline

        result = pipeline.extract(str(generated_pdfs["bhum103l"]))
        assert result.figures == []

    def test_question_extraction_is_unaffected(self, generated_pdfs):
        from app.services import pipeline

        result = pipeline.extract(str(generated_pdfs["bhum103l"]))
        assert len(result.questions) == 5


class TestFullPageImageIsNotAFigure:
    def test_page_scan_is_excluded(self, generated_pdfs):
        path = generated_pdfs["bhum103l"]
        with pdfplumber.open(path) as pdf:
            assert len(pdf.pages[0].images) >= 1  # the scan itself
            figures = detect_figures(pdf, lines=[])
        assert all(f.kind != "image" for f in figures)


class TestInkDetector:
    @pytest.mark.slow
    def test_real_diagrams_are_found_on_a_pure_scan(self, bcse308l_scanned_pdf):
        from app.services import pipeline

        result = pipeline.extract(str(bcse308l_scanned_pdf))
        assert len(result.figures) == 2
        assert all(f.kind == "ink" for f in result.figures)
        assert all(f.question_no for f in result.figures)
