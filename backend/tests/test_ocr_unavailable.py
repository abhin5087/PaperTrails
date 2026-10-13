"""Behaviour when no OCR engine is installed.

A scanned paper cannot be read without OCR.  The requirement is that the
application says so plainly rather than crashing, silently returning nothing,
or claiming a successful extraction.
"""

import pytest

from app.services import confidence, ocr, pipeline


@pytest.fixture
def no_tesseract(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    monkeypatch.setattr(ocr, "tesseract_version", lambda: None)


class TestScannedPaperWithoutOcr:
    def test_extraction_does_not_crash(self, bhum103l_pdf, no_tesseract):
        path, _ = bhum103l_pdf
        result = pipeline.extract(str(path))
        assert result.questions == []

    def test_summary_reports_the_engine_as_unavailable(self, bhum103l_pdf, no_tesseract):
        path, _ = bhum103l_pdf
        result = pipeline.extract(str(path))
        assert result.summary.ocr_attempted is True
        assert result.summary.ocr_available is False
        assert result.summary.ocr_used is False
        assert result.summary.source == "none"

    def test_diagnostic_names_the_remedy(self, bhum103l_pdf, no_tesseract):
        path, _ = bhum103l_pdf
        result = pipeline.extract(str(path))
        score = confidence.score(header=result.header, questions=result.questions,
                                 max_marks=None, summary=result.summary)
        codes = {d.code for d in score.diagnostics}
        assert "ocr_unavailable" in codes
        message = next(d.message for d in score.diagnostics
                       if d.code == "ocr_unavailable")
        assert "Install Tesseract" in message

    def test_confidence_is_low_not_falsely_high(self, bhum103l_pdf, no_tesseract):
        path, _ = bhum103l_pdf
        result = pipeline.extract(str(path))
        score = confidence.score(header=result.header, questions=result.questions,
                                 max_marks=None, summary=result.summary)
        assert score.level == "low"

    def test_upload_still_persists_a_paper_with_the_problem_recorded(
        self, client, bhum103l_pdf, no_tesseract
    ):
        path, _ = bhum103l_pdf
        with open(path, "rb") as handle:
            response = client.post(
                "/api/upload",
                files={"file": (path.name, handle, "application/pdf")},
            )
        assert response.status_code == 200
        paper = response.json()
        assert paper["question_count"] == 0
        assert paper["ocr_engine"] is None
        severities = {d["severity"] for d in paper["diagnostics"]}
        assert "error" in severities


class TestNativePaperWithoutOcr:
    def test_a_text_layer_paper_is_unaffected(self, bcse308l_pdf, no_tesseract):
        """OCR being absent must not degrade a paper that never needed it."""
        path, _ = bcse308l_pdf
        result = pipeline.extract(str(path))
        assert len(result.questions) == 13
        assert result.summary.source == "native_text"
        assert result.summary.ocr_attempted is False
