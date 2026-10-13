"""Marks parsing: resolve what the text supports, preserve what it does not."""

import pytest

from app.services.marks import (
    Marks,
    combine,
    extract_marks,
    find_marks,
    parse_marks_token,
    split_trailing_marks,
)


class TestCleanMarks:
    @pytest.mark.parametrize(
        "token,total,parts",
        [
            ("10", 10, [10]),
            ("5", 5, [5]),
            ("5+5", 10, [5, 5]),
            ("7+3", 10, [7, 3]),
            ("2 + 8", 10, [2, 8]),
            ("3+3+4", 10, [3, 3, 4]),
        ],
    )
    def test_parses_clean_values(self, token, total, parts):
        parsed = parse_marks_token(token)
        assert parsed.resolved
        assert parsed.total == total
        assert parsed.parts == parts
        assert parsed.raw == " ".join(token.split())

    def test_raw_is_always_preserved(self):
        assert parse_marks_token("5+5").raw == "5+5"
        assert parse_marks_token("743").raw == "743"


class TestAmbiguousMarks:
    def test_743_is_not_resolved_to_a_number(self):
        """OCR dropping the '+' in 7+3 must not become a confident 743."""
        parsed = parse_marks_token("743")
        assert not parsed.resolved
        assert parsed.total is None
        assert parsed.raw == "743"
        assert "ambiguous" in parsed.reason

    def test_ambiguous_reason_names_the_candidates(self):
        """The reason must name the reading the scan most likely damaged."""
        reason = parse_marks_token("743").reason
        assert "7+3" in reason

    def test_fused_two_digit_sum_is_unresolved(self):
        """'5+5' read as '55' is over the ceiling, so it stays unresolved."""
        parsed = parse_marks_token("55")
        assert not parsed.resolved
        assert "5+5" in parsed.reason

    def test_sum_over_the_ceiling_is_unresolved(self):
        parsed = parse_marks_token("40+40")
        assert not parsed.resolved
        assert parsed.raw == "40+40"

    def test_unparseable_text_keeps_its_raw(self):
        parsed = parse_marks_token("f1ve")
        assert not parsed.resolved
        assert parsed.raw == "f1ve"


class TestFindMarks:
    @pytest.mark.parametrize(
        "text,total",
        [
            ("Explain demand. (5 Marks)", 5),
            ("Explain demand. [10]", 10),
            ("Explain demand. (10)", 10),
            ("Explain demand. Marks: 8", 8),
            ("Explain demand. [5+5]", 10),
        ],
    )
    def test_delimited_and_labelled(self, text, total):
        assert find_marks(text).total == total

    def test_distribution_banner_is_not_question_marks(self):
        """'(5 X 10 = 50 Marks)' is the paper total, not this question's."""
        assert find_marks("Answer ALL the Questions (5 X 10 = 50 Marks)").raw is None


class TestTrailingMarks:
    def test_bare_trailing_number(self):
        head, parsed = split_trailing_marks("Define the law of demand. 10")
        assert head == "Define the law of demand."
        assert parsed.total == 10

    def test_bare_trailing_sum(self):
        head, parsed = split_trailing_marks("Distinguish the two cases. 5+5")
        assert head == "Distinguish the two cases."
        assert parsed.parts == [5, 5]

    def test_number_only_line_is_not_marks(self):
        _, parsed = split_trailing_marks("10")
        assert parsed.raw is None

    def test_does_not_absorb_an_equation_result(self):
        _, parsed = split_trailing_marks("Given that x + y = 12")
        assert parsed.raw is None

    def test_ip_address_is_not_marks(self):
        head, parsed = split_trailing_marks("The gateway is 192.168.1.1")
        assert parsed.raw is None
        assert head == "The gateway is 192.168.1.1"


class TestExtractMarks:
    def test_marks_notation_is_removed_from_the_body(self):
        text, parsed = extract_marks("Explain elasticity of demand. (10 Marks)")
        assert parsed.total == 10
        assert "Marks" not in text
        assert text == "Explain elasticity of demand."

    def test_question_number_is_not_absorbed(self):
        text, parsed = extract_marks("Compare OSI with TCP/IP at layer 3. 5")
        assert parsed.total == 5
        assert "layer 3" in text


class TestCombine:
    def test_sums_resolved_children(self):
        rolled = combine([parse_marks_token("5"), parse_marks_token("5")])
        assert rolled.resolved and rolled.total == 10

    def test_withholds_total_when_a_child_is_unresolved(self):
        """A parent total built on a guess would itself be a guess."""
        rolled = combine([parse_marks_token("5"), parse_marks_token("743")])
        assert not rolled.resolved
        assert rolled.total is None

    def test_no_children_is_missing_not_zero(self):
        assert combine([]).total is None
