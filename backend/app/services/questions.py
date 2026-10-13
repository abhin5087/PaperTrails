"""Question and subquestion boundary detection.

All boundary decisions live in :func:`classify_lines`.  Putting them in one
place is what keeps the rules consistent: the same positional constraints
that let a *garbled* label be recovered also stop diagram material from
inventing a question.

The material that used to produce phantom questions - IP octets like
``16.0.0.1``, graph axis ticks, figure captions - is rejected because a
question label has to satisfy *all* of:

* it sits at the document's left margin,
* it is followed by prose, not by another number,
* it is not part of a dotted-decimal run,
* its number fits the sequence seen so far.

A line that fails any of these stays body text attached to whichever question
is open, which is where diagram labels belong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .marks import (
    Marks,
    combine,
    extract_marks,
    find_marks,
    split_trailing_marks,
)

# "1." / "2)" / "03." - the separator is required so a bare number in a chart
# axis cannot open a question.
QUESTION_LABEL_RE = re.compile(r"^\s*(\d{1,2})\s*[.)]\s*(.*)$")

# "(a)" / "a)" / "(i)" / "i." - subquestion openers.
SUBQUESTION_RE = re.compile(
    r"^\s*[\(\[]?\s*([a-h]|i{1,3}|iv|vi{0,3}|ix|x)\s*[\)\].]\s+(.*)$",
    re.IGNORECASE,
)

# A label whose digits OCR destroyed: "1G.", "l0.", "S.", "|2."
GARBLED_LABEL_RE = re.compile(r"^\s*([0-9OlIiSsGgBbZzQq|!\]\[]{1,3})\s*[.)]\s*(.+)$")

# Dotted decimals: IP addresses, version numbers, figure numbering.
DOTTED_DECIMAL_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){2,}\b")

# A run of bare numbers - a graph axis.
NUMERIC_RUN_RE = re.compile(r"^[\s\d.,%/+-]+$")

PAGE_FOOTER_RE = re.compile(
    r"^(?:page\s*\d+\s*(?:of\s*\d+)?|\d+\s*/\s*\d+|-\s*\d+\s*-)$", re.IGNORECASE
)

FIGURE_CAPTION_RE = re.compile(
    r"^\s*(?:fig(?:ure)?|table|chart|graph|diagram|exhibit)\s*[.:]?\s*\d*[.:]?\s",
    re.IGNORECASE,
)

# Instruction boilerplate that precedes question 1.
BOILERPLATE_RE = re.compile(
    r"^\s*(?:answer\s+(?:all|any)|instructions?\b|note\s*[:\-]|general\s+instructions"
    r"|all\s+questions\s+(?:are\s+)?compulsory)",
    re.IGNORECASE,
)

# Prose must start a question body; a digit means we are looking at numbers.
BODY_START_RE = re.compile(r"^[A-Za-z(\[\"']")

#: How far right of the margin a label may sit and still count as one.
MARGIN_TOLERANCE = 12.0

#: A number this far beyond the expected one is a page artefact, not Q47.
MAX_FORWARD_SKIP = 3


@dataclass
class Line:
    """One physical line of text with whatever geometry we have for it."""

    text: str
    page: int
    index: int
    x0: float | None = None
    top: float | None = None
    bottom: float | None = None
    x1: float | None = None

    @property
    def indent(self) -> float:
        if self.x0 is not None:
            return self.x0
        # No geometry (plain OCR text): fall back to leading whitespace.
        return float(len(self.text) - len(self.text.lstrip()))


@dataclass
class Classified:
    """A line plus the boundary decision made about it."""

    line: Line
    kind: str  # question | subquestion | body | boilerplate | footer | caption
    number: str | None = None
    body: str = ""
    reason: str = ""
    recovered: bool = False


@dataclass
class Question:
    """A top-level question and its subquestions."""

    number: str
    text: str = ""
    page: int = 1
    marks: Marks = field(default_factory=Marks.missing)
    children: list["Question"] = field(default_factory=list)
    parent_number: str | None = None
    recovered_label: bool = False
    top: float | None = None
    bottom: float | None = None

    @property
    def label(self) -> str:
        if self.parent_number:
            return f"{self.parent_number}({self.number})"
        return self.number


# --------------------------------------------------------------------------
# Margin estimation
# --------------------------------------------------------------------------


def estimate_left_margin(lines: list[Line]) -> float:
    """The x position where body text begins on this document."""
    values = sorted(ln.indent for ln in lines if ln.text.strip())
    if not values:
        return 0.0
    # The 15th percentile: robust against a handful of outdented artefacts.
    return values[max(0, int(len(values) * 0.15) - 1)]


# --------------------------------------------------------------------------
# Line-level predicates
# --------------------------------------------------------------------------


def _is_numeric_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if DOTTED_DECIMAL_RE.search(stripped):
        return True
    if NUMERIC_RUN_RE.fullmatch(stripped):
        return True
    return False


def _body_is_prose(body: str) -> bool:
    body = body.strip()
    if not body:
        return True  # a bare label on its own line; the next line carries it
    if DOTTED_DECIMAL_RE.match(body):
        return False
    return bool(BODY_START_RE.match(body))


def _at_margin(line: Line, margin: float) -> bool:
    return line.indent <= margin + MARGIN_TOLERANCE


#: A first question label may be any number up to this; after that the
#: sequence constraint takes over.
MAX_FIRST_NUMBER = 20


def _number_fits(number: int, expected: int, seen: set[int], started: bool) -> bool:
    """Sequence constraint: forward only, and not by a wild jump.

    Before the first question is found there is no sequence to check - a
    paper may legitimately be processed from a later page - so any plausible
    opening number is accepted.
    """
    if number in seen:
        return False
    if not started:
        return 1 <= number <= MAX_FIRST_NUMBER
    if number < expected - 1:
        return False
    return number <= expected + MAX_FORWARD_SKIP


#: What each damaged character might really have been.  Several entries are
#: genuinely ambiguous - "G" is read for both 0 and 6 - so every reading is
#: kept and the caller decides using the expected number.
_GARBLE_MAP: dict[str, set[str]] = {
    "O": {"0"}, "o": {"0"}, "Q": {"0"}, "D": {"0"},
    "l": {"1"}, "I": {"1"}, "i": {"1"}, "|": {"1"}, "!": {"1"},
    "]": {"1"}, "[": {"1"}, "t": {"1"},
    "Z": {"2"}, "z": {"2"},
    "S": {"5"}, "s": {"5"},
    "G": {"0", "6"}, "g": {"9", "6"}, "b": {"6"},
    "B": {"8"},
    "q": {"9"},
}


def _degarble_candidates(token: str) -> set[str]:
    """Every digit string a damaged label could have been.

    ``1G`` yields ``{"10", "16"}``: OCR reads "G" for both a zero and a six,
    and refusing to choose here is what lets the sequence constraint decide.
    """
    readings: list[set[str]] = []

    for char in token:
        if char.isdigit():
            readings.append({char})
            continue
        options = _GARBLE_MAP.get(char)
        if not options:
            return set()
        readings.append(options)

    if not readings or len(readings) > 2:
        return set()

    candidates = {""}
    for options in readings:
        candidates = {prefix + option for prefix in candidates for option in options}

    return {c for c in candidates if c.isdigit()}


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_lines(
    lines: list[Line],
    *,
    margin: float | None = None,
    figure_spans: list[tuple[int, float, float]] | None = None,
) -> list[Classified]:
    """Decide what every line is.

    ``figure_spans`` holds rectangles known to contain a figure, as either
    ``(page, top, bottom)`` or ``(page, top, bottom, x0, x1)``.  A line inside
    one is never a question label, and its text belongs to the figure rather
    than to the question body - diagram labels and axis ticks are not part of
    what the question asks.
    """
    if margin is None:
        margin = estimate_left_margin(lines)
    figure_spans = figure_spans or []

    def inside_figure(line: Line) -> bool:
        if line.top is None:
            return False

        for span in figure_spans:
            page, top, bottom = span[0], span[1], span[2]
            if page != line.page or not (top <= line.top <= bottom):
                continue

            # Without horizontal bounds, vertical containment is all we have.
            if len(span) < 5 or line.x0 is None:
                return True

            x0, x1 = span[3], span[4]
            line_x1 = line.x1 if line.x1 is not None else line.x0
            if line_x1 >= x0 and line.x0 <= x1:
                return True

        return False

    out: list[Classified] = []
    seen_numbers: set[int] = set()
    expected = 1
    started = False

    # True once the question currently open has been given its own marks.
    # A question that has not yet collected its marks is still mid-body, so a
    # following line is a continuation rather than a new, unlabelled question.
    marks_seen_since_label = False

    for line in lines:
        text = line.text.strip()

        if not text:
            continue

        if PAGE_FOOTER_RE.fullmatch(text):
            out.append(Classified(line, "footer", reason="page footer"))
            continue

        # Text drawn as part of a diagram - node names, IP labels, axis ticks.
        # It belongs to the figure, not to the question's wording.
        if inside_figure(line):
            out.append(Classified(line, "figure_content", body=text,
                                  reason="inside a figure region"))
            continue

        if FIGURE_CAPTION_RE.match(text):
            out.append(Classified(line, "caption", body=text, reason="figure caption"))
            continue

        if not started and BOILERPLATE_RE.match(text):
            out.append(Classified(line, "boilerplate", body=text,
                                  reason="instruction boilerplate"))
            continue

        # ---- candidate top-level question label -------------------------
        match = QUESTION_LABEL_RE.match(text)
        if match:
            number_text, body = match.group(1), match.group(2)
            number = int(number_text)
            rejection = None

            if inside_figure(line):
                rejection = "inside a figure region"
            elif not _at_margin(line, margin):
                rejection = f"indented past the margin ({line.indent:.0f})"
            elif DOTTED_DECIMAL_RE.match(text.strip()):
                rejection = "dotted-decimal run (IP address or similar)"
            elif not _body_is_prose(body):
                rejection = "not followed by prose"
            elif not _number_fits(number, expected, seen_numbers, started):
                rejection = (
                    f"number {number} does not fit the sequence (expected {expected})"
                )

            if rejection is None:
                out.append(Classified(line, "question", number=str(number), body=body,
                                      reason="numbered label at margin"))
                seen_numbers.add(number)
                expected = number + 1
                started = True
                marks_seen_since_label = split_trailing_marks(body)[1].resolved
                continue

            out.append(Classified(line, "body", body=text,
                                  reason=f"rejected as question: {rejection}"))
            continue

        # ---- candidate subquestion --------------------------------------
        sub = SUBQUESTION_RE.match(text)
        if sub and started:
            marker, body = sub.group(1), sub.group(2)
            if inside_figure(line):
                out.append(Classified(line, "body", body=text,
                                      reason="rejected as subquestion: inside figure"))
            elif not _body_is_prose(body):
                out.append(Classified(line, "body", body=text,
                                      reason="rejected as subquestion: not prose"))
            else:
                out.append(Classified(line, "subquestion", number=marker.lower(),
                                      body=body, reason="subpart marker"))
            continue

        # ---- garbled label recovery -------------------------------------
        # Only at the margin, only for the exact number expected next, and
        # only when real prose follows.  Diagram text satisfies none of this.
        garbled = GARBLED_LABEL_RE.match(text)
        if garbled and not inside_figure(line) and _at_margin(line, margin):
            token, body = garbled.group(1), garbled.group(2)
            candidates = _degarble_candidates(token)
            digits = str(expected) if str(expected) in candidates else None
            if (
                digits is not None
                and _body_is_prose(body)
                and not _is_numeric_noise(body)
            ):
                out.append(Classified(line, "question", number=digits, body=body,
                                      reason=f"recovered garbled label '{token}'",
                                      recovered=True))
                seen_numbers.add(int(digits))
                expected = int(digits) + 1
                started = True
                marks_seen_since_label = split_trailing_marks(body)[1].resolved
                continue

        # ---- missing-label recovery -------------------------------------
        # A question whose label OCR dropped entirely.  Requires the strongest
        # evidence available: at the margin, prose, carrying its own trailing
        # marks, outside any figure, after at least one real question, and -
        # critically - only once the open question has already taken its own
        # marks.  Without that last constraint a continuation line printed
        # after a diagram looks exactly like a new question.
        if (
            started
            and marks_seen_since_label
            and not inside_figure(line)
            and _at_margin(line, margin)
        ):
            head, trailing = split_trailing_marks(text)
            if (
                trailing.raw is not None
                and trailing.resolved
                and _body_is_prose(head)
                and not _is_numeric_noise(head)
                and len(head.split()) >= 6
                and not DOTTED_DECIMAL_RE.search(head)
            ):
                out.append(Classified(line, "question", number=str(expected),
                                      body=text,
                                      reason="recovered unlabelled question "
                                             "(margin + prose + trailing marks)",
                                      recovered=True))
                seen_numbers.add(expected)
                expected += 1
                marks_seen_since_label = True
                continue

        if started and split_trailing_marks(text)[1].resolved:
            marks_seen_since_label = True

        out.append(Classified(line, "body" if started else "boilerplate", body=text,
                              reason="continuation" if started else "pre-question text"))

    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def _distribute_sum(parent: Question) -> None:
    """Hand the parts of a summed mark to the matching subquestions.

    ``5+5`` across exactly two subparts is evidence, not a guess, so the
    parts are assigned.  Any other shape is left alone.
    """
    if not parent.children or not parent.marks.is_split:
        return
    if len(parent.marks.parts) != len(parent.children):
        return
    if any(child.marks.raw is not None for child in parent.children):
        return

    for child, value in zip(parent.children, parent.marks.parts):
        child.marks = Marks(raw=str(value), total=value, parts=[value], resolved=True)


def _reattribute_trailing_marks(parent: Question) -> bool:
    """Move a marks value printed after the last subpart up to the parent.

    A paper prints ``5+5`` or ``10`` once, at the end of the whole question
    block.  Line-wise that lands on the final subquestion, but it is the
    parent's total.  The giveaway is that *only* the last subpart carries a
    value while its siblings carry none - genuine per-subpart marks appear on
    every subpart.
    """
    if not parent.children or parent.marks.raw is not None:
        return False

    last = parent.children[-1]
    if last.marks.raw is None:
        return False
    if any(child.marks.raw is not None for child in parent.children[:-1]):
        return False

    parent.marks = last.marks
    last.marks = Marks.missing()
    return True


def build_questions(classified: list[Classified]) -> list[Question]:
    """Fold classified lines into top-level questions with subquestions."""
    questions: list[Question] = []
    current: Question | None = None
    current_sub: Question | None = None

    # A marks value printed on a caption or inside a diagram is still the
    # question's marks, so it is kept aside rather than thrown away with the
    # figure text it happened to share a line with.
    deferred_marks: dict[int, Marks] = {}

    def flush_text(target: Question, chunk: str) -> None:
        target.text = f"{target.text} {chunk}".strip()

    def defer_marks(target: Question | None, text: str) -> None:
        """Take a marks value off a caption or diagram line.

        Only explicit notation counts here - ``[5]``, ``(5 Marks)``.  A bare
        number inside a figure is an axis tick or a node label, never a mark,
        so the trailing-number rule used for body text is deliberately not
        applied.
        """
        if target is None:
            return
        found = find_marks(text)
        if found.raw is not None:
            deferred_marks.setdefault(id(target), found)

    for item in classified:
        if item.kind == "question":
            current = Question(
                number=item.number or "?",
                text=item.body.strip(),
                page=item.line.page,
                recovered_label=item.recovered,
                top=item.line.top,
                bottom=item.line.bottom,
            )
            questions.append(current)
            current_sub = None
            continue

        if item.kind == "subquestion" and current is not None:
            current_sub = Question(
                number=item.number or "?",
                text=item.body.strip(),
                page=item.line.page,
                parent_number=current.number,
                top=item.line.top,
                bottom=item.line.bottom,
            )
            current.children.append(current_sub)
            continue

        if item.kind == "body":
            target = current_sub or current
            if target is not None:
                flush_text(target, item.body or item.line.text.strip())
                if item.line.bottom is not None:
                    target.bottom = item.line.bottom
            continue

        if item.kind in ("caption", "figure_content"):
            # The wording belongs to the figure, but a marks value on that
            # line belongs to the question.
            defer_marks(current_sub or current, item.body or item.line.text.strip())
            continue

    # Marks come out of the assembled text, not line by line, so a value
    # printed on a continuation line still reaches the right question.
    for question in questions:
        for child in question.children:
            child.text, child.marks = extract_marks(child.text)
            if child.marks.raw is None and id(child) in deferred_marks:
                child.marks = deferred_marks[id(child)]

        question.text, question.marks = extract_marks(question.text)
        if question.marks.raw is None and id(question) in deferred_marks:
            question.marks = deferred_marks[id(question)]

        moved = _reattribute_trailing_marks(question)

        if question.marks.raw is None and question.children:
            question.marks = combine([c.marks for c in question.children])
        elif moved or question.marks.raw is not None:
            _distribute_sum(question)

    return questions


def extract_questions(
    lines: list[Line],
    *,
    margin: float | None = None,
    figure_spans: list[tuple[int, float, float]] | None = None,
) -> tuple[list[Question], list[Classified]]:
    """Convenience wrapper returning both the questions and the audit trail."""
    classified = classify_lines(lines, margin=margin, figure_spans=figure_spans)
    return build_questions(classified), classified


def flatten(questions: list[Question]) -> list[dict]:
    """Flatten to the row shape the persistence layer stores."""
    rows: list[dict] = []

    for question in questions:
        rows.append(
            {
                "question_no": question.label,
                "parent_no": None,
                "text": question.text,
                "page": question.page,
                "recovered_label": question.recovered_label,
                **question.marks.to_dict(),
            }
        )
        for child in question.children:
            rows.append(
                {
                    "question_no": child.label,
                    "parent_no": question.label,
                    "text": child.text,
                    "page": child.page,
                    "recovered_label": False,
                    **child.marks.to_dict(),
                }
            )

    return rows
