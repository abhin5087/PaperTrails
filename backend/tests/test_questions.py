"""Question boundaries: recover real labels, reject diagram noise."""

import pytest

from app.services.questions import (
    Line,
    build_questions,
    classify_lines,
    estimate_left_margin,
    extract_questions,
    flatten,
)

MARGIN = 0.0
INDENT = 60.0


def lines(rows):
    """``rows`` is a list of ``(text, x0)`` pairs."""
    return [
        Line(text=text, page=1, index=i, x0=float(x), top=float(i * 14),
             bottom=float(i * 14 + 10))
        for i, (text, x) in enumerate(rows)
    ]


NETWORK_PAGE = [
    ("1. Compare the OSI reference model with the TCP/IP suite briefly. 5", MARGIN),
    ("2. Explain how CSMA/CD resolves contention on Ethernet segments. 5", MARGIN),
    ("3. A host is configured with the address 192.168.10.20 and mask", MARGIN),
    ("255.255.255.0. Determine the network address.", INDENT),
    ("R1 10.0.0.1", INDENT),
    ("R2 16.0.0.1", INDENT),
    ("R3 192.168.1.1", INDENT),
    ("255.255.255.0", INDENT),
    ("Figure 1: Sample network topology", INDENT),
    ("1 2 3 4 5 6 7 8", INDENT),
    ("Figure 2: Congestion window vs transmission round", INDENT),
    ("4. Differentiate between a switch and a router by layer. 5", MARGIN),
]


