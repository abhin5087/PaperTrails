"""Ink-region detection for scanned pages.

A scan holds no geometry, so a diagram has to be found in the pixels.  The
method is: mark genuinely dark pixels, erase everything the text layer
already explains, and treat what remains as drawing.

The previous implementation segmented the leftovers into horizontal *bands*.
That is what split one diagram into several overlapping crops, clipped graphs
at a band edge, and turned the shadowed strip along a page edge into its own
figure.  This module instead finds **connected components**: a diagram's
boxes, arrows and labels touch or nearly touch, so they form one component,
while a shadow along the binding forms another that can be judged on its own
merits.

Components are labelled on a coarse grid (a few points per cell) which both
denoises the scan and keeps the labelling cheap.  Bounds are then measured
from the *undilated* ink inside each component, so joining strokes together
does not inflate the reported region.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Pixels darker than this are ink.  A photocopy's background is light grey;
#: line art is near black.
INK_THRESHOLD = 140

#: Coarse grid cell size in PDF points.  Small enough to resolve a thin axis,
#: large enough that labelling a page is cheap.
CELL_POINTS = 3.0

#: Cells of dilation applied before labelling, to join the separate strokes
#: of one drawing.  5 cells ~ 15pt bridges the gaps left where the text layer
#: erased a diagram own labels.  Larger values start swallowing the
#: paragraphs around the figure, which trimming then has to undo.
DILATE_CELLS = 5

#: A component with fewer inked cells than this is speckle.
MIN_COMPONENT_CELLS = 12

#: Width of the strip along each page edge treated as the page's own margin,
#: where scanner shadow and the border line of a photocopy live.
EDGE_MARGIN_POINTS = 8.0

#: A row at the edge of a component is trimmed away as prose when the text
#: layer covers at least this much of it and it carries little ink of its own.
#: This is what stops a diagram's region from reaching up into the question
#: text printed above it.
TRIM_TEXT_SHARE = 0.5
TRIM_INK_SHARE = 0.3


@dataclass
class InkRegion:
    """One connected region of unexplained ink."""

    box: tuple[float, float, float, float]
    #: Share of the region's own area that is inked.
    density: float
    #: Share of the region covered by text-layer boxes.
    text_coverage: float

    cells: int
    #: Tight bounds of the ink itself, for clipping checks.
    content_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    #: Share covered by *prose* lines only - full sentences, not short
    #: labels.  A diagram annotated with IP addresses and axis ticks has high
    #: text coverage but almost no prose coverage, whereas a paragraph has
    #: both.  Judging on prose is what keeps a labelled diagram.
    prose_coverage: float = 0.0

    #: Share of the region's rows / columns that contain any ink.  These
    #: separate a drawing from a page artefact where density cannot: the dark
    #: border line down the edge of a photocopy fills every row but only a
    #: couple of columns, whereas a diagram's ink is spread over both axes.
    row_occupancy: float = 0.0
    col_occupancy: float = 0.0

    #: Share of the region's ink lying within a thin margin of a page edge.
    edge_ink: float = 0.0


@dataclass
class InkPage:
    """Everything the detector learned about one page."""

    page: int
    regions: list[InkRegion] = field(default_factory=list)
    #: Share of the page's ink that the text layer accounted for.
    mask_effectiveness: float = 0.0
    skipped: str | None = None

    #: The coarse ink grid and its scale, kept so the merge stage can ask
    #: whether the strip between two pieces actually contains ink.  That is
    #: the difference between one split diagram and two separate ones.
    grid: object | None = None
    cell_width: float = 0.0
    cell_height: float = 0.0

    def gap_ink_share(self, a, b) -> float | None:
        """Ink share of the strip separating two boxes, or ``None``."""
        if self.grid is None or not self.cell_width or not self.cell_height:
            return None

        # The strip lies between them on whichever axis they are apart.
        top = min(a[3], b[3])
        bottom = max(a[1], b[1])
        left = max(a[0], b[0])
        right = min(a[2], b[2])

        if bottom > top and right > left:
            box = (left, top, right, bottom)        # vertical gap
        else:
            left2 = min(a[2], b[2])
            right2 = max(a[0], b[0])
            top2 = max(a[1], b[1])
            bottom2 = min(a[3], b[3])
            if right2 > left2 and bottom2 > top2:
                box = (left2, top2, right2, bottom2)  # horizontal gap
            else:
                return None

        c0 = max(0, int(box[0] / self.cell_width))
        c1 = min(self.grid.shape[1], int(box[2] / self.cell_width) + 1)
        r0 = max(0, int(box[1] / self.cell_height))
        r1 = min(self.grid.shape[0], int(box[3] / self.cell_height) + 1)
        if c1 <= c0 or r1 <= r0:
            return None

        window = self.grid[r0:r1, c0:c1]
        return float(window.mean()) if window.size else None


def _dilate(grid, cells: int):
    """Grow a boolean grid by ``cells`` in all directions (numpy shifts)."""
    import numpy as np

    out = grid.copy()
    for _ in range(cells):
        padded = np.zeros_like(out)
        padded[1:, :] |= out[:-1, :]
        padded[:-1, :] |= out[1:, :]
        padded[:, 1:] |= out[:, :-1]
        padded[:, :-1] |= out[:, 1:]
        out = out | padded
    return out


def _label_components(grid) -> tuple[list[list[tuple[int, int]]], int]:
    """Label 8-connected components with a two-pass union-find.

    Implemented directly rather than pulling in scipy: the grid is coarse, so
    a plain Python pass is fast, and it keeps the dependency list short.
    """
    import numpy as np

    rows, cols = grid.shape
    labels = np.zeros((rows, cols), dtype=np.int32)
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unite(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    next_label = 1
    inked = np.argwhere(grid)

    for r, c in inked:
        r, c = int(r), int(c)
        neighbours = []
        for dr, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and labels[nr, nc]:
                neighbours.append(int(labels[nr, nc]))

        if not neighbours:
            labels[r, c] = next_label
            parent[next_label] = next_label
            next_label += 1
        else:
            smallest = min(neighbours)
            labels[r, c] = smallest
            for other in neighbours:
                unite(smallest, other)

    groups: dict[int, list[tuple[int, int]]] = {}
    for r, c in inked:
        r, c = int(r), int(c)
        root = find(int(labels[r, c]))
        groups.setdefault(root, []).append((r, c))

    # Deterministic order: top-most, then left-most.
    ordered = sorted(groups.values(), key=lambda cs: (min(c[0] for c in cs),
                                                      min(c[1] for c in cs)))
    return ordered, len(ordered)


def find_ink_regions(
    image,
    page_no: int,
    text_boxes: list[tuple[float, float, float, float]],
    page_width: float,
    page_height: float,
    *,
    min_mask_effectiveness: float = 0.0,
    prose_boxes: list[tuple[float, float, float, float]] | None = None,
) -> InkPage:
    """Find connected regions of ink the text layer does not explain."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a hard dependency
        return InkPage(page=page_no, skipped="numpy unavailable")

    result = InkPage(page=page_no)

    grey = image.convert("L")
    px_w, px_h = grey.size
    if not px_w or not px_h or page_width <= 0 or page_height <= 0:
        result.skipped = "page has no usable dimensions"
        return result

    data = np.asarray(grey, dtype=np.uint8)
    ink = data < INK_THRESHOLD
    total_ink = int(ink.sum())
    if total_ink == 0:
        result.skipped = "page carries no ink"
        return result

    sx, sy = px_w / page_width, px_h / page_height

    def _mask_from(boxes):
        mask = np.zeros_like(ink)
        for bx0, btop, bx1, bbottom in boxes:
            mx0 = max(0, int(bx0 * sx) - 2)
            mx1 = min(px_w, int(bx1 * sx) + 2)
            my0 = max(0, int(btop * sy) - 2)
            my1 = min(px_h, int(bbottom * sy) + 2)
            if mx1 > mx0 and my1 > my0:
                mask[my0:my1, mx0:mx1] = True
        return mask

    prose_mask = _mask_from(prose_boxes or [])

    text_mask = np.zeros_like(ink)
    for x0, top, x1, bottom in text_boxes:
        cx0 = max(0, int(x0 * sx) - 2)
        cx1 = min(px_w, int(x1 * sx) + 2)
        cy0 = max(0, int(top * sy) - 2)
        cy1 = min(px_h, int(bottom * sy) + 2)
        if cx1 > cx0 and cy1 > cy0:
            text_mask[cy0:cy1, cx0:cx1] = True

    unexplained = ink & ~text_mask
    result.mask_effectiveness = 1.0 - (int(unexplained.sum()) / total_ink)

    if result.mask_effectiveness < min_mask_effectiveness:
        result.skipped = (
            f"text layer explains only {result.mask_effectiveness * 100:.0f}% of the "
            "ink, so its coordinates do not match the page image"
        )
        return result

    # --- coarse grid ----------------------------------------------------
    cell_px_x = max(1, int(round(CELL_POINTS * sx)))
    cell_px_y = max(1, int(round(CELL_POINTS * sy)))
    rows = px_h // cell_px_y
    cols = px_w // cell_px_x
    if rows < 2 or cols < 2:
        result.skipped = "page too small to analyse"
        return result

    trimmed = unexplained[: rows * cell_px_y, : cols * cell_px_x]
    coarse = trimmed.reshape(rows, cell_px_y, cols, cell_px_x).any(axis=(1, 3))

    text_trimmed = text_mask[: rows * cell_px_y, : cols * cell_px_x]
    coarse_text = text_trimmed.reshape(rows, cell_px_y, cols, cell_px_x).any(axis=(1, 3))

    prose_trimmed = prose_mask[: rows * cell_px_y, : cols * cell_px_x]
    coarse_prose = prose_trimmed.reshape(rows, cell_px_y, cols,
                                         cell_px_x).any(axis=(1, 3))

    if not coarse.any():
        result.skipped = "no unexplained ink"
        return result

    joined = _dilate(coarse, DILATE_CELLS)
    components, _ = _label_components(joined)

    cell_w = cell_px_x / sx
    cell_h = cell_px_y / sy
    result.grid = coarse
    result.cell_width = cell_w
    result.cell_height = cell_h

    for cells in components:
        # Measure from the real ink, not from the dilated shape.
        own = [(r, c) for r, c in cells if coarse[r, c]]
        if len(own) < MIN_COMPONENT_CELLS:
            continue

        r0 = min(r for r, _ in own)
        r1 = max(r for r, _ in own)
        c0 = min(c for _, c in own)
        c1 = max(c for _, c in own)

        # Trim prose rows off the top and bottom.  A component can reach
        # into the text above or below it through a descender or a stray
        # mark; those rows belong to the question, not to the figure.
        own_rows: dict[int, int] = {}
        for r, _ in own:
            own_rows[r] = own_rows.get(r, 0) + 1

        row_span = c1 - c0 + 1
        while r0 < r1:
            text_share = int(coarse_text[r0, c0 : c1 + 1].sum()) / row_span
            ink_share = own_rows.get(r0, 0) / row_span
            if text_share >= TRIM_TEXT_SHARE and ink_share <= TRIM_INK_SHARE:
                r0 += 1
            else:
                break
        while r1 > r0:
            text_share = int(coarse_text[r1, c0 : c1 + 1].sum()) / row_span
            ink_share = own_rows.get(r1, 0) / row_span
            if text_share >= TRIM_TEXT_SHARE and ink_share <= TRIM_INK_SHARE:
                r1 -= 1
            else:
                break

        own = [(r, c) for r, c in own if r0 <= r <= r1]
        if len(own) < MIN_COMPONENT_CELLS:
            continue

        # Columns may have narrowed once prose rows were dropped.
        c0 = min(c for _, c in own)
        c1 = max(c for _, c in own)

        box = (c0 * cell_w, r0 * cell_h, (c1 + 1) * cell_w, (r1 + 1) * cell_h)
        n_rows = r1 - r0 + 1
        n_cols = c1 - c0 + 1
        span_cells = n_rows * n_cols
        density = len(own) / span_cells if span_cells else 0.0

        text_cells = int(coarse_text[r0 : r1 + 1, c0 : c1 + 1].sum())
        text_coverage = text_cells / span_cells if span_cells else 0.0

        prose_cells = int(coarse_prose[r0 : r1 + 1, c0 : c1 + 1].sum())
        prose_coverage = prose_cells / span_cells if span_cells else 0.0

        occupied_rows = len({r for r, _ in own})
        occupied_cols = len({c for _, c in own})

        margin_cols_left = EDGE_MARGIN_POINTS / cell_w
        margin_cols_right = (page_width - EDGE_MARGIN_POINTS) / cell_w
        margin_rows_top = EDGE_MARGIN_POINTS / cell_h
        margin_rows_bottom = (page_height - EDGE_MARGIN_POINTS) / cell_h
        edge_cells = sum(
            1
            for r, c in own
            if c <= margin_cols_left
            or c >= margin_cols_right
            or r <= margin_rows_top
            or r >= margin_rows_bottom
        )

        result.regions.append(
            InkRegion(
                box=box,
                density=density,
                text_coverage=text_coverage,
                prose_coverage=prose_coverage,
                cells=len(own),
                content_box=box,
                row_occupancy=occupied_rows / n_rows if n_rows else 0.0,
                col_occupancy=occupied_cols / n_cols if n_cols else 0.0,
                edge_ink=edge_cells / len(own) if own else 0.0,
            )
        )

    return result
