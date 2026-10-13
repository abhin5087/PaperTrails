"""Deduplicating and merging raw figure detections.

Several detectors can describe the same drawing, and one detector can emit
several pieces of it.  Both produce the same visible defect - the same diagram
cropped twice, overlapping - so both are resolved here, after detection and
before any crop is made.

The rules are deliberately several, because no single measure is sufficient:

* **IoU** catches two boxes that are roughly the same region.
* **Containment** (intersection over the *smaller* box) catches a small crop
  sitting wholly inside a large one, which IoU scores low.
* **Gap plus alignment** catches fragments of one figure stacked vertically or
  side by side with a blank strip between them.

Against that, two genuinely separate diagrams printed near each other must
stay separate.  The guard is an emptiness test: if joining two boxes creates a
region far larger than the two together, the space between them is blank and
they are not one figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import figure_geometry as geo

#: Overlap at which two boxes describe the same region.
MERGE_IOU = 0.30

#: Share of the smaller box inside the larger at which it is a duplicate.
MERGE_CONTAINMENT = 0.60

#: Largest gap (points) across which two pieces may still be one figure.
MERGE_GAP_POINTS = 18.0

#: How much of the narrower box must share columns (or rows) with the other
#: before a gap-based merge is allowed.
MERGE_ALIGNMENT = 0.45

#: If the union is more than this multiple of the parts' combined area, the
#: space between them is empty and they are separate diagrams.
MAX_UNION_INFLATION = 1.9

#: Ink share the strip between two pieces must carry before a gap-based merge
#: is believed.  A connecting line or a shared axis leaves ink there; two
#: independent diagrams leave the strip blank.
MIN_GAP_CONTINUITY = 0.02

#: Detector precedence: exact geometry beats a raster image, which beats a
#: region inferred from pixels.
DETECTOR_RANK = {"vector": 0, "image": 1, "ink": 2}


@dataclass
class MergeDecision:
    """Why two detections were or were not joined - kept for the debug trace."""

    a: tuple[float, float, float, float]
    b: tuple[float, float, float, float]
    merged: bool
    rule: str
    iou: float
    containment: float

    def to_dict(self) -> dict:
        return {
            "a": [round(v, 1) for v in self.a],
            "b": [round(v, 1) for v in self.b],
            "merged": self.merged,
            "rule": self.rule,
            "iou": round(self.iou, 3),
            "containment": round(self.containment, 3),
        }


@dataclass
class MergeResult:
    decisions: list[MergeDecision] = field(default_factory=list)


def _should_merge(a, b, gap_ink: float | None = None) -> tuple[bool, str]:
    """Decide whether two boxes describe one figure, and say which rule applied."""
    overlap = geo.describe(a, b)

    # Same region, or one effectively inside the other.
    if overlap.containment >= MERGE_CONTAINMENT:
        return True, f"containment={overlap.containment:.2f}"
    if overlap.iou >= MERGE_IOU:
        return True, f"iou={overlap.iou:.2f}"

    # Fragments of one drawing: close together and lined up.  The emptiness
    # guard keeps two separate diagrams apart.
    touching = (
        overlap.vertical_gap <= MERGE_GAP_POINTS
        and overlap.horizontal_gap <= MERGE_GAP_POINTS
    )
    if touching and overlap.horizontal_alignment >= MERGE_ALIGNMENT:
        combined = geo.area(a) + geo.area(b) - overlap.intersection
        inflation = geo.area(geo.union(a, b)) / combined if combined else float("inf")

        # When the pieces are actually apart, require ink in the strip
        # between them.  Without it they are two diagrams, not one.
        separated = max(overlap.vertical_gap, overlap.horizontal_gap) > 1.0
        if separated and gap_ink is not None and gap_ink < MIN_GAP_CONTINUITY:
            return False, f"separate: gap carries no ink ({gap_ink:.3f})"

        if inflation <= MAX_UNION_INFLATION:
            return True, (
                f"fragment gap={max(overlap.vertical_gap, overlap.horizontal_gap):.0f}pt "
                f"align={overlap.horizontal_alignment:.2f} inflation={inflation:.2f}"
            )
        return False, f"separate: union inflates {inflation:.2f}x"

    if overlap.intersection > 0:
        return False, (
            f"overlaps but distinct: iou={overlap.iou:.2f} "
            f"containment={overlap.containment:.2f}"
        )
    return False, "disjoint"


def merge_detections(figures: list, *, result: MergeResult | None = None,
                     continuity=None) -> list:
    """Collapse duplicate and fragmentary detections into final figures.

    Deterministic: detections are ordered by page, position and detector rank
    before merging, and merging repeats until nothing changes, so the same
    input always produces the same output.
    """
    if len(figures) < 2:
        return list(figures)

    ordered = sorted(
        figures,
        key=lambda f: (f.page, round(f.top, 2), round(f.x0, 2),
                       DETECTOR_RANK.get(f.kind, 9)),
    )

    changed = True
    while changed:
        changed = False
        output: list = []

        for figure in ordered:
            for index, kept in enumerate(output):
                if kept.page != figure.page:
                    continue

                gap_ink = (
                    continuity(figure.page, kept.bbox, figure.bbox)
                    if continuity is not None
                    else None
                )
                merge, rule = _should_merge(kept.bbox, figure.bbox, gap_ink)
                if result is not None:
                    result.decisions.append(
                        MergeDecision(
                            a=kept.bbox, b=figure.bbox, merged=merge, rule=rule,
                            iou=geo.describe(kept.bbox, figure.bbox).iou,
                            containment=geo.describe(kept.bbox,
                                                     figure.bbox).containment,
                        )
                    )
                if merge:
                    output[index] = _combine(kept, figure)
                    changed = True
                    break
            else:
                output.append(figure)

        ordered = sorted(
            output,
            key=lambda f: (f.page, round(f.top, 2), round(f.x0, 2),
                           DETECTOR_RANK.get(f.kind, 9)),
        )

    return ordered


def _combine(a, b):
    """Union two detections, keeping the better-quality metadata.

    The more precise detector names the result, but the other's geometry still
    contributes - a vector shape and the ink region around its labels describe
    one figure between them, and discarding either would lose part of it.
    """
    box = geo.union(a.bbox, b.bbox)

    primary, secondary = (
        (a, b)
        if DETECTOR_RANK.get(a.kind, 9) <= DETECTOR_RANK.get(b.kind, 9)
        else (b, a)
    )

    primary.x0, primary.top, primary.x1, primary.bottom = box
    primary.sources = sorted(set(primary.sources) | set(secondary.sources)
                             | {a.kind, b.kind})
    primary.caption = primary.caption or secondary.caption

    # Quality metrics: keep the stronger evidence available.
    for field_name in ("ink_density", "text_coverage"):
        own = getattr(primary, field_name, None)
        other = getattr(secondary, field_name, None)
        if own is None and other is not None:
            setattr(primary, field_name, other)

    return primary
