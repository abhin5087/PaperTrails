"""Conservative OCR noise correction.

OCR output from an exam paper is a mix of prose, which benefits from
correction, and technical material - IP addresses, course codes, protocol
acronyms, equations, marks - which is destroyed by it.  This module therefore
corrects a token only when every one of the following holds:

  1. the token is not protected (see :data:`PROTECTED_PATTERNS`),
  2. the token is not already a word the lexicon recognises,
  3. exactly one correction candidate is recognised by the lexicon.

Anything else is left exactly as OCR produced it.  The original text is
always preserved alongside the corrected text, and every change is recorded
with the rule that produced it, so a bad correction can be traced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_LEXICON_FILE = _DATA_DIR / "ocr_lexicon.txt"
_DOMAIN_FILE = _DATA_DIR / "ocr_domain_terms.txt"


# --------------------------------------------------------------------------
# Protected material - never corrected
# --------------------------------------------------------------------------

PROTECTED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Dotted-quad IP addresses and anything that looks like one.
    ("ip_address", re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")),
    ("ip_with_prefix", re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$")),
    # MAC addresses.
    ("mac_address", re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")),
    # Hostnames, URLs, file names.
    ("url", re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)),
    ("filename", re.compile(r"^[\w-]+\.(?:pdf|txt|csv|png|jpe?g|py|c|cpp|java|json)$",
                            re.IGNORECASE)),
    # VIT-style course codes: letters followed by digits, optional suffix.
    ("course_code", re.compile(r"^[A-Z]{2,5}\d{3,4}[A-Z]?$")),
    # Anything carrying a digit is technical until proven otherwise.
    ("contains_digit", re.compile(r"\d")),
    # Acronyms and protocol names.  Capped at five characters: real
    # acronyms are short (TCP, ICMP, HTTPS), whereas a longer all-caps
    # token is an ordinary word set in capitals and stays correctable.
    ("acronym", re.compile(r"^[A-Z]{2,5}(?:/[A-Z]{2,5})*$")),
    ("slashed", re.compile(r"^\w+(?:/\w+)+$")),
    # Equations, operators, variables.
    ("operator", re.compile(r"[+\-*/=<>^_\\]")),
    ("single_char", re.compile(r"^.$")),
)

# Words that must survive untouched even though they are short or unusual.
ALWAYS_KEEP = frozenset(
    {
        "ack", "arp", "bgp", "cidr", "csma", "dhcp", "dns", "ftp", "http",
        "https", "icmp", "ip", "lan", "mac", "nat", "nack", "ospf", "rip",
        "rtt", "smtp", "snmp", "ssh", "tcp", "udp", "vlan", "vpn", "wan",
        "osi", "mtu", "qos", "sla", "url", "uri", "api", "cpu", "gpu", "ram",
        "co", "bl", "cat", "fat", "vit", "gdp",
    }
)


# --------------------------------------------------------------------------
# Correction knowledge
# --------------------------------------------------------------------------

#: Explicit misreadings seen in real scans.  Lowercase keys; the replacement
#: inherits the casing of the token it replaces.
CORRECTION_DICTIONARY: dict[str, str] = {
    "etwork": "network",
    "etworks": "networks",
    "diflerent": "different",
    "diferent": "different",
    "difterent": "different",
    "iiie": "the",
    "tbe": "the",
    "thc": "the",
    "aud": "and",
    "amd": "and",
    "witli": "with",
    "witb": "with",
    "wliich": "which",
    "whicb": "which",
    "cliart": "chart",
    "tlie": "the",
    "frorn": "from",
    "forrn": "form",
    "rnark": "mark",
    "rnarks": "marks",
    "mnarks": "marks",
    "questiou": "question",
    "questious": "questions",
    "answcr": "answer",
    "explaiu": "explain",
    "explaim": "explain",
    "cxplain": "explain",
    "dcmand": "demand",
    "dernand": "demand",
    "suppiy": "supply",
    "utiiity": "utility",
    "marginai": "marginal",
    "elasticitv": "elasticity",
    "packct": "packet",
    "packcts": "packets",
    "routcr": "router",
    "protocoi": "protocol",
    "congcstion": "congestion",
    "algoritlim": "algorithm",
    "tlirough": "through",
    "witbout": "without",
    "betwecn": "between",
    "bctween": "between",
    "descrihe": "describe",
    "descrlbe": "describe",
    "iayer": "layer",
    "iink": "link",
    "foilowing": "following",
    "foliowing": "following",
    "suitahle": "suitable",
    "diagrarn": "diagram",
    "diagrani": "diagram",
}

#: Character confusions Tesseract makes.  Each is tried on its own; a
#: candidate is accepted only when the lexicon recognises the result.
SUBSTITUTION_RULES: tuple[tuple[str, str], ...] = (
    ("rn", "m"),
    ("m", "rn"),
    ("cl", "d"),
    ("ri", "n"),
    ("ii", "n"),
    ("fl", "ff"),
    ("fi", "ff"),
    ("li", "h"),
    ("vv", "w"),
    ("nn", "m"),
    ("c", "e"),
    ("e", "c"),
    ("i", "l"),
    ("l", "i"),
    ("u", "n"),
    ("n", "u"),
    ("b", "h"),
    ("h", "b"),
    ("t", "f"),
    ("a", "o"),
    ("o", "a"),
    ("s", "g"),
)

#: Characters OCR may drop from the front of a word ("etwork" -> "network").
LEADING_RESTORE = "abcdefghilmnoprstuvw"

#: Single-letter words that OCR fuses onto the next word ("Aconsumer").
#: Deliberately limited to these two: allowing any split would turn
#: "carpet" into "car pet".
FUSED_ARTICLES = ("a", "i")

#: The remainder of a fused pair must be at least this long to be believed.
MIN_FUSED_REMAINDER = 4

_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\S+|\s+", re.UNICODE)
_WORD_RE = re.compile(r"^[^\W\d_]+(?:['’-][^\W\d_]+)*$", re.UNICODE)

MIN_CORRECTABLE_LENGTH = 4


@dataclass(frozen=True)
class Correction:
    """One applied change, kept for audit."""

    original: str
    corrected: str
    rule: str
    index: int

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "corrected": self.corrected,
            "rule": self.rule,
            "index": self.index,
        }


@dataclass
class CorrectionResult:
    """Corrected text plus everything needed to audit or undo it."""

    original_text: str
    corrected_text: str
    corrections: list[Correction] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.corrections)

    def to_dict(self) -> dict:
        return {
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "correction_count": len(self.corrections),
            "corrections": [c.to_dict() for c in self.corrections],
        }


@lru_cache(maxsize=1)
def load_lexicon() -> frozenset[str]:
    """Words considered correct.  Bundled list plus domain supplement."""
    words: set[str] = set(ALWAYS_KEEP)

    for path in (_LEXICON_FILE, _DOMAIN_FILE):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = raw.strip().lower()
            if word and not word.startswith("#"):
                words.add(word)

    return frozenset(words)


def is_protected(token: str) -> str | None:
    """Return the name of the rule protecting ``token``, or ``None``."""
    if not token or not token.strip():
        return "whitespace"

    bare = token.strip(".,;:!?()[]{}\"'")
    if not bare:
        return "punctuation"

    if bare.lower() in ALWAYS_KEEP:
        return "known_acronym"

    for name, pattern in PROTECTED_PATTERNS:
        if pattern.search(bare):
            return name

    if not _WORD_RE.match(bare):
        return "non_word"

    return None


def _match_case(source: str, replacement: str) -> str:
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _candidates(word: str) -> list[tuple[str, str]]:
    """Generate (candidate, rule) pairs for a lowercase word."""
    out: list[tuple[str, str]] = []

    for src, dst in SUBSTITUTION_RULES:
        if src not in word:
            continue
        # Replace one occurrence at a time so a single change is tested.
        start = 0
        while (pos := word.find(src, start)) != -1:
            out.append((word[:pos] + dst + word[pos + len(src):],
                        f"substitution:{src}->{dst}"))
            start = pos + 1

    for char in LEADING_RESTORE:
        out.append((char + word, f"leading_restore:{char}"))

    return out


def correct_token(token: str) -> tuple[str, str | None]:
    """Correct one token.  Returns ``(text, rule)``; ``rule`` is ``None`` if
    the token was left alone."""
    protection = is_protected(token)
    if protection is not None:
        return token, None

    prefix_len = len(token) - len(token.lstrip(".,;:!?()[]{}\"'"))
    prefix = token[:prefix_len]
    rest = token[prefix_len:]
    suffix_len = len(rest) - len(rest.rstrip(".,;:!?()[]{}\"'"))
    core = rest[: len(rest) - suffix_len] if suffix_len else rest
    suffix = rest[len(core):]

    if not core:
        return token, None

    lowered = core.lower()
    lexicon = load_lexicon()

    # Already a real word: never touch it.  This is what makes the pass
    # idempotent - a corrected word is a real word, so a second run is a
    # no-op.
    if lowered in lexicon:
        return token, None

    # The curated dictionary is explicit, hand-checked evidence, so it is
    # applied regardless of token length.
    explicit = CORRECTION_DICTIONARY.get(lowered)
    if explicit:
        return prefix + _match_case(core, explicit) + suffix, "dictionary"

    # The generative rules are far less certain, so they need a token long
    # enough for a single edit to be meaningful.
    if len(core) < MIN_CORRECTABLE_LENGTH:
        return token, None

    # A fused article: "Aconsumer" for "A consumer".  Only an "a" or "i"
    # prefix is considered, and only when what follows is a solid word, so an
    # ordinary word is never torn in two.
    for article in FUSED_ARTICLES:
        if not lowered.startswith(article):
            continue
        remainder = lowered[len(article):]
        if len(remainder) < MIN_FUSED_REMAINDER or remainder not in lexicon:
            continue
        head = core[: len(article)]
        tail = core[len(article):]
        return prefix + f"{head} {tail}" + suffix, "split:fused_article"

    accepted: set[str] = set()
    rule_for: dict[str, str] = {}
    for candidate, rule in _candidates(lowered):
        if candidate != lowered and candidate in lexicon:
            if candidate not in accepted:
                accepted.add(candidate)
                rule_for[candidate] = rule

    # Ambiguity means we do not know, so we keep the original.
    if len(accepted) != 1:
        return token, None

    choice = accepted.pop()
    return prefix + _match_case(core, choice) + suffix, rule_for[choice]


def correct_text(text: str) -> CorrectionResult:
    """Correct a block of OCR text, preserving the original."""
    if not text:
        return CorrectionResult(original_text=text or "", corrected_text=text or "")

    pieces: list[str] = []
    corrections: list[Correction] = []
    offset = 0

    for match in _TOKEN_RE.finditer(text):
        token = match.group(0)
        if token.isspace():
            pieces.append(token)
            offset += len(token)
            continue

        fixed, rule = correct_token(token)
        if rule is not None and fixed != token:
            corrections.append(
                Correction(original=token, corrected=fixed, rule=rule, index=offset)
            )
        pieces.append(fixed)
        offset += len(token)

    return CorrectionResult(
        original_text=text,
        corrected_text="".join(pieces),
        corrections=corrections,
    )


def correct_lines(lines: list[str]) -> tuple[list[str], list[Correction]]:
    """Correct a list of lines, returning the corrected lines and the audit."""
    corrected: list[str] = []
    audit: list[Correction] = []

    for line in lines:
        result = correct_text(line)
        corrected.append(result.corrected_text)
        audit.extend(result.corrections)

    return corrected, audit
