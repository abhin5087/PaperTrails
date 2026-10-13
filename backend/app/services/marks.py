"""Marks parsing.

Exam papers print marks in several shapes - ``10``, ``[10]``, ``(5 Marks)``,
``5+5``, ``2 + 8`` - and a scan can damage any of them.  The guiding rule here
is that a mark is only reported as a number when the text actually supports
that number.  When OCR has plainly eaten a separator (``7+3`` arriving as
``743``) the value is kept *unresolved* with its raw text intact rather than
guessed at, because a wrong mark is worse than a missing one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A single question is never worth more than this.  Used to tell a plausible
# mark from a page number, a year, or a fused OCR sum.
MAX_QUESTION_MARKS = 50

_SUM_RE = re.compile(r"^\d{1,2}(?:\s*\+\s*\d{1,2})+$")
_PLAIN_RE = re.compile(r"^\d{1,3}$")

# Bracketed / labelled marks appearing anywhere in a line.
_DELIMITED_RE = re.compile(
    r"[\(\[\{]\s*(\d{1,3}(?:\s*\+\s*\d{1,2})*)\s*(?:marks?|m)?\s*[\)\]\}]",
    re.IGNORECASE,
)
_LABELLED_RE = re.compile(
    r"\bmarks?\s*[:\-]?\s*(\d{1,3}(?:\s*\+\s*\d{1,2})*)\b",
    re.IGNORECASE,
)

# A bare mark hanging at the end of a line: "... slopes downward. 10"
_TRAILING_RE = re.compile(r"(?<![\w.+/-])(\d{1,3}(?:\s*\+\s*\d{1,2})*)\s*$")

# Distribution banners such as "(5 X 10 = 50 Marks)" are totals for the whole
# paper, never marks for the question they sit next to.
_DISTRIBUTION_RE = re.compile(
    r"\d{1,2}\s*[xX×*]\s*\d{1,2}\s*=\s*\d{1,3}", re.IGNORECASE
)


@dataclass
class Marks:
    """A parsed marks value, carrying its own evidence."""

    raw: str | None = None
    total: int | None = None
    parts: list[int] = field(default_factory=list)
    resolved: bool = False
    reason: str | None = None

    #: Where the value came from. ``printed`` means it was written next to
    #: the question; ``distribution`` means the paper stated it once for
    #: every question ("10 X 10 = 100 Marks").  Never a guess either way.
    source: str = "printed"

    @property
    def is_split(self) -> bool:
        return len(self.parts) > 1

    def to_dict(self) -> dict:
        return {
            "marks": self.total,
            "marks_raw": self.raw,
            "marks_parts": list(self.parts),
            "marks_resolved": self.resolved,
            "marks_reason": self.reason,
            "marks_source": self.source,
        }

    @classmethod
    def missing(cls) -> "Marks":
        return cls()

    @classmethod
    def unresolved(cls, raw: str, reason: str) -> "Marks":
        return cls(raw=raw, total=None, parts=[], resolved=False, reason=reason)


#: Largest value a single component of a split mark can plausibly take.
MAX_SPLIT_PART = 20


def _plausible(parts: tuple[int, ...]) -> bool:
    return all(1 <= p <= MAX_SPLIT_PART for p in parts)


def _ambiguous_splits(digits: str) -> list[tuple[int, ...]]:
    """Ways a digit run could have been a sum before OCR damaged the ``+``.

    Two kinds of damage are modelled:

    *dropped* separator
        ``5+5`` read as ``55``, so any cut of the run is a candidate.
    *misread* separator
        ``7+3`` read as ``743`` - the ``+`` came back as a digit.  For an
        odd-length run the middle character is tried as the lost operator.

    Candidates are evidence that the value is ambiguous, never an answer.
    """
    candidates: list[tuple[int, ...]] = []

    for cut in range(1, len(digits)):
        left, right = digits[:cut], digits[cut:]
        if left.startswith("0") or right.startswith("0"):
            continue
        parts = (int(left), int(right))
        if _plausible(parts):
            candidates.append(parts)

    if len(digits) >= 3 and len(digits) % 2 == 1:
        middle = len(digits) // 2
        left, right = digits[:middle], digits[middle + 1 :]
        if left and right and not left.startswith("0") and not right.startswith("0"):
            parts = (int(left), int(right))
            if _plausible(parts) and parts not in candidates:
                candidates.append(parts)

    return candidates


def parse_marks_token(token: str) -> Marks:
    """Interpret one marks-shaped token."""
    if token is None:
        return Marks.missing()

    raw = " ".join(str(token).split())
    if not raw:
        return Marks.missing()

    compact = raw.replace(" ", "")

    if _SUM_RE.match(compact):
        parts = [int(p) for p in compact.split("+")]
        total = sum(parts)
        if total > MAX_QUESTION_MARKS:
            return Marks.unresolved(
                raw, f"sum {total} exceeds the {MAX_QUESTION_MARKS} mark ceiling"
            )
        return Marks(raw=raw, total=total, parts=parts, resolved=True)

    if _PLAIN_RE.match(compact):
        value = int(compact)
        if 1 <= value <= MAX_QUESTION_MARKS and len(compact) <= 2:
            return Marks(raw=raw, total=value, parts=[value], resolved=True)

        # A value that is too long or too large for a single question is
        # almost always a sum whose separator the scan damaged.  Say so
        # instead of guessing which reading was intended.
        splits = _ambiguous_splits(compact)
        if splits:
            options = ", ".join("+".join(str(p) for p in s) for s in splits)
            return Marks.unresolved(
                raw,
                f"ambiguous marks '{raw}': could be {options} with a damaged '+'",
            )

        return Marks.unresolved(raw, f"implausible marks value '{raw}'")

    return Marks.unresolved(raw, f"unrecognised marks text '{raw}'")


def find_marks(text: str) -> Marks:
    """Find marks stated anywhere in ``text``, preferring explicit notation."""
    if not text:
        return Marks.missing()

    for pattern in (_DELIMITED_RE, _LABELLED_RE):
        for match in pattern.finditer(text):
            if _DISTRIBUTION_RE.search(match.group(0)):
                continue
            parsed = parse_marks_token(match.group(1))
            if parsed.raw:
                return parsed

    return Marks.missing()


def split_trailing_marks(line: str) -> tuple[str, Marks]:
    """Peel a bare marks value off the end of a line.

    Returns the line without the marks and the parsed value.  Lines that end
    in a sentence number, a year, or a distribution banner are left alone.
    """
    if not line:
        return line, Marks.missing()

    stripped = line.rstrip()
    if _DISTRIBUTION_RE.search(stripped):
        return line, Marks.missing()

    match = _TRAILING_RE.search(stripped)
    if not match:
        return line, Marks.missing()

    head = stripped[: match.start()].rstrip()

    # A number is only a mark when something precedes it; a line that is just
    # a number is diagram noise or a page artefact.
    if not head:
        return line, Marks.missing()

    # Refuse to strip a digit that belongs to the sentence (".. by 2020").
    if head.endswith(("+", "-", "=", "x", "X", "/", ".e", "e")):
        return line, Marks.missing()

    parsed = parse_marks_token(match.group(1))
    if parsed.raw is None:
        return line, Marks.missing()

    return head, parsed


def extract_marks(text: str) -> tuple[str, Marks]:
    """Full marks extraction for a question body.

    Explicit notation wins; a bare trailing number is the fallback.  The
    returned text has the marks notation removed so it does not pollute the
    question body.
    """
    found = find_marks(text)
    if found.raw is not None:
        cleaned = _DELIMITED_RE.sub(" ", text)
        cleaned = _LABELLED_RE.sub(" ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(), found

    head, trailing = split_trailing_marks(text)
    if trailing.raw is not None:
        return re.sub(r"\s+", " ", head).strip(), trailing

    return re.sub(r"\s+", " ", text).strip(), Marks.missing()


def combine(children: list[Marks]) -> Marks:
    """Roll subquestion marks up into a parent total.

    Returns an unresolved value when any child is unresolved - a parent total
    built from a guess would be a guess.
    """
    known = [c for c in children if c.resolved and c.total is not None]
    if not children or not known:
        return Marks.missing()

    if len(known) != len(children):
        raw = " + ".join(c.raw for c in children if c.raw)
        return Marks.unresolved(
            raw or None, "parent total withheld: a subquestion mark is unresolved"
        )

    parts = [c.total for c in known]
    total = sum(parts)
    raw = "+".join(str(p) for p in parts)
    if total > MAX_QUESTION_MARKS:
        return Marks.unresolved(raw, f"subquestion total {total} is implausible")
    return Marks(raw=raw, total=total, parts=parts, resolved=True)


def from_distribution(each: int, raw: str) -> Marks:
    """A per-question value the paper stated once for the whole paper.

    This is reading the paper, not guessing: a banner such as
    ``(10 X 10 = 100 Marks)`` says every one of the ten questions is worth
    ten.  The caller is responsible for checking that the question count
    actually matches the banner before applying it.
    """
    return Marks(
        raw=raw,
        total=each,
        parts=[each],
        resolved=True,
        reason=f"from the paper's stated distribution '{raw}'",
        source="distribution",
    )
