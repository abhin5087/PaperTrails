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

from . import figure_geometry

logger = logging.getLogger(__name__)

#: An image this large relative to the page is the page scan, not a figure.
FULL_PAGE_IMAGE_RATIO = 0.65

#: Smallest figure worth reporting, as a fraction of page area.
MIN_FIGURE_AREA_RATIO = 0.01

#: Largest an *ink* region may be before it is the page rather than a
#: figure.  A noisy scan leaves dark pixels between every line, which can
#: merge into one band spanning the sheet; reporting that as a diagram is
#: wrong, and letting it through would mask the whole page as figure content.
MAX_INK_AREA_RATIO = 0.5

#: An ink region taller than this share of the page is likewise the page.
MAX_INK_HEIGHT_RATIO = 0.8

#: The ink detector works by removing everything the text layer explains
#: and treating the remainder as diagram.  That only holds when the text
#: boxes actually line up with the rendered page - some scanned PDFs carry
#: a text layer whose coordinates do not match the image at all.  Below
#: this share of ink explained, the detector cannot tell a diagram from a
#: paragraph, so it declines instead of reporting text as figures.
MIN_MASK_EFFECTIVENESS = 0.05

#: A real diagram covers a reasonable share of its own bounding box with
#: ink; a shadow over empty paper does not.  Kept low because a line graph on
#: a large axis is genuinely sparse.
MIN_REGION_INK_DENSITY = 0.02

#: A figure's ink is spread over both axes.  A page border fills every row
#: and two columns; a scanner shadow along the top fills every column and two
#: rows.  Neither passes this.
MIN_INK_OCCUPANCY = 0.25

#: Share of a region's own ink that may lie in the page margin.  Evidence,
#: not a veto: a genuine figure near the edge keeps most of its ink inside.
MAX_EDGE_INK = 0.30

#: A figure has width as well as height.
MIN_INK_WIDTH_PT = 40.0

#: A figure has vertical extent.  A thin wide strip is a page edge, a rule
#: or a shadow along the binding, never a diagram.  Expressed in points so
#: it does not vary with page size.
MIN_INK_HEIGHT_PT = 24.0

#: Body-text lines covering more than this share of a region mean it is a
#: paragraph rather than a diagram.  Short label lines are excluded from the
#: measure, so a heavily annotated figure is not mistaken for prose.
MAX_PROSE_COVERAGE = 0.25

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

    #: Every detector that contributed geometry to this figure.
    sources: list[str] = field(default_factory=list)

    #: Quality evidence from the ink detector, when it was involved.
    ink_density: float | None = None
    text_coverage: float | None = None

    #: Edges where the figure's own content reaches the boundary, which may
    #: mean the drawing continues past it.
    clipped_edges: list[str] = field(default_factory=list)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [self.kind]

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "kind": self.kind,
            "sources": list(self.sources),
            "ink_density": (round(self.ink_density, 3)
                            if self.ink_density is not None else None),
            "text_coverage": (round(self.text_coverage, 3)
                              if self.text_coverage is not None else None),
            "clipped_edges": list(self.clipped_edges),
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


def _ink_figures(image, page_no: int, word_boxes, page_width: float,
                 page_height: float, *, rejections=None, prose_boxes=None):
    """Connected regions of ink the text layer does not explain.

    Delegates to :mod:`.figure_ink`, which labels connected components rather
    than slicing the page into horizontal bands.  Band slicing was what split
    one diagram into several overlapping crops and cut graphs off at a band
    edge; a component follows the drawing itself.
    """
    from . import figure_ink

    page = figure_ink.find_ink_regions(
        image, page_no, word_boxes, page_width, page_height,
        min_mask_effectiveness=MIN_MASK_EFFECTIVENESS,
        prose_boxes=prose_boxes,
    )

    if page.skipped:
        if rejections is not None:
            rejections.append((page_no, None, "ink", page.skipped))
        return [], page

    out = []
    for region in page.regions:
        reason = _reject_ink_region(region, page_width, page_height)
        if reason:
            if rejections is not None:
                rejections.append((page_no, region.box, "ink", reason))
            continue

        out.append(
            Figure(
                page=page_no,
                x0=region.box[0], top=region.box[1],
                x1=region.box[2], bottom=region.box[3],
                kind="ink",
                detector="ink:connected-component",
                ink_density=region.density,
                text_coverage=region.text_coverage,
                note="approximate region: isolated from the page image, so it "
                     "may include nearby text or omit part of the figure",
            )
        )

    return out, page


