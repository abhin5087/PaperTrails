"""Synthetic stand-ins for the two golden regression papers.

The real BHUM103L / BCSE308L PDFs are not redistributable with the repo, so
the regression suite prefers real files dropped into ``tests/fixtures/pdfs``
and falls back to these generators.  They are built to reproduce the
*failure modes* of the originals rather than their exact pixels:

``bhum103l``
    Image-only (no text layer at all), so the native text extractor returns
    nothing and the OCR path has to carry the header as well as the body.
    Marks are printed as ``5+5`` style sums whose ``+`` OCR tends to lose.

``bcse308l``
    Thirteen questions interleaved with vector network diagrams containing
    IP addresses and a congestion-window graph - the material that used to
    be misread as extra question labels.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4

# Rasterisation DPI for the "scanned" fixture.  High enough that Tesseract
# reads it reliably, low enough that it still behaves like a scan.
SCAN_DPI = 200


# --------------------------------------------------------------------------
# Expected values - the regression suite imports these as its golden data.
# --------------------------------------------------------------------------

BHUM103L_HEADER = {
    "course_code": "BHUM103L",
    "course_name": "Microeconomics",
    "exam_type": "Continuous Assessment Test-1",
    "semester": "Winter Semester",
    "academic_year": "2024-2025",
    "max_marks": 50,
    "duration": "90 Minutes",
    "exam_date": "16-02-2024",
}

# (question number, printed marks text, resolved total)
BHUM103L_QUESTIONS = [
    ("1", "10", 10),
    ("2", "5+5", 10),
    ("3", "7+3", 10),
    ("4", "2+8", 10),
    ("5", "7+3", 10),
]

BCSE308L_HEADER = {
    "course_code": "BCSE308L",
    "course_name": "COMPUTER NETWORKS",
    "exam_type": "Final Assessment Test",
    "max_marks": 100,
    "duration": "3 Hours",
}

# Q1-Q6 carry 5 marks, Q7-Q13 carry 10.
BCSE308L_QUESTIONS = [(str(n), 5 if n <= 6 else 10) for n in range(1, 14)]


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


class _Writer:
    """Minimal flowing-text cursor over a reportlab canvas."""

    def __init__(self, c: canvas.Canvas, top: float = PAGE_H - 25 * mm):
        self.c = c
        self.y = top

    def line(self, text: str, font: str = "Helvetica", size: int = 11,
             x: float = 20 * mm, gap: float = 5.5 * mm) -> None:
        self._ensure(gap)
        self.c.setFont(font, size)
        self.c.drawString(x, self.y, text)
        self.y -= gap

    def centred(self, text: str, font: str = "Helvetica-Bold", size: int = 12,
                gap: float = 6 * mm) -> None:
        self._ensure(gap)
        self.c.setFont(font, size)
        self.c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= gap

    def paragraph(self, text: str, x: float = 20 * mm, width: int = 88) -> None:
        for chunk in _wrap(text, width):
            self.line(chunk, x=x, gap=5 * mm)

    def space(self, amount: float = 4 * mm) -> None:
        self.y -= amount

    def _ensure(self, needed: float) -> None:
        if self.y - needed < 20 * mm:
            self.c.showPage()
            self.y = PAGE_H - 25 * mm

    def reserve(self, needed: float) -> None:
        """Force a page break when ``needed`` vertical space is unavailable."""
        if self.y - needed < 20 * mm:
            self.c.showPage()
            self.y = PAGE_H - 25 * mm


def _draw_topology(c: canvas.Canvas, w: _Writer, height: float = 48 * mm) -> None:
    """A small router topology with IP labels - the classic false-positive source."""
    w.reserve(height)
    top = w.y
    base = top - height + 8 * mm

    c.setLineWidth(1)
    boxes = [(28 * mm, "R1", "10.0.0.1"), (80 * mm, "R2", "16.0.0.1"),
             (132 * mm, "R3", "192.168.1.1")]
    for x, name, ip in boxes:
        c.rect(x, base + 14 * mm, 26 * mm, 14 * mm)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x + 13 * mm, base + 20 * mm, name)
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + 13 * mm, base + 10 * mm, ip)

    for x0, x1 in ((54 * mm, 80 * mm), (106 * mm, 132 * mm)):
        c.line(x0, base + 21 * mm, x1, base + 21 * mm)

    c.setFont("Helvetica", 7)
    c.drawCentredString(67 * mm, base + 23 * mm, "255.255.255.0")
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(PAGE_W / 2, base + 2 * mm, "Figure 1: Sample network topology")
    w.y = base - 3 * mm


def _draw_congestion_graph(c: canvas.Canvas, w: _Writer, height: float = 52 * mm) -> None:
    """Congestion-window graph: axis tick numbers must not become questions."""
    w.reserve(height)
    top = w.y
    base = top - height + 10 * mm
    ox, oy = 40 * mm, base + 8 * mm
    gw, gh = 95 * mm, 32 * mm

    c.setLineWidth(1)
    c.line(ox, oy, ox + gw, oy)
    c.line(ox, oy, ox, oy + gh)

    # Sawtooth congestion window.
    pts = [(0, 0), (18, 26), (19, 13), (36, 28), (37, 14), (55, 30), (56, 15), (75, 31)]
    c.setLineWidth(1.2)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        c.line(ox + x0 * mm, oy + y0 * mm, ox + x1 * mm, oy + y1 * mm)

    c.setFont("Helvetica", 7)
    for i in range(1, 9):
        x = ox + i * 11 * mm
        c.line(x, oy, x, oy - 1.5 * mm)
        c.drawCentredString(x, oy - 5 * mm, str(i))
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(ox + gw / 2, base + 1 * mm,
                        "Figure 2: Congestion window vs transmission round")
    w.y = base - 3 * mm


# --------------------------------------------------------------------------
# BHUM103L - scanned Microeconomics CAT-1
# --------------------------------------------------------------------------

_BHUM_BODIES = {
    "1": "Define the law of demand and explain, with a suitable diagram, why the "
         "demand curve for a normal good slopes downward.",
    "2": "Distinguish between a movement along the demand curve and a shift of the "
         "demand curve. Give one real world example of each case.",
    "3": "A consumer spends her entire income on two goods. Derive the budget line "
         "and explain how it responds to a fall in the price of one good.",
    "4": "State the law of diminishing marginal utility. Explain how the equi-marginal "
         "principle guides a rational consumer towards equilibrium.",
    "5": "Explain the concept of price elasticity of demand. Discuss how elasticity "
         "influences the total revenue of a seller.",
}

_BHUM_SUBPARTS = {
    "2": [("a", "Explain the distinction using a clearly labelled diagram."),
          ("b", "Give one real world example for each of the two cases.")],
    "3": [("a", "Derive the budget line for the two good case."),
          ("b", "Explain the effect of a fall in the price of one good.")],
    "4": [("a", "State the law of diminishing marginal utility."),
          ("b", "Explain the equi-marginal principle and consumer equilibrium.")],
    "5": [("a", "Define price elasticity of demand and its determinants."),
          ("b", "Discuss the relationship between elasticity and total revenue.")],
}


def _bhum_source_pdf() -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w = _Writer(c)

    w.centred("SCHOOL OF SOCIAL SCIENCES AND LANGUAGES", size=11)
    w.centred("Continuous Assessment Test-1 - Winter Semester 2024-2025", size=11)
    w.space(2 * mm)
    w.line("Course Code: BHUM103L", font="Helvetica-Bold")
    w.line("Course Name: Microeconomics", font="Helvetica-Bold")
    w.line("Class Number: CH2024250100123        Slot: F2")
    w.line("Date: 16-02-2024        Time: 2:00 PM - 3:30 PM")
    w.line("Duration: 90 Minutes        Maximum Marks: 50")
    w.space(3 * mm)
    w.line("Answer ALL the Questions   (5 X 10 = 50 Marks)", font="Helvetica-Bold")
    w.space(3 * mm)

    for number, marks_text, _ in BHUM103L_QUESTIONS:
        w.line(f"{number}.", font="Helvetica-Bold")
        w.y += 5.5 * mm  # body starts on the label line
        w.paragraph(_BHUM_BODIES[number], x=28 * mm, width=80)
        for letter, sub in _BHUM_SUBPARTS.get(number, []):
            w.paragraph(f"({letter}) {sub}", x=34 * mm, width=76)
        c.setFont("Helvetica", 10)
        c.drawRightString(PAGE_W - 20 * mm, w.y + 5 * mm, marks_text)
        w.space(4 * mm)

    c.save()
    return buffer.getvalue()


def build_bhum103l(path: Path) -> Path:
    """Write an image-only (no text layer) scan of the Microeconomics paper."""
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(_bhum_source_pdf(), dpi=SCAN_DPI)
    flattened = [p.convert("L").convert("RGB") for p in pages]
    path.parent.mkdir(parents=True, exist_ok=True)
    flattened[0].save(
        path, format="PDF", save_all=True, append_images=flattened[1:],
        resolution=SCAN_DPI,
    )
    return path


# --------------------------------------------------------------------------
# BCSE308L - Computer Networks FAT with diagrams
# --------------------------------------------------------------------------

_BCSE_BODIES = {
    1: "Compare the OSI reference model with the TCP/IP protocol suite and state two "
       "functions performed at the data link layer.",
    2: "Explain how CSMA/CD resolves contention on a shared Ethernet segment.",
    3: "A host is configured with the address 192.168.10.20 and the mask "
       "255.255.255.0. Determine the network address and the broadcast address.",
    4: "Differentiate between a switch and a router with respect to the layer at "
       "which each operates.",
    5: "Explain the purpose of ARP and describe the format of an ARP request.",
    6: "Describe the three way handshake used by TCP to establish a connection.",
    7: "Explain the sliding window protocol and compare go-back-N with selective "
       "repeat in terms of buffer requirements and retransmission cost.",
    8: "Describe the operation of the distance vector routing algorithm and explain "
       "the count to infinity problem with a suitable example.",
    9: "Explain the working of DNS resolution, covering recursive and iterative "
       "queries and the role of the root servers.",
    10: "Discuss the services offered by UDP and explain why a real time application "
        "may prefer UDP over TCP despite the absence of reliability.",
    11: "Explain classless inter domain routing and show how route aggregation "
        "reduces the size of the forwarding table.",
    12: "Describe the leaky bucket and token bucket algorithms used for traffic "
        "shaping and compare their burst handling behaviour.",
    13: "Answer the following with reference to TCP congestion control.",
}

_BCSE_Q13_SUBPARTS = [
    ("a", "Explain slow start and congestion avoidance using the graph shown above."),
    ("b", "Describe how fast retransmit and fast recovery alter the window size."),
]


def build_bcse308l(path: Path) -> Path:
    """Write a native-text Computer Networks paper carrying vector diagrams."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    w = _Writer(c)

    w.centred("SCHOOL OF COMPUTER SCIENCE AND ENGINEERING", size=11)
    w.centred("Final Assessment Test (FAT) - Fall Inter Semester 2022-2023", size=11)
    w.space(2 * mm)
    w.line("Course Code: BCSE308L", font="Helvetica-Bold")
    w.line("Course Name: COMPUTER NETWORKS", font="Helvetica-Bold")
    w.line("Slot: C2        Duration: 3 Hours        Maximum Marks: 100")
    w.space(3 * mm)
    w.line("Answer ALL the Questions", font="Helvetica-Bold")
    w.space(3 * mm)

    for number, marks in BCSE308L_QUESTIONS:
        n = int(number)
        w.line(f"{n}.", font="Helvetica-Bold")
        w.y += 5.5 * mm
        w.paragraph(_BCSE_BODIES[n], x=28 * mm, width=82)

        if n == 3:
            _draw_topology(c, w)
        if n == 13:
            _draw_congestion_graph(c, w)
            for letter, sub in _BCSE_Q13_SUBPARTS:
                w.paragraph(f"({letter}) {sub}", x=34 * mm, width=78)

        c.setFont("Helvetica", 10)
        c.drawRightString(PAGE_W - 20 * mm, w.y + 5 * mm, f"[{marks}]")
        w.space(4 * mm)

    c.save()
    return path


