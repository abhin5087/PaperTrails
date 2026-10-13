"""OCR noise correction: fix prose, never touch technical material."""

import pytest

from app.services.ocr_correction import (
    correct_text,
    correct_token,
    is_protected,
    load_lexicon,
)


class TestObviousErrors:
    @pytest.mark.parametrize(
        "bad,good",
        [
            ("etwork", "network"),
            ("diflerent", "different"),
            ("tbe", "the"),
            ("questiou", "question"),
            ("packct", "packet"),
            ("diagrarn", "diagram"),
        ],
    )
    def test_dictionary_corrections(self, bad, good):
        assert correct_text(bad).corrected_text == good

    def test_generated_candidate_correction(self):
        """'difler' is not in the dictionary; the fl->ff rule finds 'differ'."""
        result = correct_text("TCP and UDP difler here.")
        assert "differ" in result.corrected_text
        assert result.corrections[0].rule == "substitution:fl->ff"

    def test_corrected_text_reads_naturally(self):
        result = correct_text("The etwork uses a diflerent protocol.")
        assert result.corrected_text == "The network uses a different protocol."

    def test_casing_is_preserved(self):
        assert correct_text("Etwork").corrected_text == "Network"
        assert correct_text("ETWORK").corrected_text == "NETWORK"

    def test_trailing_punctuation_survives(self):
        assert correct_text("etwork.").corrected_text == "network."
        assert correct_text("(etwork)").corrected_text == "(network)"


class TestProtectedMaterial:
    @pytest.mark.parametrize(
        "text",
        [
            "10.0.0.1",
            "192.168.10.20",
            "255.255.255.0",
            "172.16.0.0/16",
            "00:1A:2B:3C:4D:5E",
        ],
    )
    def test_addresses_are_untouched(self, text):
        assert correct_text(text).corrected_text == text
        assert not correct_text(text).changed

    @pytest.mark.parametrize("code", ["BHUM103L", "BCSE308L", "BMAT205L", "BECE204P"])
    def test_course_codes_are_untouched(self, code):
        assert correct_text(code).corrected_text == code

    @pytest.mark.parametrize(
        "token",
        ["TCP", "UDP", "ARP", "ICMP", "CSMA/CD", "TCP/IP", "OSI", "DNS", "BGP", "OSPF"],
    )
    def test_protocols_and_acronyms_are_untouched(self, token):
        assert correct_text(token).corrected_text == token

    @pytest.mark.parametrize(
        "text",
        ["5+5", "7+3", "2 + 8", "x = y + 2z", "f(x) = ax^2 + bx + c", "n-1", "O(n log n)"],
    )
    def test_equations_and_marks_are_untouched(self, text):
        assert correct_text(text).corrected_text == text

    @pytest.mark.parametrize("label", ["1.", "(a)", "(iii)", "Q13", "13(a)"])
    def test_question_labels_are_untouched(self, label):
        assert correct_text(label).corrected_text == label

    @pytest.mark.parametrize("text", ["16-02-2024", "2:00 PM", "2024-2025", "report.pdf"])
    def test_dates_times_and_filenames_are_untouched(self, text):
        assert correct_text(text).corrected_text == text

    def test_protection_reason_is_reported(self):
        assert is_protected("10.0.0.1") == "ip_address"
        assert is_protected("BHUM103L") == "course_code"
        assert is_protected("TCP") == "known_acronym"
        assert is_protected("ordinary") is None


class TestConservatism:
    def test_real_words_are_never_rewritten(self):
        for word in ("demand", "supply", "router", "congestion", "elasticity"):
            assert correct_token(word) == (word, None)

    def test_ambiguous_tokens_keep_the_original(self):
        """More than one lexicon-valid candidate means we do not know."""
        text = "xqzj"
        assert correct_text(text).corrected_text == text

    def test_short_tokens_are_left_alone(self):
        assert correct_token("abc") == ("abc", None)

    def test_unknown_long_words_are_left_alone(self):
        token = "zzzqqqwwx"
        assert correct_token(token) == (token, None)


class TestAuditAndIdempotence:
    SAMPLE = "The etwork layer uses a diflerent protocol at 10.0.0.1 for 5+5 marks."

    def test_original_text_is_preserved(self):
        result = correct_text(self.SAMPLE)
        assert result.original_text == self.SAMPLE
        assert result.corrected_text != self.SAMPLE

    def test_every_change_is_recorded(self):
        result = correct_text(self.SAMPLE)
        assert len(result.corrections) == 2
        for change in result.corrections:
            assert change.original and change.corrected and change.rule
            assert self.SAMPLE[change.index:].startswith(change.original)

    def test_applying_twice_changes_nothing_further(self):
        once = correct_text(self.SAMPLE).corrected_text
        twice = correct_text(once)
        assert twice.corrected_text == once
        assert twice.corrections == []

    def test_technical_content_survives_the_full_sentence(self):
        corrected = correct_text(self.SAMPLE).corrected_text
        assert "10.0.0.1" in corrected
        assert "5+5" in corrected
        assert "network" in corrected and "different" in corrected

    def test_empty_input(self):
        assert correct_text("").corrected_text == ""


class TestLexicon:
    def test_bundled_lexicon_loads(self):
        lexicon = load_lexicon()
        assert len(lexicon) > 1000
        for word in ("network", "different", "demand", "elasticity"):
            assert word in lexicon

    def test_domain_terms_are_present(self):
        lexicon = load_lexicon()
        for word in ("congestion", "subnet", "microeconomics", "equimarginal"):
            assert word in lexicon


class TestFusedWords:
    """OCR drops the space after a one-letter word: 'A consumer' -> 'Aconsumer'."""

    @pytest.mark.parametrize(
        "fused,split",
        [
            ("Aconsumer", "A consumer"),
            ("aconsumer", "a consumer"),
            ("Adiagram", "A diagram"),
            ("Irecommend", "I recommend"),
        ],
    )
    def test_fused_article_is_separated(self, fused, split):
        assert correct_text(fused).corrected_text == split

    @pytest.mark.parametrize(
        "word", ["carpet", "around", "about", "apart", "item", "image", "income"]
    )
    def test_ordinary_words_are_never_torn_apart(self, word):
        assert correct_text(word).corrected_text == word

    def test_short_remainders_are_refused(self):
        assert correct_text("Acat").corrected_text == "Acat"

    def test_the_split_is_recorded(self):
        result = correct_text("Aconsumer spends her income.")
        assert result.corrections[0].rule == "split:fused_article"

    def test_splitting_is_idempotent(self):
        once = correct_text("Aconsumer spends her income.").corrected_text
        assert correct_text(once).corrected_text == once
