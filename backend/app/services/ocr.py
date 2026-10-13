"""Tesseract OCR for scanned exam papers.

A scan is run through several Tesseract page-segmentation modes because no
single mode handles every layout: ``--psm 6`` suits a dense single block,
``--psm 4`` copes with columns, ``--psm 3`` lets Tesseract decide.  Each run
becomes an independent extraction candidate carrying its own text, its own
word geometry and its own mean engine confidence, and the pipeline picks
between them on structural grounds rather than on raw confidence.

Word boxes are converted from render pixels into PDF points so that the
margin logic in :mod:`.questions` behaves identically for OCR output and for
a native text layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .questions import Line

logger = logging.getLogger(__name__)

DEFAULT_DPI = 300

#: Word-level confidence below which a token is treated as noise.
MIN_WORD_CONFIDENCE = 30.0


@dataclass(frozen=True)
class OcrConfig:
    """One Tesseract invocation."""

    name: str
    psm: int
    dpi: int = DEFAULT_DPI
    oem: int = 3

    @property
    def tesseract_config(self) -> str:
        return f"--oem {self.oem} --psm {self.psm}"


#: Tried in order; all of them become candidates.
OCR_CONFIGS: tuple[OcrConfig, ...] = (
    OcrConfig(name="psm6-block", psm=6),
    OcrConfig(name="psm4-column", psm=4),
    OcrConfig(name="psm3-auto", psm=3),
)


@dataclass
class OcrPage:
    """OCR result for one page."""

    page: int
    text: str
    lines: list[Line] = field(default_factory=list)
    mean_confidence: float = 0.0
    word_count: int = 0


@dataclass
class OcrResult:
    """OCR result for a whole document under one configuration."""

    config: OcrConfig
    pages: list[OcrPage] = field(default_factory=list)
    available: bool = True
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def first_page_text(self) -> str:
        return self.pages[0].text if self.pages else ""

    @property
    def lines(self) -> list[Line]:
        out: list[Line] = []
        for page in self.pages:
            out.extend(page.lines)
        return out

    @property
    def mean_confidence(self) -> float:
        scored = [p.mean_confidence for p in self.pages if p.word_count]
        return sum(scored) / len(scored) if scored else 0.0

    @property
    def word_count(self) -> int:
        return sum(p.word_count for p in self.pages)


class OcrUnavailable(RuntimeError):
    """Raised when no OCR engine is installed."""


def tesseract_version() -> str | None:
    """The installed Tesseract version, or ``None`` when absent."""
    try:
        import pytesseract
    except ImportError:
        return None

    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:  # noqa: BLE001 - binary missing or unusable
        return None


def ocr_available() -> bool:
    return tesseract_version() is not None


def render_pages(pdf_path: str, dpi: int = DEFAULT_DPI):
    """Rasterise a PDF, preferring pdf2image and falling back to pypdfium2."""
    try:
        from pdf2image import convert_from_path

        return convert_from_path(pdf_path, dpi=dpi)
    except Exception as exc:  # noqa: BLE001 - poppler missing or broken
        logger.debug("pdf2image failed (%s); trying pypdfium2", exc)

    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(pdf_path)
        scale = dpi / 72.0
        return [page.render(scale=scale).to_pil() for page in document]
    except Exception as exc:  # noqa: BLE001
        raise OcrUnavailable(f"Could not rasterise {pdf_path}: {exc}") from exc


def _words_to_lines(data: dict, page_no: int, dpi: int) -> tuple[list[Line], float, int]:
    """Group Tesseract word boxes into lines with PDF-point geometry."""
    scale = 72.0 / dpi
    buckets: dict[tuple[int, int, int], list[dict]] = {}
    confidences: list[float] = []

    count = len(data.get("text", []))
    for i in range(count):
        word = (data["text"][i] or "").strip()
        if not word:
            continue

        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0

        if conf >= 0:
            confidences.append(conf)
        if conf >= 0 and conf < MIN_WORD_CONFIDENCE:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        buckets.setdefault(key, []).append(
            {
                "text": word,
                "left": data["left"][i],
                "top": data["top"][i],
                "height": data["height"][i],
                "width": data["width"][i],
            }
        )

    lines: list[Line] = []
    for index, key in enumerate(sorted(buckets)):
        words = sorted(buckets[key], key=lambda w: w["left"])
        text = " ".join(w["text"] for w in words)
        if not text.strip():
            continue
        left = min(w["left"] for w in words)
        right = max(w["left"] + w["width"] for w in words)
        top = min(w["top"] for w in words)
        bottom = max(w["top"] + w["height"] for w in words)
        lines.append(
            Line(
                text=text,
                page=page_no,
                index=index,
                x0=left * scale,
                top=top * scale,
                bottom=bottom * scale,
                # The measured right edge matters: without it the text mask
                # used by the ink figure detector under-covers each line and
                # ordinary text is reported as an unexplained diagram.
                x1=right * scale,
            )
        )

    # Reading order: top to bottom, then left to right.
    lines.sort(key=lambda ln: (round(ln.top or 0, 1), ln.x0 or 0))
    for position, line in enumerate(lines):
        line.index = position

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return lines, mean_conf, len(confidences)


def run_ocr(pdf_path: str, config: OcrConfig, images=None) -> OcrResult:
    """Run one Tesseract configuration over a document."""
    try:
        import pytesseract
    except ImportError as exc:
        return OcrResult(config=config, available=False,
                         error=f"pytesseract is not installed: {exc}")

    if not ocr_available():
        return OcrResult(config=config, available=False,
                         error="Tesseract binary not found on PATH")

    try:
        pages = images if images is not None else render_pages(pdf_path, config.dpi)
    except OcrUnavailable as exc:
        return OcrResult(config=config, available=False, error=str(exc))

    result = OcrResult(config=config)

    for page_no, image in enumerate(pages, start=1):
        try:
            data = pytesseract.image_to_data(
                image,
                config=config.tesseract_config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill the run
            logger.warning("OCR failed on page %s (%s): %s", page_no, config.name, exc)
            result.pages.append(OcrPage(page=page_no, text="", mean_confidence=0.0))
            continue

        lines, mean_conf, word_count = _words_to_lines(data, page_no, config.dpi)
        result.pages.append(
            OcrPage(
                page=page_no,
                text="\n".join(ln.text for ln in lines),
                lines=lines,
                mean_confidence=mean_conf,
                word_count=word_count,
            )
        )

    return result


def run_all_configs(
    pdf_path: str,
    configs: tuple[OcrConfig, ...] = OCR_CONFIGS,
    dpi: int = DEFAULT_DPI,
) -> list[OcrResult]:
    """Run every configuration, rasterising the document only once."""
    if not ocr_available():
        return [
            OcrResult(config=c, available=False,
                      error="Tesseract binary not found on PATH")
            for c in configs
        ]

    try:
        images = render_pages(pdf_path, dpi)
    except OcrUnavailable as exc:
        return [OcrResult(config=c, available=False, error=str(exc)) for c in configs]

    results = []
    for config in configs:
        # All configs share the render, so they must share its DPI.
        results.append(run_ocr(pdf_path, OcrConfig(config.name, config.psm, dpi,
                                                   config.oem), images=images))
    return results