def build_bcse308l_scanned(path: Path) -> Path:
    """An image-only scan of the Computer Networks paper.

    Exercises the ink figure detector, which is the only one that can work
    when the PDF holds no vector geometry at all.
    """
    import io

    from pdf2image import convert_from_bytes

    buffer = io.BytesIO()
    source = path.parent / "_bcse308l_source.pdf"
    build_bcse308l(source)
    buffer.write(source.read_bytes())
    source.unlink(missing_ok=True)

    pages = convert_from_bytes(buffer.getvalue(), dpi=SCAN_DPI)
    flattened = [p.convert("L").convert("RGB") for p in pages]
    path.parent.mkdir(parents=True, exist_ok=True)
    flattened[0].save(path, format="PDF", save_all=True,
                      append_images=flattened[1:], resolution=SCAN_DPI)
    return path


def build_all(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return {
        "bhum103l": build_bhum103l(directory / "synthetic_bhum103l_scanned.pdf"),
        "bcse308l": build_bcse308l(directory / "synthetic_bcse308l_networks.pdf"),
        "bcse308l_scanned": build_bcse308l_scanned(
            directory / "synthetic_bcse308l_scanned.pdf"
        ),
    }


if __name__ == "__main__":  # pragma: no cover - manual fixture refresh
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("generated")
    for name, built in build_all(target).items():
        print(f"{name}: {built} ({built.stat().st_size} bytes)")