def _reject_ink_region(region, page_width: float, page_height: float) -> str | None:
    """Why an ink region is not a figure, or ``None`` if it is plausible.

    The tests are combined rather than applied as independent ratios, because
    no single one separates a real diagram from a scanning artefact: the
    congestion graph on the supplied paper has *lower* ink density than the
    blank, creased strip beside it.
    """
    x0, top, x1, bottom = region.box
    width, height = x1 - x0, bottom - top

    if width <= 0 or height <= 0:
        return "zero-area region"
    if height < MIN_INK_HEIGHT_PT:
        return f"too short ({height:.0f}pt < {MIN_INK_HEIGHT_PT:.0f}pt)"
    if width < MIN_INK_WIDTH_PT:
        return f"too narrow ({width:.0f}pt < {MIN_INK_WIDTH_PT:.0f}pt)"

    page_area = page_width * page_height
    if page_area and (width * height) / page_area > MAX_INK_AREA_RATIO:
        return "covers too much of the page to be a figure"
    if page_height and height / page_height > MAX_INK_HEIGHT_RATIO:
        return "spans nearly the whole page height"

    # Ink spread, not ink quantity.  The dark border line down the edge of a
    # photocopy fills every row but only a couple of columns.
    if region.row_occupancy < MIN_INK_OCCUPANCY:
        return f"ink confined to {region.row_occupancy:.0%} of its rows"
    if region.col_occupancy < MIN_INK_OCCUPANCY:
        return f"ink confined to {region.col_occupancy:.0%} of its columns"

    # Most of the ink sitting in the page margin is scanner shadow or the
    # page border, not a drawing.  This is evidence, not an absolute rule: a
    # real figure near the edge still has most of its ink inside the page.
    if region.edge_ink > MAX_EDGE_INK:
        return f"{region.edge_ink:.0%} of its ink lies in the page margin"

    if region.density < MIN_REGION_INK_DENSITY:
        return f"too faint (density {region.density:.3f})"
    # Judged on prose, not on all text: a diagram covered in IP addresses
    # and axis ticks is still a diagram.
    if region.prose_coverage > MAX_PROSE_COVERAGE:
        return f"mostly prose ({region.prose_coverage:.0%} covered by body text)"

    return None


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


def drop_page_furniture(figures: list[Figure], questions,
                        trace: "FigureTrace | None" = None) -> list[Figure]:
    """Remove regions that are part of the page, not of any question.

    The block at the top of an exam paper - the logo and the ruled
    Programme / Course Code / Max Marks table - is a genuine ruled region, so
    a detector is right to find it.  It still is not a figure belonging to a
    question.  The test is structural rather than a size ratio: anything
    lying entirely *before the first question in reading order* is the
    paper's masthead.

    A region after the last question is kept: a diagram can legitimately be
    the final thing printed on a paper.
    """
    if not figures or not questions:
        return list(figures)

    anchored = [q for q in questions if q.top is not None]
    if not anchored:
        return list(figures)

    first = min(anchored, key=lambda q: (q.page, q.top))

    kept: list[Figure] = []
    for figure in figures:
        before_first = figure.page < first.page or (
            figure.page == first.page and figure.bottom <= first.top
        )
        if before_first:
            if trace is not None:
                trace.rejected.append({
                    "page": figure.page,
                    "bbox": [round(v, 1) for v in figure.bbox],
                    "detector": figure.detector,
                    "reason": "page furniture: lies above the first question",
                })
            logger.debug("Dropping page furniture on page %s: %s",
                         figure.page, figure.bbox)
            continue
        kept.append(figure)

    return kept


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


@dataclass
class FigureTrace:
    """Everything each stage decided, for debugging and regression evidence.

    Not part of any API response: the pipeline fills it only when a caller
    asks, and the result is written to the JSON sidecar or a test artefact.
    """

    raw: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    merges: list[dict] = field(default_factory=list)
    final: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "raw": list(self.raw),
            "rejected": list(self.rejected),
            "merges": list(self.merges),
            "final": list(self.final),
        }


