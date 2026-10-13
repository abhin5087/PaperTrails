"""Shared test fixtures.

Golden regression tests prefer the *real* exam papers.  Drop
``BHUM103L-CAT-1-F2-2024-2025.pdf`` and ``BCSE308L-FAT-C2-2022-2023.pdf``
into ``tests/fixtures/pdfs/`` and the golden tests bind to them
automatically.  When they are absent the suite falls back to generated
surrogates that reproduce the same failure modes, and says so.

Every database test runs against a throwaway SQLite file.  The application's
own ``papertrails.db`` is never opened, written or deleted by the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
REAL_PDF_DIR = FIXTURE_DIR / "pdfs"
GENERATED_DIR = FIXTURE_DIR / "generated"

#: Real file name -> generated surrogate name.
GOLDEN_PAPERS = {
    "bhum103l": ("BHUM103L-CAT-1-F2-2024-2025.pdf", "synthetic_bhum103l_scanned.pdf"),
    "bcse308l": ("BCSE308L-FAT-C2-2022-2023.pdf", "synthetic_bcse308l_networks.pdf"),
}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: runs OCR over a rendered PDF")
    config.addinivalue_line("markers", "golden: regression test against a whole paper")


@pytest.fixture(scope="session")
def generated_pdfs() -> dict[str, Path]:
    """Build the synthetic fixtures once per session."""
    from tests.fixtures import synthetic

    expected = {
        "bhum103l": GENERATED_DIR / "synthetic_bhum103l_scanned.pdf",
        "bcse308l": GENERATED_DIR / "synthetic_bcse308l_networks.pdf",
        "bcse308l_scanned": GENERATED_DIR / "synthetic_bcse308l_scanned.pdf",
    }
    if not all(p.exists() for p in expected.values()):
        synthetic.build_all(GENERATED_DIR)

    return expected


def resolve_paper(key: str, generated: dict[str, Path]) -> tuple[Path, bool]:
    """Return ``(path, is_real)`` for a golden paper."""
    real_name, _ = GOLDEN_PAPERS[key]
    real = REAL_PDF_DIR / real_name
    if real.is_file():
        return real, True
    return generated[key], False


@pytest.fixture(scope="session")
def bhum103l_pdf(generated_pdfs) -> tuple[Path, bool]:
    return resolve_paper("bhum103l", generated_pdfs)


@pytest.fixture(scope="session")
def bcse308l_pdf(generated_pdfs) -> tuple[Path, bool]:
    return resolve_paper("bcse308l", generated_pdfs)


@pytest.fixture(scope="session")
def bcse308l_scanned_pdf(generated_pdfs) -> Path:
    return generated_pdfs["bcse308l_scanned"]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """An isolated engine + session factory on a throwaway SQLite file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.database as database
    from app import models  # noqa: F401 - registers tables
    from app.migrations import run_migrations

    db_file = tmp_path / "papertrails_test.db"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    run_migrations(engine)

    yield engine, factory

    engine.dispose()


@pytest.fixture
def db_session(temp_db):
    _, factory = temp_db
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Redirect PDF/JSON/figure storage into the test's tmp directory."""
    import app.config as config
    import app.services.ingest as ingest

    pdf_dir = tmp_path / "pdfs"
    json_dir = tmp_path / "json"
    figure_dir = tmp_path / "figures"
    for directory in (pdf_dir, json_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(config, "JSON_DIR", json_dir)
    monkeypatch.setattr(config, "FIGURE_DIR", figure_dir)
    monkeypatch.setattr(ingest, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(ingest, "JSON_DIR", json_dir)
    monkeypatch.setattr(ingest, "FIGURE_DIR", figure_dir)

    return {"pdfs": pdf_dir, "json": json_dir, "figures": figure_dir}


@pytest.fixture
def client(temp_db, storage):
    """A TestClient wired to the isolated database."""
    from fastapi.testclient import TestClient

    import app.database as database
    from app.database import get_db
    from app.main import app

    _, factory = temp_db

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
