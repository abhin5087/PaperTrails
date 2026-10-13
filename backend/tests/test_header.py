"""Header parsing across OCR damage and layout variation."""

import pytest

from app.services.header import normalise_course_code, parse_header

BHUM_OCR = """SCHOOL OF SOCIAL SCIENCES AND LANGUAGES
Continuous Assessment Test-1 - Winter Semester 2024-2025
Course Code: BHUM1O3L
Course Name: Microeconomics
Class Number: CH2024250100123 Slot: F2
Date: 16-02-2024 Time: 2:00 PM - 3:30 PM
Duration: 90 Minutes Maximum Marks: 50
Answer ALL the Questions (5 X 10 = 50 Marks)"""

BCSE_NATIVE = """SCHOOL OF COMPUTER SCIENCE AND ENGINEERING
Final Assessment Test (FAT) - Fall Inter Semester 2022-2023
Course Code: BCSE308L
Course Name: COMPUTER NETWORKS
Slot: C2        Duration: 3 Hours        Maximum Marks: 100"""


class TestCourseCode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("BHUM103L", "BHUM103L"),
            ("BCSE308L", "BCSE308L"),
            ("BHUM1O3L", "BHUM103L"),   # letter O read for zero
            ("8HUM103L", "BHUM103L"),   # digit 8 read for B
            ("BHUM1O3L", "BHUM103L"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert normalise_course_code(raw) == expected

    def test_legitimate_codes_survive_untouched(self):
        for code in ("BCSE308L", "BMAT205L", "BHUM103L", "BECE204P"):
            assert normalise_course_code(code) == code

    def test_non_code_tokens_are_refused(self):
        assert normalise_course_code("MICROECONOMICS") is None
        assert normalise_course_code("12345") is None

    def test_repaired_code_is_flagged_as_unconfident(self):
        header = parse_header(BHUM_OCR)
        assert header.get("course_code") == "BHUM103L"
        assert header.fields["course_code"].confident is False
        assert header.fields["course_code"].raw == "BHUM1O3L"


class TestExamType:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Continuous Assessment Test-1", "Continuous Assessment Test-1"),
            ("Continuous Assessment Test - I", "Continuous Assessment Test-1"),
            ("CAT-1", "Continuous Assessment Test-1"),
            ("CAT - II", "Continuous Assessment Test-2"),
            ("Final Assessment Test", "Final Assessment Test"),
            ("FAT", "Final Assessment Test"),
        ],
    )
    def test_arabic_and_roman_labels_agree(self, text, expected):
        assert parse_header(f"{text}\nCourse Code: BHUM103L").get("exam_type") == expected


class TestSemester:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Winter Semester 2024-2025", "Winter Semester"),
            ("Fall Inter Semester 2022-2023", "Fall Inter Semester"),
            ("Semester: Winter", "Winter Semester"),
            ("Semester - Fall Inter", "Fall Inter Semester"),
        ],
    )
    def test_word_order_variations(self, text, expected):
        assert parse_header(text).get("semester") == expected

    def test_academic_year_range(self):
        assert parse_header("Winter Semester 2024-2025").get("academic_year") == "2024-2025"

    def test_two_digit_year_is_expanded(self):
        assert parse_header("Fall Semester 2022-23").get("academic_year") == "2022-2023"

    def test_month_year_form(self):
        header = parse_header("Winter Semester, February 2024\nCourse Code: BHUM103L")
        assert header.get("semester") == "Winter Semester"
        assert header.get("academic_year") == "2024"


class TestMaxMarks:
    def test_plain_value(self):
        assert parse_header("Maximum Marks: 100").get("max_marks") == "100"

    def test_ocr_digit_confusion_is_repaired(self):
        assert parse_header("Maximum Marks: 5O").get("max_marks") == "50"

    def test_self_consistent_expression_beats_a_damaged_field(self):
        """'(5 X 10 = 50)' checks out internally; a lone '8O' does not."""
        header = parse_header("Maximum Marks: 8O\nAnswer ALL (5 X 10 = 50 Marks)")
        assert header.get("max_marks") == "50"
        assert header.fields["max_marks"].source == "expression"
        assert any("disagrees" in note for note in header.unparsed)

    def test_inconsistent_expression_is_ignored(self):
        """'5 X 10 = 70' contradicts itself, so the stated field wins."""
        header = parse_header("Maximum Marks: 50\nAnswer ALL (5 X 10 = 70 Marks)")
        assert header.get("max_marks") == "50"


class TestDuration:
    def test_duration_does_not_bleed_into_the_next_field(self):
        header = parse_header("Duration: 90 Minutes Maximum Marks: 50")
        assert header.get("duration") == "90 Minutes"
        assert header.get("max_marks") == "50"

    def test_hours_form(self):
        assert parse_header("Duration: 3 Hours  Maximum Marks: 100").get(
            "duration"
        ) == "3 Hours"


class TestCompressedText:
    COMPRESSED = (
        "CourseCode:BHUM103LCourseName:MicroeconomicsWinterSemester2024-2025"
        "Duration:90MinutesMaximumMarks:50"
    )

    def test_fields_are_read_without_spaces(self):
        header = parse_header(self.COMPRESSED)
        assert header.get("course_code") == "BHUM103L"
        assert header.get("course_name") == "Microeconomics"
        assert header.get("semester") == "Winter Semester"
        assert header.get("max_marks") == "50"
        assert header.get("duration") == "90 Minutes"

    def test_spaced_multiword_course_name_is_not_truncated(self):
        header = parse_header("Course Name: Introduction to Computer Networks")
        assert header.get("course_name") == "Introduction to Computer Networks"


class TestWholeHeaders:
    def test_scanned_microeconomics_header(self):
        header = parse_header(BHUM_OCR)
        assert header.get("course_code") == "BHUM103L"
        assert header.get("course_name") == "Microeconomics"
        assert header.get("exam_type") == "Continuous Assessment Test-1"
        assert header.get("semester") == "Winter Semester"
        assert header.get("academic_year") == "2024-2025"
        assert header.get("max_marks") == "50"
        assert header.get("duration") == "90 Minutes"
        assert header.get("exam_date") == "16-02-2024"
        assert header.get("slot") == "F2"

    def test_native_networks_header(self):
        header = parse_header(BCSE_NATIVE)
        assert header.get("course_code") == "BCSE308L"
        assert header.get("course_name") == "COMPUTER NETWORKS"
        assert header.get("exam_type") == "Final Assessment Test"
        assert header.get("semester") == "Fall Inter Semester"
        assert header.get("max_marks") == "100"
        assert header.get("duration") == "3 Hours"


class TestHonesty:
    def test_missing_fields_are_absent_not_invented(self):
        header = parse_header("Course Code: BHUM103L")
        for absent in ("exam_type", "semester", "max_marks", "duration", "exam_date"):
            assert not header.has(absent)
            assert header.get(absent) is None

    def test_empty_text_yields_an_empty_header(self):
        header = parse_header("")
        assert len(header) == 0
        assert header.completeness == 0.0

    def test_raw_text_is_retained_for_investigation(self):
        header = parse_header(BHUM_OCR)
        assert "Microeconomics" in header.raw_text

    def test_every_field_keeps_its_raw_and_source(self):
        header = parse_header(BCSE_NATIVE)
        for name, parsed in header.fields.items():
            assert parsed.raw, f"{name} lost its raw text"
            assert parsed.source, f"{name} lost its source"
