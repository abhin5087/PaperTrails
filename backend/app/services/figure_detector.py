"""Figure, diagram and table detection, plus association to questions.

Three sources are handled, because exam papers mix all of them:

``vector``
    Clusters of lines, rects and curves drawn into the PDF - network
    topologies, graphs, ruled tables.
``image``
    Embedded raster images.  A single image covering most of the page is the
    *scan itself*, not a figure, so it is ignored.
``ink``
    For a scanned page there is no vector geometry at all, so the rendered
    page is examined for blocks of ink that no OCR word box covers.  That is
    what a hand-drawn or photographed diagram looks like to us.

Every figure is cropped to a real PNG.  When a region cannot be isolated
cleanly the crop is still a usable picture of that part of the page, which is
more honest than claiming a precise extraction that did not happen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: An image this large relative to the page is the page scan, not a figure.
FULL_PAGE_IMAGE_RATIO = 0.65

#: Smallest figure worth reporting, as a fraction of page area.
MIN_FIGURE_AREA_RATIO = 0.01

#: Gap (PDF points) below which two drawing objects join one figure.
CLUSTER_GAP = 26.0

#: How far below a figure a caption may sit.
CAPTION_WINDOW = 46.0

#: How far a figure may reach to absorb its own labels (axis ticks, node
#: names, IP addresses).  Deliberately small so question prose is not pulled in.
LABEL_WINDOW = 18.0

#: A line longer than this is prose, never a figure label.
MAX_LABEL_CHARS = 60

CROP_DPI = 150
CROP_PADDING = 6.0


@dataclass
class Figure:
    """One detected figure."""

    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    kind: str  # vector | image | ink
    detector: str = ""
    caption: str | None = None
    question_no: str | None = None
    image_path: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    area_ratio: float = 0.0
    note: str | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "kind": self.kind,
            "detector": self.detector,
            "bbox": [round(v, 2) for v in self.bbox],
            "caption": self.caption,
            "question_no": self.question_no,
            "image_path": self.image_path,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "area_ratio": round(self.area_ratio, 4),
            "note": self.note,
        }


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------


def _merge(a: Figure, b: Figure) -> Figure:
    return Figure(
        page=a.page,
        x0=min(a.x0, b.x0),
        top=min(a.top, b.top),
        x1=max(a.x1, b.x1),
        bottom=max(a.bottom, b.bottom),
        kind=a.kind,
        detector=a.detector,
    )


def _overlaps(a: Figure, b: Figure, gap: float) -> bool:
    return not (
        a.x1 + gap < b.x0
        or b.x1 + gap < a.x0
        or a.bottom + gap < b.top
        or b.bottom + gap < a.top
    )


def _cluster(boxes: list[Figure], gap: float = CLUSTER_GAP) -> list[Figure]:
    """Merge boxes that touch or nearly touch into single figures."""
    clusters: list[Figure] = []

    for box in boxes:
        merged = box
        changed = True
        while changed:
            changed = False
            for existing in list(clusters):
                if _overlaps(merged, existing, gap):
                    clusters.remove(existing)
                    merged = _merge(merged, existing)
                    changed = True
        clusters.append(merged)

    return clusters


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------


def _vector_figures(page, page_no: int) -> list[Figure]:
    """Clusters of drawn geometry."""
    boxes: list[Figure] = []

    for kind, objects in (
        ("line", getattr(page, "lines", [])),
        ("rect", getattr(page, "rects", [])),
        ("curve", getattr(page, "curves", [])),
    ):
        for obj in objects:
            try:
                x0, top = float(obj["x0"]), float(obj["top"])
                x1, bottom = float(obj["x1"]), float(obj["bottom"])
            except (KeyError, TypeError, ValueError):
                continue
            if x1 <= x0 or bottom < top:
                continue
            boxes.append(
                Figure(page=page_no, x0=x0, top=top, x1=x1, bottom=bottom,
                       kind="vector", detector=f"vector:{kind}")
            )

    return _cluster(boxes)


def _image_figures(page, page_no: int, page_area: float) -> list[Figure]:
    """Embedded raster images, excluding the full-page scan."""
    out: list[Figure] = []

    for image in getattr(page, "images", []):
        try:
            x0, top = float(image["x0"]), float(image["top"])
            x1, bottom = float(image["x1"]), float(image["bottom"])
        except (KeyError, TypeError, ValueError):
            continue

        area = max(0.0, x1 - x0) * max(0.0, bottom - top)
        if page_area and area / page_area >= FULL_PAGE_IMAGE_RATIO:
            continue  # the page scan itself

        out.append(
            Figure(page=page_no, x0=x0, top=top, x1=x1, bottom=bottom,
                   kind="image", detector="image:embedded")
        )

    return _cluster(out)


def _ink_figures(image, page_no: int, word_boxes: list[tuple[float, float, float, float]],
                 page_width: float, page_height: float) -> list[Figure]:
    """Blocks of ink on a rendered page that no OCR word covers.

    This is the only detector that works on a pure scan, where the PDF holds
    no geometry to inspect.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a hard dependency
        return []

    grey = image.convert("L")
    px_w, px_h = grey.size
    if not px_w or not px_h:
        return []

    data = np.asarray(grey, dtype=np.uint8)
    ink = data < 190  # dark pixels

    # Blank out everything OCR already explained as text.
    sx, sy = px_w / page_width, px_h / page_height
    for x0, top, x1, bottom in word_boxes:
        cx0 = max(0, int(x0 * sx) - 2)
        cx1 = min(px_w, int(x1 * sx) + 2)
        cy0 = max(0, int(top * sy) - 2)
        cy1 = min(px_h, int(bottom * sy) + 2)
        if cx1 > cx0 and cy1 > cy0:
            ink[cy0:cy1, cx0:cx1] = False

    row_ink = ink.sum(axis=1)
    # A row counts as part of a figure when a non-trivial share of it is ink.
    threshold = max(6, int(px_w * 0.012))
    active = row_ink > threshold
    if not active.any():
        return []

    figures: list[Figure] = []
    start: int | None = None
    gap_rows = int(px_h * 0.012)
    blanks = 0

    for y in range(px_h):
        if active[y]:
            if start is None:
                start = y
            blanks = 0
        elif start is not None:
            blanks += 1
            if blanks > gap_rows:
                figures.extend(
                    _band_to_figure(ink, start, y - blanks, page_no, sx, sy, px_w)
                )
                start, blanks = None, 0

    if start is not None:
        figures.extend(_band_to_figure(ink, start, px_h - 1, page_no, sx, sy, px_w))

    return figures