def detect_figures(pdf, *, page_images=None, lines=None,
                   use_ink_detector: bool = False,
                   trace: "FigureTrace | None" = None) -> list[Figure]:
    """Find every figure in an open ``pdfplumber`` document.

    Runs as explicit stages, in this order, because each depends on the last:

    1. **detect** - every detector proposes regions independently;
    2. **validate** - implausible regions are dropped, with a reason recorded;
    3. **merge** - duplicates and fragments are consolidated;
    4. **grow** - each figure takes in its own labels;
    5. **merge again** - growth can make two figures overlap;
    6. **caption and clipping** - describe the result honestly.

    Crops are deliberately *not* made here.  They are cut from the finalised
    geometry by :func:`crop_figures`, so no crop is ever produced from a
    region that later merged or was rejected.
    """
    from . import figure_merge

    lines = lines or []
    found: list[Figure] = []
    rejections: list[tuple] = []
    ink_pages: dict[int, object] = {}

    for page_no, page in enumerate(pdf.pages, start=1):
        page_width, page_height = float(page.width), float(page.height)
        page_area = page_width * page_height

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
                prose_boxes = [
                    (ln.x0, ln.top, ln.x0 + _estimate_width(ln), ln.bottom)
                    for ln in lines
                    if ln.page == page_no
                    and ln.x0 is not None
                    and ln.top is not None
                    and ln.bottom is not None
                    and len(ln.text.strip()) > MAX_LABEL_CHARS
                ]
                if word_boxes:
                    ink, ink_page = _ink_figures(
                        page_images[index], page_no, word_boxes,
                        page_width, page_height, rejections=rejections,
                        prose_boxes=prose_boxes,
                    )
                    found.extend(ink)
                    ink_pages[page_no] = ink_page
                else:
                    # With nothing to mask, every glyph reads as a diagram.
                    rejections.append(
                        (page_no, None, "ink",
                         "no text boxes on this page to mask against")
                    )

    if trace is not None:
        trace.raw = [
            {"page": f.page, "detector": f.detector, "kind": f.kind,
             "bbox": [round(v, 1) for v in f.bbox]}
            for f in found
        ]

    # ---- stage 2: validate -------------------------------------------
    kept: list[Figure] = []
    for figure in found:
        page = pdf.pages[figure.page - 1]
        page_width, page_height = float(page.width), float(page.height)
        page_area = page_width * page_height

        box = figure_geometry.clamp(figure.bbox, page_width, page_height)
        figure.x0, figure.top, figure.x1, figure.bottom = box

        if not figure_geometry.is_valid(box):
            rejections.append((figure.page, box, figure.detector, "empty after clamping"))
            continue

        ratio = figure_geometry.area(box) / page_area if page_area else 0.0
        if ratio < MIN_FIGURE_AREA_RATIO:
            rejections.append(
                (figure.page, box, figure.detector,
                 f"below the minimum figure area ({ratio:.4f})")
            )
            continue

        figure.area_ratio = ratio
        kept.append(figure)

    # ---- stage 3: merge duplicates and fragments ----------------------
    def continuity(page_no, a, b):
        ink_page = ink_pages.get(page_no)
        return ink_page.gap_ink_share(a, b) if ink_page is not None else None

    merge_result = figure_merge.MergeResult()
    merged = figure_merge.merge_detections(
        kept, result=merge_result, continuity=continuity
    )

    # ---- stage 4: take in each figure's own labels --------------------
    grow_to_labels(merged, lines)

    # ---- stage 5: growth can create fresh overlaps --------------------
    merged = figure_merge.merge_detections(
        merged, result=merge_result, continuity=continuity
    )

    # ---- stage 6: describe honestly -----------------------------------
    for figure in merged:
        page = pdf.pages[figure.page - 1]
        box = figure_geometry.clamp(figure.bbox, float(page.width), float(page.height))
        figure.x0, figure.top, figure.x1, figure.bottom = box
        page_area = float(page.width) * float(page.height)
        figure.area_ratio = (figure_geometry.area(box) / page_area) if page_area else 0.0

    attach_captions(merged, lines)
    _flag_clipping(merged, ink_pages)

    merged.sort(key=lambda f: (f.page, f.top, f.x0))

    if trace is not None:
        trace.rejected = [
            {"page": pg, "bbox": ([round(v, 1) for v in bx] if bx else None),
             "detector": det, "reason": why}
            for pg, bx, det, why in rejections
        ]
        trace.merges = [d.to_dict() for d in merge_result.decisions]
        trace.final = [f.to_dict() for f in merged]

    return merged


def _flag_clipping(figures: list[Figure], ink_pages: dict) -> None:
    """Note where a figure's content reaches its own boundary.

    Recorded rather than acted on: content touching an edge *may* mean the
    drawing continues past it, but a diagram is also allowed to end exactly
    at its own edge, so expanding every such figure would swallow the page.
    """
    for figure in figures:
        ink_page = ink_pages.get(figure.page)
        if ink_page is None or getattr(ink_page, "grid", None) is None:
            continue

        probe = 4.0
        edges = []
        for edge, strip in (
            ("top", (figure.x0, figure.top - probe, figure.x1, figure.top)),
            ("bottom", (figure.x0, figure.bottom, figure.x1, figure.bottom + probe)),
            ("left", (figure.x0 - probe, figure.top, figure.x0, figure.bottom)),
            ("right", (figure.x1, figure.top, figure.x1 + probe, figure.bottom)),
        ):
            share = ink_page.gap_ink_share(
                (strip[0], strip[1], strip[2], strip[3]),
                (strip[0], strip[1], strip[2], strip[3]),
            )
            if share is not None and share > 0.05:
                edges.append(edge)

        if edges:
            figure.clipped_edges = edges
            extra = "content continues past the " + ", ".join(edges) + " edge"
            figure.note = f"{figure.note}; {extra}" if figure.note else extra


def _estimate_width(line) -> float:
    """Line width: measured when the extractor gave a right edge, else estimated."""
    x1 = getattr(line, "x1", None)
    if x1 is not None and line.x0 is not None and x1 > line.x0:
        return x1 - line.x0

    height = (line.bottom - line.top) if (line.bottom and line.top) else 10.0
    return max(10.0, len(line.text) * height * 0.52)
