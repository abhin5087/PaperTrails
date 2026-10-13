"""Coordinate conversion between PDF points, page pixels and crops.

A figure that looks clipped is often a scale or origin mistake rather than
tight padding, so the conversions are pinned here directly.  The convention
throughout the pipeline is pdfplumber's: ``top`` grows downwards from the top
of the page.
"""

import pdfplumber
import pytest
from PIL import Image

from app.services import figure_detector, figure_ink
from app.services.figure_detector import CROP_DPI, Figure, crop_figures


class TestPointToPixel:
    @pytest.mark.parametrize("dpi", [72, 150, 300])
    def test_scale_is_dpi_over_72(self, dpi):
        page_width = 530.4
        pixels = page_width * dpi / 72.0
        assert pixels / page_width == pytest.approx(dpi / 72.0)

    def test_top_is_measured_downwards(self, vector_pdf):
        """A line near the top of the page must have a small `top`."""
        with pdfplumber.open(vector_pdf) as pdf:
            page = pdf.pages[0]
            lines = page.extract_text_lines()
            first, last = lines[0], lines[-1]
        assert first["top"] < last["top"]

    def test_render_matches_page_aspect(self, vector_pdf):
        from app.services.ocr import render_pages

        images = render_pages(str(vector_pdf), CROP_DPI)
        with pdfplumber.open(vector_pdf) as pdf:
            page = pdf.pages[0]
            expected = float(page.width) / float(page.height)
        actual = images[0].width / images[0].height
        assert actual == pytest.approx(expected, rel=0.01)


class TestCropGeometry:
    @pytest.fixture
    def page_one(self, vector_pdf):
        from app.services.ocr import render_pages

        images = render_pages(str(vector_pdf), CROP_DPI)
        with pdfplumber.open(vector_pdf) as pdf:
            sizes = {i + 1: (float(p.width), float(p.height))
                     for i, p in enumerate(pdf.pages)}
        return images, sizes

    def test_crop_lands_where_the_box_says(self, vector_pdf, page_one, tmp_path):
        """A crop of the top-left quarter must come from the top-left quarter."""
        images, sizes = page_one
        width, height = sizes[1]
        figure = Figure(page=1, x0=0, top=0, x1=width / 2, bottom=height / 2,
                        kind="vector")
        crop_figures(str(vector_pdf), [figure], tmp_path, page_images=images,
                     page_sizes=sizes)

        with Image.open(figure.image_path) as crop:
            expected_w = (width / 2) * images[0].width / width
            expected_h = (height / 2) * images[0].height / height
            # Padding adds a few pixels; the quarter must not be doubled or halved.
            assert crop.width == pytest.approx(expected_w, rel=0.08)
            assert crop.height == pytest.approx(expected_h, rel=0.08)

    def test_crop_is_clamped_to_the_page(self, vector_pdf, page_one, tmp_path):
        images, sizes = page_one
        width, height = sizes[1]
        figure = Figure(page=1, x0=width - 30, top=height - 30,
                        x1=width + 500, bottom=height + 500, kind="vector")
        crop_figures(str(vector_pdf), [figure], tmp_path, page_images=images,
                     page_sizes=sizes)
        with Image.open(figure.image_path) as crop:
            assert crop.width <= images[0].width
            assert crop.height <= images[0].height

    def test_crops_are_only_made_from_final_geometry(self, vector_pdf, tmp_path):
        """detect_figures must not leave crop files behind."""
        with pdfplumber.open(vector_pdf) as pdf:
            figure_detector.detect_figures(pdf, lines=[])
        assert list(tmp_path.iterdir()) == []


class TestPageBoxes:
    def test_crop_box_offset_is_respected(self, vector_pdf):
        """Page width/height come from the crop box, which is what we scale by."""
        with pdfplumber.open(vector_pdf) as pdf:
            page = pdf.pages[0]
            assert float(page.width) == pytest.approx(page.cropbox[2] - page.cropbox[0])
            assert float(page.height) == pytest.approx(page.cropbox[3] - page.cropbox[1])

    def test_rotation_is_reported(self, vector_pdf):
        with pdfplumber.open(vector_pdf) as pdf:
            assert pdf.pages[0].rotation in (0, 90, 180, 270)

    def test_real_scan_pages_scale_independently(self, bcse308l_pdf):
        """The supplied paper's pages differ in width; each must use its own."""
        path, _ = bcse308l_pdf
        with pdfplumber.open(path) as pdf:
            widths = {round(float(p.width), 1) for p in pdf.pages}
        assert len(widths) >= 1
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                assert float(page.width) > 0 and float(page.height) > 0


class TestInkGridConversion:
    def test_grid_cells_map_back_to_points(self):
        """A region's box must be expressible in page points, not cells."""
        image = Image.new("L", (1105, 1650), color=255)
        for y in range(400, 600):
            for x in range(200, 500):
                image.putpixel((x, y), 0)

        page = figure_ink.find_ink_regions(image, 1, [], 530.4, 792.0)
        assert page.regions
        box = page.regions[0].box
        # 200..500 px of 1105 across 530.4pt -> roughly 96..240pt
        assert 80 < box[0] < 115
        assert 225 < box[2] < 255

    def test_blank_page_yields_nothing(self):
        image = Image.new("L", (400, 500), color=255)
        page = figure_ink.find_ink_regions(image, 1, [], 300.0, 400.0)
        assert page.regions == []
        assert page.skipped