def _band_to_figure(ink, y0: int, y1: int, page_no: int, sx: float, sy: float,
                    px_w: int) -> list[Figure]:
    """Turn a horizontal ink band into a figure box with tight columns."""
    import numpy as np

    if y1 <= y0:
        return []

    band = ink[y0 : y1 + 1]
    columns = band.sum(axis=0)
    active = np.nonzero(columns > 0)[0]
    if active.size == 0:
        return []

    x_start, x_end = int(active[0]), int(active[-1])
    if x_end - x_start < px_w * 0.05:
        return []

    return [
        Figure(
            page=page_no,
            x0=x_start / sx,
            top=y0 / sy,
            x1=x_end / sx,
            bottom=y1 / sy,
            kind="ink",
            detector="ink:unexplained-region",
        )
    ]


# --------------------------------------------------------------------------
# Captions and association
# --------------------------------------------------------------------------


def grow_to_labels(figures: list[Figure], lines) -> None:
    """Extend each figure to cover the text printed as part of it.

    A topology's IP addresses and a graph's axis ticks are drawn as text, so
    the vector cluster alone clips them out of the crop.  Only short lines
    that sit inside the figure's horizontal span and within
    :data:`LABEL_WINDOW` of its edges are absorbed, which keeps question
    prose out.
    """
    from .questions import (
        DOTTED_DECIMAL_RE,
        FIGURE_CAPTION_RE,
        QUESTION_LABEL_RE,
    )

    for figure in figures:
        for line in lines:
            if line.page != figure.page:
                continue
            if line.top is None or line.bottom is None or line.x0 is None:
                continue

            text = line.text.strip()
            if not text or len(text) > MAX_LABEL_CHARS:
                continue
            if FIGURE_CAPTION_RE.match(text):
                continue
            # "10.0.0.1" matches the question-label pattern but is an IP
            # address, so dotted-decimal runs stay eligible as labels.
            if QUESTION_LABEL_RE.match(text) and not DOTTED_DECIMAL_RE.search(text):
                continue

            if not (figure.top - LABEL_WINDOW <= line.top
                    and line.bottom <= figure.bottom + LABEL_WINDOW):
                continue

            width = _estimate_width(line)
            x1 = line.x0 + width
            overlap = min(x1, figure.x1) - max(line.x0, figure.x0)
            if overlap <= 0 or overlap < width * 0.5:
                continue

            figure.x0 = min(figure.x0, line.x0)
            figure.x1 = max(figure.x1, x1)
            figure.top = min(figure.top, line.top)
            figure.bottom = max(figure.bottom, line.bottom)


def attach_captions(figures: list[Figure], lines) -> None:
    """Attach the nearest caption line printed under each figure."""
    from .questions import FIGURE_CAPTION_RE

    captions = [
        ln for ln in lines
        if ln.top is not None and FIGURE_CAPTION_RE.match(ln.text.strip())
    ]

    for figure in figures:
        best, best_gap = None, CAPTION_WINDOW
        for line in captions:
            if line.page != figure.page:
                continue
            gap = (line.top or 0) - figure.bottom
            if -6.0 <= gap <= best_gap:
                best, best_gap = line, gap
        if best is not None:
            figure.caption = " ".join(best.text.split())


