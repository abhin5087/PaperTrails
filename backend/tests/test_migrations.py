"""Schema migrations must be additive and never lose data."""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401 - registers tables
from app.migrations import pending_changes, run_migrations

LEGACY_SCHEMA = """
CREATE TABLE courses (
  id INTEGER PRIMARY KEY, code VARCHAR(32) UNIQUE, name VARCHAR(255),
  created_at DATETIME);
CREATE TABLE papers (
  id INTEGER PRIMARY KEY, course_id INTEGER, original_filename VARCHAR(255),
  pdf_path VARCHAR(512), json_path VARCHAR(512), pdf_type VARCHAR(16),
  extraction_method VARCHAR(32), exam_type VARCHAR(128), semester VARCHAR(64),
  academic_year VARCHAR(32), slot VARCHAR(32), max_marks INTEGER,
  duration VARCHAR(64), exam_date VARCHAR(32), marks_extracted INTEGER,
  confidence INTEGER, confidence_breakdown JSON, notes JSON, created_at DATETIME);
CREATE TABLE questions (
  id INTEGER PRIMARY KEY, paper_id INTEGER, question_no VARCHAR(16), text TEXT,
  marks INTEGER, module VARCHAR(16), co VARCHAR(16), bl VARCHAR(16),
  page INTEGER, cluster_id INTEGER);
INSERT INTO courses VALUES (1,'BHUM103L','Microeconomics','2024-01-01');
INSERT INTO papers VALUES
  (1,1,'old.pdf','/x.pdf',NULL,'scanned','none','CAT-1','Winter','2024-2025',
   'F2',50,'90 Minutes','16-02-2024',50,61,'{}','["legacy note"]','2024-01-01');
INSERT INTO questions VALUES
  (1,1,'1','Legacy question text',10,NULL,NULL,NULL,1,NULL);
"""


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA)
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def legacy_engine(legacy_db):
    engine = create_engine(f"sqlite:///{legacy_db}")
    yield engine
    engine.dispose()


class TestPlanning:
    def test_plan_reports_work_without_doing_it(self, legacy_engine):
        plan = pending_changes(legacy_engine)
        assert "figures" in plan["create_table"]
        assert "questions.marks_raw" in plan["add_column"]
        assert "papers.diagnostics" in plan["add_column"]
        # Nothing applied yet.
        columns = {c["name"] for c in inspect(legacy_engine).get_columns("questions")}
        assert "marks_raw" not in columns

    def test_nothing_is_blocked(self, legacy_engine):
        assert pending_changes(legacy_engine)["blocked"] == []


class TestApplying:
    def test_new_columns_are_added(self, legacy_engine):
        run_migrations(legacy_engine)
        inspector = inspect(legacy_engine)

        question_columns = {c["name"] for c in inspector.get_columns("questions")}
        assert {"marks_raw", "marks_parts", "marks_resolved", "marks_reason",
                "parent_no", "recovered_label"} <= question_columns

        paper_columns = {c["name"] for c in inspector.get_columns("papers")}
        assert {"diagnostics", "header_detail", "extraction_detail", "ocr_engine",
                "ocr_config", "ocr_confidence", "page_count",
                "exam_time"} <= paper_columns

    def test_new_tables_are_created(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "figures" in inspect(legacy_engine).get_table_names()

    def test_existing_rows_survive(self, legacy_engine):
        run_migrations(legacy_engine)
        with legacy_engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM papers")).scalar() == 1
            assert connection.execute(
                text("SELECT COUNT(*) FROM questions")).scalar() == 1
            row = connection.execute(
                text("SELECT original_filename, notes, max_marks, confidence "
                     "FROM papers WHERE id = 1")
            ).one()
            assert row == ("old.pdf", '["legacy note"]', 50, 61)

    def test_existing_question_values_are_untouched(self, legacy_engine):
        run_migrations(legacy_engine)
        with legacy_engine.connect() as connection:
            row = connection.execute(
                text("SELECT question_no, text, marks FROM questions WHERE id = 1")
            ).one()
            assert row == ("1", "Legacy question text", 10)

    def test_added_columns_read_as_empty_for_legacy_rows(self, legacy_engine):
        run_migrations(legacy_engine)
        with legacy_engine.connect() as connection:
            row = connection.execute(
                text("SELECT marks_raw, marks_resolved, parent_no "
                     "FROM questions WHERE id = 1")
            ).one()
            assert row[0] is None
            assert not row[1]
            assert row[2] is None

    def test_running_twice_is_a_no_op(self, legacy_engine):
        run_migrations(legacy_engine)
        again = run_migrations(legacy_engine)
        assert again == {"added": [], "blocked": []}

    def test_no_table_is_ever_dropped(self, legacy_engine):
        before = set(inspect(legacy_engine).get_table_names())
        run_migrations(legacy_engine)
        after = set(inspect(legacy_engine).get_table_names())
        assert before <= after


class TestFreshDatabase:
    def test_empty_database_gets_the_full_schema(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        run_migrations(engine)
        tables = set(inspect(engine).get_table_names())
        assert {"courses", "papers", "questions", "figures"} <= tables
        engine.dispose()
