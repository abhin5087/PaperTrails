"""Geometry primitives for figure regions.

Kept separate from detection so the merge rules can be reasoned about and
tested without rendering a PDF.  All boxes are ``(x0, top, x1, bottom)`` in
PDF points with ``top`` measured downwards from the top of the page, which is
pdfplumber's convention and the one used throughout the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Overlap:
    """How two boxes relate.  Several measures, because no single one is enough."""

    intersection: float
    iou: float
    #: Intersection over the *smaller* box.  A small crop sitting wholly
    #: inside a large one has low IoU but containment of 1.0, and is still a
    #: duplicate - which is why IoU alone cannot be the test.
    containment: float
    #: Smallest gap between the two boxes on each axis; 0 when they overlap.
    vertical_gap: float
    horizontal_gap: float
    #: Share of the narrower box's width that lies within the other's columns.
    horizontal_alignment: float


def area(box: Box) -> float:
    x0, top, x1, bottom = box
    return max(0.0, x1 - x0) * max(0.0, bottom - top)


def width(box: Box) -> float:
    return max(0.0, box[2] - box[0])


def height(box: Box) -> float:
    return max(0.0, box[3] - box[1])


def is_valid(box: Box) -> bool:
    return width(box) > 0 and height(box) > 0


def union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def clamp(box: Box, page_width: float, page_height: float) -> Box:
    """Confine a box to the page.  Detection can run a little past the edge."""
    x0 = min(max(0.0, box[0]), page_width)
    x1 = min(max(0.0, box[2]), page_width)
    top = min(max(0.0, box[1]), page_height)
    bottom = min(max(0.0, box[3]), page_height)
    return (min(x0, x1), min(top, bottom), max(x0, x1), max(top, bottom))


def describe(a: Box, b: Box) -> Overlap:
    """Every relationship measure the merge rules need, computed once."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    intersection = max(0.0, ix) * max(0.0, iy)

    area_a, area_b = area(a), area(b)
    smaller = min(area_a, area_b)
    combined = area_a + area_b - intersection

    vertical_gap = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    horizontal_gap = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))

    narrow = min(width(a), width(b))
    shared_columns = max(0.0, ix)

    return Overlap(
        intersection=intersection,
        iou=(intersection / combined) if combined > 0 else 0.0,
        containment=(intersection / smaller) if smaller > 0 else 0.0,
        vertical_gap=vertical_gap,
        horizontal_gap=horizontal_gap,
        horizontal_alignment=(shared_columns / narrow) if narrow > 0 else 0.0,
    )


def touches_edges(box: Box, content: Box, tolerance: float = 2.0) -> list[str]:
    """Which edges of ``box`` the ``content`` reaches.

    Used to flag a crop that may have cut a diagram off.  Content touching an
    edge is evidence of clipping, not proof - a diagram can legitimately end
    exactly at its own boundary.
    """
    edges = []
    if content[1] - box[1] <= tolerance:
        edges.append("top")
    if box[3] - content[3] <= tolerance:
        edges.append("bottom")
    if content[0] - box[0] <= tolerance:
        edges.append("left")
    if box[2] - content[2] <= tolerance:
        edges.append("right")
    return edges