def associate_with_questions(figures: list[Figure], questions) -> None:
    """Give every figure the question it sits under.

    A figure belongs to the last question that opened above it on the same
    page.  Subquestions are resolved to their parent so that a figure printed
    between a question stem and its subparts is not handed to one subpart.
    """
    if not questions:
        return

    anchors: list[tuple[int, float, str]] = []
    for question in questions:
        if question.top is None:
            continue
        anchors.append((question.page, question.top, question.label))

    if not anchors:
        # No geometry at all: fall back to page ownership.
        by_page: dict[int, str] = {}
        for question in questions:
            by_page.setdefault(question.page, question.label)
        for figure in figures:
            figure.question_no = by_page.get(figure.page)
            if figure.question_no:
                figure.note = "associated by page only (no line geometry)"
        return

    anchors.sort()

    for figure in figures:
        candidates = [
            (page, top, label)
            for page, top, label in anchors
            if page < figure.page or (page == figure.page and top <= figure.top + 2.0)
        ]
        if candidates:
            figure.question_no = candidates[-1][2]
        else:
            # Above the first question: it belongs to whatever starts the page.
            same_page = [a for a in anchors if a[0] == figure.page]
            if same_page:
                figure.question_no = same_page[0][2]
                figure.note = "figure printed above its question label"


# --------------------------------------------------------------------------
# Cropping
# --------------------------------------------------------------------------


def crop_figures(pdf_path: str, figures: list[Figure], out_dir: Path,
                 page_images=None, dpi: int = CROP_DPI,
                 page_sizes: dict[int, tuple[float, float]] | None = None) -> None:
    """Render each figure to a PNG.  Failures are recorded, never raised."""
    if not figures:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    pages = page_images

    if pages is None:
        try:
            from .ocr import render_pages

            pages = render_pages(pdf_path, dpi)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not rasterise for figure crops: %s", exc)
            for figure in figures:
                figure.note = f"crop unavailable: {exc}"
            return

    stem = Path(pdf_path).stem

    for index, figure in enumerate(figures, start=1):
        page_index = figure.page - 1
        if page_index < 0 or page_index >= len(pages):
            figure.note = "crop skipped: page out of range"
            continue

        # Check the region before padding: padding must not rescue a
        # degenerate box into a crop of blank page.
        if figure.width <= 0 or figure.height <= 0:
            figure.note = "crop skipped: empty region"
            continue

        image = pages[page_index]
        px_w, px_h = image.size

        if page_sizes and figure.page in page_sizes:
            pw, ph = page_sizes[figure.page]
        else:
            pw, ph = px_w * 72.0 / dpi, px_h * 72.0 / dpi
        if not pw or not ph:
            figure.note = "crop skipped: unknown page size"
            continue

        sx, sy = px_w / pw, px_h / ph
        box = (
            max(0, int((figure.x0 - CROP_PADDING) * sx)),
            max(0, int((figure.top - CROP_PADDING) * sy)),
            min(px_w, int((figure.x1 + CROP_PADDING) * sx)),
            min(px_h, int((figure.bottom + CROP_PADDING) * sy)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            figure.note = "crop skipped: empty region"
            continue

        try:
            crop = image.crop(box)
            path = out_dir / f"{stem}_p{figure.page}_f{index}.png"
            crop.save(path, format="PNG")
            figure.image_path = str(path)
            figure.width_px, figure.height_px = crop.size
        except Exception as exc:  # noqa: BLE001 - unsupported mode, disk, etc.
            logger.warning("Figure crop failed: %s", exc)
            figure.note = f"crop failed: {exc}"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def detect_figures(pdf, *, page_images=None, lines=None,
                   use_ink_detector: bool = False) -> list[Figure]:
    """Find every figure in an open ``pdfplumber`` document."""
    found: list[Figure] = []
    lines = lines or []

    for page_no, page in enumerate(pdf.pages, start=1):
        page_area = float(page.width) * float(page.height)

        found.extend(_image_figures(page, page_no, page_area))
        found.extend(_vector_figures(page, page_no))

        if use_ink_detector and page_images is not None:
            index = page_no - 1
            if 0 <= index < len(page_images):
                word_boxes = [
                    (ln.x0, ln.top, ln.x0 + _estimate_width(ln), ln.bottom)
                    for ln in lines
                    if ln.page == page_no
                    and ln.x0 is not None
                    and ln.top is not None
                    and ln.bottom is not None
                ]
                if not word_boxes:
                    # With nothing to mask, every glyph on the page reads as
                    # an unexplained region, so the detector is skipped.
                    continue
                found.extend(
                    _ink_figures(page_images[index], page_no, word_boxes,
                                 float(page.width), float(page.height))
                )

    # Drop anything too small to be a real figure.
    kept: list[Figure] = []
    for figure in found:
        page = pdf.pages[figure.page - 1]
        page_area = float(page.width) * float(page.height)
        ratio = (figure.width * figure.height) / page_area if page_area else 0.0
        if ratio < MIN_FIGURE_AREA_RATIO:
            continue
        figure.area_ratio = ratio
        kept.append(figure)

    kept.sort(key=lambda f: (f.page, f.top, f.x0))
    return kept


def _estimate_width(line) -> float:
    """Line width: measured when the extractor gave a right edge, else estimated."""
    x1 = getattr(line, "x1", None)
    if x1 is not None and line.x0 is not None and x1 > line.x0:
        return x1 - line.x0

    height = (line.bottom - line.top) if (line.bottom and line.top) else 10.0
    return max(10.0, len(line.text) * height * 0.52)