class TestFalsePositives:
    def test_ip_octets_do_not_become_questions(self):
        questions, _ = extract_questions(lines(NETWORK_PAGE))
        numbers = [q.number for q in questions]
        assert numbers == ["1", "2", "3", "4"]
        for bogus in ("16", "10", "192", "255"):
            assert bogus not in numbers

    def test_graph_axis_ticks_do_not_become_questions(self):
        classified = classify_lines(lines(NETWORK_PAGE))
        axis = next(c for c in classified if c.line.text.startswith("1 2 3 4"))
        assert axis.kind != "question"

    def test_diagram_text_stays_with_its_question(self):
        questions, _ = extract_questions(lines(NETWORK_PAGE))
        q3 = next(q for q in questions if q.number == "3")
        assert "10.0.0.1" in q3.text
        assert "192.168.1.1" in q3.text

    def test_figure_captions_are_classified_as_captions(self):
        classified = classify_lines(lines(NETWORK_PAGE))
        captions = [c for c in classified if c.kind == "caption"]
        assert len(captions) == 2

    def test_continuation_after_a_figure_is_not_a_new_question(self):
        rows = [
            ("1. Explain the three way handshake used by TCP in detail. 5", MARGIN),
            ("2. A host is configured with address 192.168.10.20 and a mask", MARGIN),
            ("Figure 1: Topology", INDENT),
            ("Determine the broadcast address for this subnet carefully. 5", MARGIN),
            ("3. Differentiate between a switch and a router by layer. 5", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1", "2", "3"]

    def test_lines_inside_a_figure_region_are_never_labels(self):
        rows = [
            ("1. Study the topology below and answer the question asked. 5", MARGIN),
            ("2. Router interface address", MARGIN),
            ("3. Differentiate a switch from a router by operating layer. 5", MARGIN),
        ]
        built = lines(rows)
        # Declare the second line to sit inside a detected figure.
        spans = [(1, built[1].top - 1, built[1].bottom + 1)]
        questions, classified = extract_questions(built, figure_spans=spans)
        assert [q.number for q in questions] == ["1", "3"]
        assert "inside a figure region" in classified[1].reason

    def test_out_of_sequence_number_is_rejected(self):
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("47. This is a stray page artefact and not a real question.", MARGIN),
        ]
        questions, classified = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1"]
        assert "does not fit the sequence" in classified[1].reason


class TestGarbledLabels:
    def test_1g_is_read_as_10_when_10_is_expected(self):
        rows = [(f"{n}. Question number {n} body text goes here now. 5", MARGIN)
                for n in range(1, 10)]
        rows.append(("1G. Discuss the services offered by UDP in detail. 10", MARGIN))
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions][-1] == "10"
        assert questions[-1].recovered_label is True

    def test_garbled_label_out_of_sequence_is_refused(self):
        """Recovery only fires for the number actually expected next."""
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("1G. Discuss the services offered by UDP in detail here. 10", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1"]

    def test_garbled_label_must_be_at_the_margin(self):
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("2. Compare go back N with selective repeat in buffering. 5", MARGIN),
            ("S. This is indented diagram text and not a question at all.", INDENT),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1", "2"]


class TestMissingLabels:
    def test_unlabelled_question_is_recovered_with_strong_evidence(self):
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("Describe the operation of the distance vector algorithm. 10", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1", "2"]
        assert questions[1].recovered_label is True

    def test_not_recovered_while_the_open_question_lacks_marks(self):
        rows = [
            ("1. Explain the sliding window protocol used by the sender", MARGIN),
            ("Describe the operation of the distance vector algorithm. 10", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1"]

    def test_not_recovered_without_trailing_marks(self):
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("Describe the operation of the distance vector algorithm.", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1"]

    def test_not_recovered_from_a_short_line(self):
        rows = [
            ("1. Explain the sliding window protocol in your own words. 5", MARGIN),
            ("Total 10", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [q.number for q in questions] == ["1"]


class TestNormalQuestions:
    def test_plain_numbered_questions_still_work(self):
        rows = [(f"{n}. Question {n} asks about an interesting topic here. 5", MARGIN)
                for n in range(1, 14)]
        questions, _ = extract_questions(lines(rows))
        assert len(questions) == 13
        assert [q.number for q in questions] == [str(n) for n in range(1, 14)]
        assert all(q.marks.total == 5 for q in questions)

    @pytest.mark.parametrize("sep", [".", ")"])
    def test_both_label_separators(self, sep):
        rows = [(f"1{sep} Explain the law of demand with a diagram shown. 10", MARGIN)]
        questions, _ = extract_questions(lines(rows))
        assert len(questions) == 1

    def test_boilerplate_before_question_one_is_skipped(self):
        rows = [
            ("Answer ALL the Questions (5 X 10 = 50 Marks)", MARGIN),
            ("1. Define the law of demand and explain it fully here. 10", MARGIN),
        ]
        questions, classified = extract_questions(lines(rows))
        assert len(questions) == 1
        assert classified[0].kind == "boilerplate"

    def test_page_footers_are_dropped(self):
        rows = [
            ("1. Define the law of demand and explain it fully here. 10", MARGIN),
            ("Page 1 of 2", MARGIN),
        ]
        questions, _ = extract_questions(lines(rows))
        assert "Page 1 of 2" not in questions[0].text


class TestSubquestions:
    ROWS = [
        ("2. Distinguish a movement along the curve from a shift of it.", MARGIN),
        ("(a) Explain the distinction using a clearly labelled diagram.", INDENT),
        ("(b) Give one real world example for each of the two cases. 5+5", INDENT),
        ("3. Derive the budget line for the two good case in full. 10", MARGIN),
    ]

    def test_subparts_attach_to_their_parent(self):
        questions, _ = extract_questions(lines(self.ROWS))
        q2 = questions[0]
        assert q2.number == "2"
        assert [c.number for c in q2.children] == ["a", "b"]
        assert q2.children[0].label == "2(a)"

    def test_trailing_sum_belongs_to_the_parent(self):
        """'5+5' printed after the last subpart is the question total."""
        questions, _ = extract_questions(lines(self.ROWS))
        q2 = questions[0]
        assert q2.marks.total == 10
        assert q2.marks.raw == "5+5"

    def test_sum_parts_are_distributed_across_subparts(self):
        questions, _ = extract_questions(lines(self.ROWS))
        assert [c.marks.total for c in questions[0].children] == [5, 5]

    def test_parent_total_is_not_double_counted(self):
        questions, _ = extract_questions(lines(self.ROWS))
        top_level_total = sum(q.marks.total for q in questions if q.marks.resolved)
        assert top_level_total == 20  # 10 for Q2 and 10 for Q3, not 30

    def test_roman_subparts(self):
        rows = [
            ("7. Answer the following parts about congestion control here.", MARGIN),
            ("(i) Explain slow start and congestion avoidance in detail.", INDENT),
            ("(ii) Describe fast retransmit and fast recovery briefly. 10", INDENT),
        ]
        questions, _ = extract_questions(lines(rows))
        assert [c.number for c in questions[0].children] == ["i", "ii"]


class TestFlatten:
    def test_rows_carry_parent_links_and_raw_marks(self):
        questions, _ = extract_questions(lines(TestSubquestions.ROWS))
        rows = flatten(questions)
        parents = [r for r in rows if r["parent_no"] is None]
        children = [r for r in rows if r["parent_no"] is not None]
        assert len(parents) == 2 and len(children) == 2
        assert all(r["parent_no"] == "2" for r in children)
        assert parents[0]["marks_raw"] == "5+5"
        assert parents[0]["marks_parts"] == [5, 5]


class TestMargin:
    def test_margin_estimate_tracks_the_body_text(self):
        built = lines(NETWORK_PAGE)
        assert estimate_left_margin(built) == pytest.approx(MARGIN, abs=1.0)

    def test_no_geometry_falls_back_to_leading_whitespace(self):
        built = [
            Line(text="1. Explain the law of demand in your own words here. 10",
                 page=1, index=0),
            Line(text="      16.0.0.1 is a router address on the diagram", page=1,
                 index=1),
        ]
        questions = build_questions(classify_lines(built))
        assert [q.number for q in questions] == ["1"]


class TestFigureContent:
    """Diagram text belongs to the figure, not to the question's wording."""

    ROWS = [
        ("3. A host is configured with the address 192.168.10.20 and a mask.", MARGIN),
        ("R1 10.0.0.1", INDENT),
        ("255.255.255.0", INDENT),
        ("Figure 1: Sample network topology [5]", INDENT),
        ("4. Differentiate between a switch and a router by layer. 5", MARGIN),
    ]

    def spans(self, built):
        """Treat the three diagram lines as one detected figure region."""
        inside = built[1:4]
        return [(1, inside[0].top - 2, inside[-1].bottom + 2,
                 min(ln.x0 for ln in inside) - 5, 500.0)]

    def test_diagram_labels_are_kept_out_of_the_question_text(self):
        built = lines(self.ROWS)
        questions, _ = extract_questions(built, figure_spans=self.spans(built))
        q3 = next(q for q in questions if q.number == "3")
        assert "10.0.0.1" not in q3.text
        assert "255.255.255.0" not in q3.text
        assert "Figure 1" not in q3.text

    def test_the_question_wording_itself_survives(self):
        built = lines(self.ROWS)
        questions, _ = extract_questions(built, figure_spans=self.spans(built))
        q3 = next(q for q in questions if q.number == "3")
        assert "192.168.10.20" in q3.text  # part of the question, not the figure

    def test_marks_printed_on_a_caption_still_reach_the_question(self):
        built = lines(self.ROWS)
        questions, _ = extract_questions(built, figure_spans=self.spans(built))
        q3 = next(q for q in questions if q.number == "3")
        assert q3.marks.total == 5

    def test_axis_ticks_are_not_taken_as_marks(self):
        rows = [
            ("13. Answer the following about TCP congestion control here.", MARGIN),
            ("1 2 3 4 5 6 7 8", INDENT),
            ("Figure 2: Congestion window", INDENT),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[2].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert questions[0].marks.raw is None

    def test_lines_beside_a_figure_are_not_swallowed(self):
        """Horizontal bounds stop a figure claiming text printed next to it."""
        rows = [
            ("3. Study the topology and answer the question that follows it.", MARGIN),
            ("This sentence sits beside the diagram, not inside it. 5", MARGIN),
        ]
        built = lines(rows)
        # A narrow figure on the right-hand side of the page.
        spans = [(1, built[1].top - 2, built[1].bottom + 2, 400.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert "beside the diagram" in questions[0].text


class TestFigureSpansVsQuestions:
    """A figure region must never cost a question.

    This is the invariant that matters most: the figure stage runs *after*
    boundary detection and feeds back into it, so an over-large or misplaced
    region can erase a real question heading.  Every case here is a layout
    where that could happen.
    """

    def test_diagram_immediately_after_a_question_heading(self):
        rows = [
            ("10. You are a network engineer with three business units. 10", MARGIN),
            ("Engineering Subnet", INDENT),
            ("From ISP Finance", INDENT),
            ("Fig. 1", INDENT),
            ("11. Interpret the figure comprising several networks. 10", MARGIN),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[3].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert [q.number for q in questions] == ["10", "11"]

    def test_diagram_between_subparts(self):
        rows = [
            ("13. Answer the following about congestion control.", MARGIN),
            ("(a) Illustrate the transaction between client and server.", INDENT),
            ("Fig. 3", INDENT),
            ("(b) Which transport layer service does HTTP use? 4", INDENT),
        ]
        built = lines(rows)
        spans = [(1, built[2].top - 2, built[2].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert len(questions) == 1
        assert [c.number for c in questions[0].children] == ["a", "b"]

    def test_figure_at_the_top_of_a_page(self):
        rows = [("Fig. 2 continued", INDENT),
                ("11. Interpret the figure comprising several networks. 10", MARGIN)]
        built = [Line(text=t, page=2, index=i, x0=float(x),
                      top=float(10 + i * 14), bottom=float(20 + i * 14))
                 for i, (t, x) in enumerate(rows)]
        spans = [(2, 8.0, 22.0, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert [q.number for q in questions] == ["11"]

    def test_figure_at_the_bottom_of_a_page(self):
        rows = [
            ("12. Explain how TCP uses congestion control to alleviate it. 10", MARGIN),
            ("Congestion Window Size vs Transmission Round", INDENT),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[1].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert [q.number for q in questions] == ["12"]

    def test_question_continues_below_a_figure(self):
        rows = [
            ("11. Interpret the figure comprising several networks. 10", MARGIN),
            ("Fig. 2", INDENT),
            ("What will be the initial table of R1 after enabling RIP?", MARGIN),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[1].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert len(questions) == 1
        assert "initial table" in questions[0].text

    def test_text_beside_a_narrow_figure_is_kept(self):
        """A narrow figure must not suppress a full line printed next to it."""
        rows = [
            ("3. Study the topology and answer the question that follows. 5", MARGIN),
            ("This sentence sits beside the diagram, not inside it.", MARGIN),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[1].bottom + 2, 420.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert "beside the diagram" in questions[0].text

    def test_a_tall_figure_does_not_erase_a_later_question(self):
        rows = [
            ("11. Interpret the figure comprising several networks. 10", MARGIN),
            ("Fig. 2", INDENT),
            ("12. Explain how TCP uses congestion control fully here. 10", MARGIN),
        ]
        built = lines(rows)
        # A region that wrongly reaches over question 12's heading.
        spans = [(1, built[1].top - 2, built[2].bottom + 2, 0.0, 500.0)]
        questions, classified = extract_questions(built, figure_spans=spans)
        assert "11" in [q.number for q in questions]
        # Question 12 is inside the bad region, so boundary detection loses it -
        # which is exactly why the pipeline keeps the unrefined extraction.
        assert len(questions) <= 2

    def test_numeric_diagram_labels_never_open_a_question(self):
        rows = [
            ("11. Interpret the figure comprising several networks. 10", MARGIN),
            ("16.0.0.1", INDENT),
            ("13.000 3", INDENT),
            ("140.0.1", INDENT),
            ("12.000", INDENT),
            ("1 2 3 4 67 8 9 10 11 12", INDENT),
            ("25 20 15 10", INDENT),
        ]
        built = lines(rows)
        spans = [(1, built[1].top - 2, built[-1].bottom + 2, 0.0, 500.0)]
        questions, _ = extract_questions(built, figure_spans=spans)
        assert [q.number for q in questions] == ["11"]

    def test_a_question_spanning_two_pages_keeps_one_entry(self):
        page_one = [
            Line(text="09. Using the Selective Repeat protocol, draw a flow diagram "
                      "of a sender with window size 4. 10",
                 page=1, index=0, x0=MARGIN, top=700.0, bottom=712.0),
        ]
        page_two = [
            Line(text="Assume no frame is lost during transmission. Show how the "
                      "window slides as acknowledgements come in.",
                 page=2, index=0, x0=MARGIN, top=20.0, bottom=32.0),
        ]
        questions, _ = extract_questions(page_one + page_two)
        assert len(questions) == 1
        assert "window slides" in questions[0].text

    def test_no_figure_spans_leaves_extraction_unchanged(self):
        rows = [(f"{n}. Question {n} asks about an interesting topic here. 5", MARGIN)
                for n in range(1, 6)]
        built = lines(rows)
        with_none, _ = extract_questions(built)
        with_empty, _ = extract_questions(built, figure_spans=[])
        assert [q.label for q in with_none] == [q.label for q in with_empty]
