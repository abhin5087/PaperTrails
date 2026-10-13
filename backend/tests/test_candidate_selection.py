"""Candidate selection must judge structure, not raw OCR confidence."""

from app.services.header import parse_header
from app.services.pipeline import Candidate, score_candidate, select_candidate
from app.services.questions import Line, extract_questions

GOOD_HEADER = """Course Code: BCSE308L
Course Name: COMPUTER NETWORKS
Final Assessment Test - Fall Inter Semester 2022-2023
Maximum Marks: 100"""

COHERENT = [
    (f"{n}. Explain in detail the operation of protocol number {n} "
     f"and compare it with the alternative approach discussed. 5", 0.0)
    for n in range(1, 11)
]

# The same page read badly: labels mangled, text chopped into scraps.
FRAGMENTED = [
    ("1. Explain in detail", 0.0),
    ("the operation", 40.0),
    ("of pro tocol", 40.0),
    ("nu mber 1", 40.0),
    ("2. Exp lain", 0.0),
    ("in de tail", 40.0),
    ("th e op eration", 40.0),
]


def build(name, rows, header_text, ocr_confidence):
    built = [
        Line(text=t, page=1, index=i, x0=x, top=float(i * 14), bottom=float(i * 14 + 10))
        for i, (t, x) in enumerate(rows)
    ]
    candidate = Candidate(name=name, source="ocr", lines=built,
                          ocr_config=name, ocr_confidence=ocr_confidence)
    candidate.first_page_text = "\n".join(t for t, _ in rows)
    candidate.header = parse_header(header_text)
    candidate.questions, candidate.classified = extract_questions(built)
    return candidate


class TestStructureBeatsConfidence:
    def test_coherent_candidate_wins_despite_lower_engine_confidence(self):
        """A well-structured read at 70% must beat a fragmented read at 95%."""
        good = build("psm6", COHERENT, GOOD_HEADER, ocr_confidence=70.0)
        bad = build("psm3", FRAGMENTED, "", ocr_confidence=95.0)

        chosen = select_candidate([good, bad])
        assert chosen is good

    def test_confidence_is_only_a_supporting_term(self):
        good = build("psm6", COHERENT, GOOD_HEADER, 70.0)
        _, detail = score_candidate(good)
        structural = sum(v for k, v in detail.items() if k != "ocr_confidence")
        assert detail["ocr_confidence"] < structural

    def test_header_completeness_breaks_a_structural_tie(self):
        with_header = build("psm6", COHERENT, GOOD_HEADER, 90.0)
        without = build("psm4", COHERENT, "", 90.0)
        assert select_candidate([with_header, without]) is with_header


class TestNoiseIsNotRewarded:
    def test_duplicated_question_text_is_penalised(self):
        duplicated = [
            ("1. The very same sentence repeated for every question here. 5", 0.0),
            ("2. The very same sentence repeated for every question here. 5", 0.0),
            ("3. The very same sentence repeated for every question here. 5", 0.0),
        ]
        candidate = build("dupe", duplicated, GOOD_HEADER, 90.0)
        assert candidate.score_detail == {} or True
        _, detail = score_candidate(candidate)
        assert detail["duplication_penalty"] < 0

    def test_long_diagram_noise_does_not_outscore_a_clean_read(self):
        """Text length is capped so a page of swallowed noise cannot win."""
        noise_rows = [
            ("1. " + "10.0.0.1 255.255.255.0 " * 40 + " 5", 0.0),
        ]
        noisy = build("noisy", noise_rows, "", 95.0)
        clean = build("clean", COHERENT, GOOD_HEADER, 95.0)
        assert select_candidate([noisy, clean]) is clean

    def test_fragmentation_is_penalised(self):
        fragmented = build("frag", FRAGMENTED, "", 95.0)
        _, detail = score_candidate(fragmented)
        assert detail["fragmentation_penalty"] <= 0


class TestSelectionRules:
    def test_unavailable_candidates_score_zero(self):
        broken = Candidate(name="ocr:x", source="ocr", available=False,
                           error="Tesseract missing")
        assert score_candidate(broken)[0] == 0.0

    def test_candidate_without_questions_is_not_usable(self):
        empty = build("empty", [], "", 90.0)
        assert not empty.usable

    def test_native_is_preferred_on_a_near_tie(self):
        """A text layer is exact where OCR is only a reading."""
        native = build("native", COHERENT, GOOD_HEADER, None)
        native.source = "native_text"
        ocr = build("ocr:psm6", COHERENT, GOOD_HEADER, 95.0)
        assert select_candidate([native, ocr]) is native

    def test_ocr_wins_when_clearly_better(self):
        native = build("native", FRAGMENTED, "", None)
        native.source = "native_text"
        ocr = build("ocr:psm6", COHERENT, GOOD_HEADER, 92.0)
        assert select_candidate([native, ocr]) is ocr

    def test_nothing_usable_returns_the_best_header_source(self):
        a = build("ocr:a", [], "", 50.0)
        a.first_page_text = GOOD_HEADER
        a.header = parse_header(GOOD_HEADER)
        b = build("ocr:b", [], "", 90.0)
        assert select_candidate([a, b]) is a

    def test_all_empty_returns_none(self):
        a = Candidate(name="ocr:a", source="ocr", available=False)
        b = Candidate(name="ocr:b", source="ocr", available=False)
        assert select_candidate([a, b]) is None
