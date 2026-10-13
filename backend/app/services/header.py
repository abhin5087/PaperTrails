"""Header metadata extraction.

A header has to survive three different kinds of damage:

* **OCR character confusion** - ``BHUM1O3L`` for ``BHUM103L``, ``5O`` for
  ``50``.  Normalisation is applied per character position and only inside a
  token that already has the shape of the field being read, so a legitimate
  course code is never rewritten.
* **Layout variation** - exam labels written in Roman (``CAT-I``) or Arabic
  (``CAT-1``) numerals, semester words in either order
  (``Winter Semester`` / ``Semester: Winter``).
* **Lost spacing** - a scan can fuse a whole line into ``CourseCode:BHUM103L``.
  Every field therefore gets a second attempt against a de-spaced view.

Nothing is invented.  A field that cannot be read confidently is reported as
absent, and the raw header text is kept so the gap can be investigated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Characters OCR swaps between the alphabetic and numeric halves of a code.
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "6": "G", "2": "Z"}
_LETTER_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8",
                    "G": "6", "Z": "2", "Q": "0", "D": "0"}

ROMAN_TO_ARABIC = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}

SEMESTER_WORDS = ("FALL", "WINTER", "SUMMER", "SPRING", "WEEKEND", "INTER")

MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")


@dataclass
class HeaderField:
    """One header value together with how it was obtained."""

    value: str
    raw: str
    source: str
    confident: bool = True

    def to_dict(self) -> dict:
        return {"value": self.value, "raw": self.raw, "source": self.source,
                "confident": self.confident}


@dataclass
class Header:
    """Parsed header.  ``unparsed`` names fields seen but not understood."""

    fields: dict[str, HeaderField] = field(default_factory=dict)
    raw_text: str = ""
    unparsed: list[str] = field(default_factory=list)

    def get(self, name: str, default=None):
        found = self.fields.get(name)
        return found.value if found else default

    def has(self, name: str) -> bool:
        return name in self.fields

    def set(self, name: str, value: str, raw: str, source: str,
            confident: bool = True) -> None:
        self.fields[name] = HeaderField(value=value, raw=raw, source=source,
                                        confident=confident)

    def to_dict(self) -> dict:
        return {name: f.value for name, f in self.fields.items()}

    def to_detail(self) -> dict:
        return {
            "fields": {n: f.to_dict() for n, f in self.fields.items()},
            "unparsed": list(self.unparsed),
        }

    @property
    def completeness(self) -> float:
        wanted = ("course_code", "course_name", "exam_type", "semester", "max_marks")
        return sum(1 for w in wanted if self.has(w)) / len(wanted)

    def __len__(self) -> int:
        return len(self.fields)


# --------------------------------------------------------------------------
# Normalisation helpers
# --------------------------------------------------------------------------


def _collapse(text: str) -> str:
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("’", "'")
    return re.sub(r"[ \t]+", " ", text)


def _despace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def normalise_digits(token: str) -> str:
    """Force a token that should be numeric into digits."""
    return "".join(_LETTER_TO_DIGIT.get(ch.upper(), ch) for ch in token)


def normalise_course_code(token: str) -> str | None:
    """Repair OCR confusion inside a course-code-shaped token.

    The VIT layout is 3-5 letters, 3-4 digits, optional trailing letter.
    Characters are corrected only where the position demands a different
    character class, so ``BCSE308L`` survives untouched and ``8HUM1O3L``
    becomes ``BHUM103L``.
    """
    candidate = token.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6,10}", candidate):
        return None

    # Trailing letter-or-confusable suffix.
    suffix = ""
    body = candidate
    tail_match = re.fullmatch(r"(.*?)([A-Z0-9])", candidate)
    if tail_match and len(candidate) >= 7:
        head, last = tail_match.groups()
        if _DIGIT_TO_LETTER.get(last, last).isalpha():
            # Only peel the suffix when what remains still has 3-4 digits.
            if re.fullmatch(r"[A-Z0-9]{3,5}[A-Z0-9]{3,4}", head):
                body, suffix = head, _DIGIT_TO_LETTER.get(last, last)

    digits_len = 4 if len(body) >= 8 else 3
    if len(body) - digits_len < 2:
        return None

    alpha_part = body[: len(body) - digits_len]
    digit_part = body[len(body) - digits_len:]

    alpha_fixed = "".join(_DIGIT_TO_LETTER.get(ch, ch) for ch in alpha_part)
    digit_fixed = "".join(_LETTER_TO_DIGIT.get(ch, ch) for ch in digit_part)

    if not alpha_fixed.isalpha() or not digit_fixed.isdigit():
        return None

    return f"{alpha_fixed}{digit_fixed}{suffix}"


def _search(patterns: tuple[str, ...], text: str, flags=re.IGNORECASE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match
    return None


# --------------------------------------------------------------------------
# Field readers
# --------------------------------------------------------------------------

_COURSE_CODE_LABELLED = (
    r"Course\s*(?:Code|Co?de)\s*[:\-]?\s*([A-Z0-9]{6,10})\b",
    r"Subject\s*Code\s*[:\-]?\s*([A-Z0-9]{6,10})\b",
)
# In de-spaced text the code runs straight into the next label, so the
# capture is bounded by the labels that can follow it.
_NEXT_LABEL_WORDS = (
    "Course|Class|Slot|Date|Time|Duration|Maximum|Max|Exam|Semester|Marks|"
    "Faculty|Programme|Program|School|Answer|Instructions"
)
_COURSE_CODE_COMPRESSED = (
    rf"Course\s*Code\s*[:\-]?\s*([A-Z0-9]{{6,10}}?)(?={_NEXT_LABEL_WORDS}|$)",
    r"Course\s*Code\s*[:\-]?\s*([A-Z]{2,5}[A-Z0-9]{3,4}[A-Z]?)",
)
_COURSE_CODE_BARE = (r"\b([A-Z]{3,5}\d{3,4}[A-Z]?)\b",)


def _read_course_code(header: Header, text: str, compressed: str) -> None:
    for patterns, source, haystack in (
        (_COURSE_CODE_LABELLED, "labelled", text),
        (_COURSE_CODE_COMPRESSED, "labelled-compressed", compressed),
        (_COURSE_CODE_BARE, "bare", text),
    ):
        match = _search(patterns, haystack)
        if not match:
            continue
        raw = match.group(1)
        fixed = normalise_course_code(raw)
        if fixed:
            header.set("course_code", fixed, raw, source, confident=(fixed == raw.upper()))
            return
        header.unparsed.append(f"course_code: could not normalise '{raw}'")


_COURSE_NAME = (
    r"Course\s*(?:Title|Name)\s*[:\-]?\s*([^\n]{2,80})",
    r"Subject\s*(?:Title|Name)\s*[:\-]?\s*([^\n]{2,80})",
    # OCR commonly eats the first letter of a label word ("Coerse itle" for
    # "Course Title").  The title is the text between that damaged label and
    # the course code that follows it on the same line, so anchoring on
    # "Course Code" recovers it without having to read the label itself.
    r"\b[Tt]?itle\s*[:\-]?\s*([A-Z][A-Za-z0-9 &/.\-]{2,60}?)\s+Course\s*Code\b",
    r"\b[Tt]?itle\s*[:\-]?\s*([A-Z][A-Za-z0-9 &/.\-]{2,60})",
)

# Labels that mark the start of the *next* field on the same line.
_NEXT_LABEL = re.compile(
    r"\s{2,}|\s+(?=(?:Course|Class|Slot|Date|Time|Duration|Max|Maximum|Exam|Semester|"
    r"Faculty|Programme|Program|School)\b)",
    re.IGNORECASE,
)


def _trim_at_next_label(value: str) -> str:
    """Stop a value from swallowing the field printed after it."""
    trimmed = _NEXT_LABEL.split(value, maxsplit=1)[0].strip(" :-–")

    # De-spaced text has no gap to split on, so fall back to cutting at the
    # next known label.  Only safe when the value really is fused; a spaced
    # value keeps whatever words it legitimately contains.
    if " " not in trimmed:
        fused_labels = f"{_NEXT_LABEL_WORDS}|" + "|".join(
            w.capitalize() for w in SEMESTER_WORDS
        )
        boundary = re.search(rf"(?<=.)(?:{fused_labels})", trimmed)
        if boundary:
            trimmed = trimmed[: boundary.start()].strip(" :-–")

    return trimmed


def _read_course_name(header: Header, text: str, compressed: str = "") -> None:
    for haystack, source in ((text, "labelled"),
                             (compressed, "labelled-compressed")):
        if not haystack:
            continue
        match = _search(_COURSE_NAME, haystack)
        if not match:
            continue
        value = _trim_at_next_label(_collapse(match.group(1)))
        if value:
            header.set("course_name", value, match.group(1).strip(), source)
            return


_EXAM_FULL = (
    r"(Continuous\s*Assessment\s*Test\s*[-–]?\s*(?:[IV]{1,3}|\d))",
    r"(Final\s*Assessment\s*Test)",
    r"(Re[-\s]?Final\s*Assessment\s*Test)",
    r"(Model\s*Examination)",
)
_EXAM_SHORT = (
    r"\b(CAT)\s*[-–]?\s*([IV]{1,3}|\d)\b",
    r"\b(FAT)\b",
)


def _canonical_exam(label: str, number: str | None) -> str:
    base = {"CAT": "Continuous Assessment Test", "FAT": "Final Assessment Test"}.get(
        label.upper(), None
    )
    if base is None:
        base = " ".join(w.capitalize() if w.islower() else w for w in label.split())
        base = re.sub(r"\s*[-–]\s*", "-", " ".join(base.split()))
    if number is None:
        return base
    return f"{base}-{number}"


def _read_exam_type(header: Header, text: str, compressed: str) -> None:
    for haystack, source in ((text, "full"), (compressed, "full-compressed")):
        match = _search(_EXAM_FULL, haystack)
        if match:
            raw = " ".join(match.group(1).split())
            # Split the trailing numeral off so it can be normalised.
            tail = re.search(r"[-–]?\s*([IV]{1,3}|\d)\s*$", raw)
            if tail:
                number = tail.group(1)
                arabic = ROMAN_TO_ARABIC.get(number.upper(), None)
                number = str(arabic) if arabic else number
                base = raw[: tail.start()].strip(" -–")
                header.set("exam_type", _canonical_exam(base, number), raw, source)
            else:
                header.set("exam_type", _canonical_exam(raw, None), raw, source)
            return

    match = _search(_EXAM_SHORT, text)
    if match:
        label = match.group(1)
        number = match.group(2) if match.lastindex and match.lastindex >= 2 else None
        if number:
            arabic = ROMAN_TO_ARABIC.get(number.upper(), None)
            number = str(arabic) if arabic else number
        header.set("exam_type", _canonical_exam(label, number), match.group(0).strip(),
                   "abbreviation")


_ACADEMIC_YEAR = re.compile(r"\b(20\d{2})\s*[-–/]\s*(20\d{2}|\d{2})\b")


def _read_semester(header: Header, text: str, compressed: str) -> None:
    words = "|".join(SEMESTER_WORDS)

    # "Winter Semester", "Fall Inter Semester"
    match = re.search(rf"\b((?:{words})(?:\s+(?:{words}))*\s+SEMESTER)\b", text,
                     re.IGNORECASE)
    source = "word-order"

    if match is None:
        # "Semester: Winter" / "Semester - Fall Inter"
        match = re.search(rf"\bSEMESTER\s*[:\-]\s*((?:{words})(?:\s+(?:{words}))*)\b",
                          text, re.IGNORECASE)
        if match:
            value = " ".join(w.capitalize() for w in match.group(1).split()) + " Semester"
            header.set("semester", value, match.group(0).strip(), "reversed")
            source = None

    if match is not None and source:
        value = " ".join(w.capitalize() for w in match.group(1).split())
        value = re.sub(r"\bSemester\b", "Semester", value, flags=re.IGNORECASE)
        header.set("semester", value, match.group(1).strip(), source)

    if not header.has("semester"):
        match = re.search(rf"((?:{words})(?:{words})*SEMESTER)", compressed,
                          re.IGNORECASE)
        if match:
            raw = match.group(1)
            spaced = re.sub(rf"({words}|SEMESTER)", r" \1 ", raw, flags=re.IGNORECASE)
            value = " ".join(w.capitalize() for w in spaced.split())
            header.set("semester", value, raw, "compressed")

    year = _ACADEMIC_YEAR.search(text)
    if year:
        start, end = year.group(1), year.group(2)
        if len(end) == 2:
            end = start[:2] + end
        header.set("academic_year", f"{start}-{end}", year.group(0).strip(), "range")
    else:
        month = re.search(rf"\b({'|'.join(MONTHS)})\s+(20\d{{2}})\b", text, re.IGNORECASE)
        if month:
            header.set("academic_year", month.group(2), month.group(0).strip(), "month")
            if not header.has("exam_month"):
                header.set("exam_month", month.group(1).capitalize(),
                           month.group(0).strip(), "month")


_SLOT = (r"\bSlot\s*[:\-]?\s*([A-Z]\d\+?[A-Z0-9+]*)\b",)


def _read_slot(header: Header, text: str, compressed: str) -> None:
    match = _search(_SLOT, text) or _search(_SLOT, compressed)
    if match:
        header.set("slot", match.group(1).upper(), match.group(0).strip(), "labelled")


# Structured total: "(5 X 10 = 50 Marks)" - internally checkable.
_MARKS_EXPRESSION = re.compile(
    r"(\d{1,2})\s*[xX×*]\s*(\d{1,3})\s*=\s*([A-Z0-9]{1,3})", re.IGNORECASE
)
_MAX_MARKS_PLAIN = (
    r"(?:Maximum|Max\.?|Total)\s*Marks\s*[:\-]?\s*([A-Z0-9]{1,3})\b",
    r"Marks\s*[:\-]?\s*([A-Z0-9]{1,3})\s*$",
)


def _read_max_marks(header: Header, text: str, compressed: str) -> None:
    plain_value: int | None = None
    plain_raw = ""
    match = _search(_MAX_MARKS_PLAIN, text) or _search(_MAX_MARKS_PLAIN, compressed)
    if match:
        digits = normalise_digits(match.group(1))
        if digits.isdigit():
            plain_value = int(digits)
            plain_raw = match.group(1)

    expr_value: int | None = None
    expr_raw = ""
    expr = _MARKS_EXPRESSION.search(text) or _MARKS_EXPRESSION.search(compressed)
    if expr:
        count = normalise_digits(expr.group(1))
        each = normalise_digits(expr.group(2))
        stated = normalise_digits(expr.group(3))
        if count.isdigit() and each.isdigit() and stated.isdigit():
            product = int(count) * int(each)
            # Only trusted when the expression agrees with itself.
            if product == int(stated):
                expr_value = product
                expr_raw = expr.group(0).strip()
                # Keep the components: "10 X 10 = 100" also says that each of
                # ten questions is worth ten, which a paper may state only here.
                header.set("marks_distribution", f"{int(count)}x{int(each)}",
                           expr_raw, "expression")

    if expr_value is not None and (plain_value is None or plain_value != expr_value):
        # A self-consistent "a X b = c" is stronger evidence than a single
        # number that OCR may have mangled.
        header.set("max_marks", str(expr_value), expr_raw, "expression")
        if plain_value is not None:
            header.unparsed.append(
                f"max_marks: stated '{plain_raw}' disagrees with expression "
                f"'{expr_raw}'; used {expr_value}"
            )
        return

    if plain_value is not None:
        header.set("max_marks", str(plain_value), plain_raw, "labelled",
                   confident=plain_raw.isdigit())
    elif expr_value is not None:
        header.set("max_marks", str(expr_value), expr_raw, "expression")


# Anchored on a unit word so it cannot run into the next header field.
_DURATION = (
    r"(?:Exam\s*)?Duration\s*[:\-]?\s*(\d{1,3}\s*(?:Minutes?|Mins?|Hours?|Hrs?))",
    r"(?:Exam\s*)?Duration\s*[:\-]?\s*(\d{1,2}\s*(?:1/2|½)?\s*(?:Hours?|Hrs?))",
    r"\b(\d{1,3}\s*(?:Minutes|Mins)\b)",
    r"\b(\d{1,2}\s*(?:Hours|Hrs)\b)",
)


def _read_duration(header: Header, text: str, compressed: str) -> None:
    match = _search(_DURATION, text)
    if match:
        value = " ".join(match.group(1).split())
        value = re.sub(r"(\d)\s*(?=[A-Za-z])", r"\1 ", value)
        header.set("duration", value, match.group(1).strip(), "unit-anchored")
        return

    match = _search((r"Duration\s*[:\-]?\s*(\d{1,3})(Minutes?|Mins?|Hours?|Hrs?)",),
                    compressed)
    if match:
        header.set("duration", f"{match.group(1)} {match.group(2)}",
                   match.group(0), "compressed")


_DATE = (
    r"(?:Date\s*of\s*Exam(?:ination)?|Exam\s*Date|Date)\s*[:\-]?\s*"
    r"(\d{1,2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{2,4})",
    r"\b(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})\b",
)
_TIME = (
    r"\b(\d{1,2}[:.]\d{2}\s*(?:AM|PM)?\s*(?:to|-|–)\s*\d{1,2}[:.]\d{2}\s*(?:AM|PM)?)",
)


def _read_date_time(header: Header, text: str) -> None:
    match = _search(_DATE, text)
    if match:
        value = re.sub(r"\s*([.\-/])\s*", r"\1", match.group(1))
        header.set("exam_date", value, match.group(1).strip(), "labelled")

    match = _search(_TIME, text)
    if match:
        value = " ".join(match.group(1).split())
        value = re.sub(r"\s*(?:to|-|–)\s*", " - ", value)
        header.set("exam_time", value, match.group(1).strip(), "range")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

#: Header material never appears beyond the opening lines of a paper.
HEADER_LINE_BUDGET = 25


def header_region(text: str, max_lines: int = HEADER_LINE_BUDGET) -> str:
    """The slice of a page that may contain header fields."""
    lines = [ln for ln in (text or "").splitlines()]
    return "\n".join(lines[:max_lines])


def parse_header(text: str, *, limit_region: bool = True) -> Header:
    """Parse header metadata out of page text.

    ``text`` should be the first page's text from whichever extraction level
    is being evaluated - OCR output and native text are both acceptable.
    """
    source_text = header_region(text) if limit_region else (text or "")
    collapsed = _collapse(source_text)
    compressed = _despace(collapsed)

    header = Header(raw_text=collapsed)
    if not collapsed.strip():
        return header

    _read_course_code(header, collapsed, compressed)
    _read_course_name(header, collapsed, compressed)
    _read_exam_type(header, collapsed, compressed)
    _read_semester(header, collapsed, compressed)
    _read_slot(header, collapsed, compressed)
    _read_max_marks(header, collapsed, compressed)
    _read_duration(header, collapsed, compressed)
    _read_date_time(header, collapsed)

    return header
