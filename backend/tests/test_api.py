"""API behaviour and persistence round-trips, on an isolated database."""

import pytest
from PIL import Image
from io import BytesIO


def upload(client, path):
    with open(path, "rb") as handle:
        return client.post(
            "/api/upload", files={"file": (path.name, handle, "application/pdf")}
        )


@pytest.fixture
def uploaded(client, bcse308l_pdf):
    path, _ = bcse308l_pdf
    response = upload(client, path)
    assert response.status_code == 200, response.text
    return response.json()


class TestHealthAndStats:
    def test_health(self, client):
        assert client.get("/api/health").json() == {"status": "ok"}

    def test_stats_on_an_empty_database(self, client):
        stats = client.get("/api/stats").json()
        assert stats["total_papers"] == 0
        assert stats["avg_confidence"] == 0

    def test_stats_reflect_an_upload(self, client, uploaded):
        stats = client.get("/api/stats").json()
        assert stats["total_papers"] == 1
        assert stats["total_courses"] == 1
        assert stats["total_questions"] >= 13


class TestUploadValidation:
    def test_non_pdf_is_rejected(self, client):
        response = client.post(
            "/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 400

    def test_empty_file_is_rejected(self, client):
        response = client.post(
            "/api/upload", files={"file": ("empty.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 400

    def test_malformed_pdf_returns_a_clean_error(self, client):
        response = client.post(
            "/api/upload",
            files={"file": ("broken.pdf", b"%PDF-1.4 not really a pdf",
                            "application/pdf")},
        )
        assert response.status_code == 500
        assert "Failed to process PDF" in response.json()["detail"]

    def test_a_failed_upload_leaves_no_paper_behind(self, client):
        client.post("/api/upload",
                    files={"file": ("broken.pdf", b"%PDF-1.4 junk", "application/pdf")})
        assert client.get("/api/papers").json() == []


class TestUploadResponse:
    def test_header_fields_are_returned(self, uploaded):
        assert uploaded["course_code"] == "BCSE308L"
        assert uploaded["exam_type"] == "Final Assessment Test"
        assert uploaded["max_marks"] == 100

    def test_question_count_excludes_subquestions(self, uploaded):
        assert uploaded["question_count"] == 13
        assert len(uploaded["questions"]) > uploaded["question_count"]

    def test_questions_carry_marks_raw(self, uploaded):
        for question in uploaded["questions"]:
            if question["marks"] is not None:
                assert question["marks_raw"] is not None

    def test_questions_declare_where_their_marks_came_from(self, uploaded):
        """A client must be able to tell a printed mark from a derived one."""
        for question in uploaded["questions"]:
            assert question["marks_source"] in ("printed", "distribution")

    def test_subquestions_declare_their_parent(self, uploaded):
        children = [q for q in uploaded["questions"] if q["parent_no"]]
        assert children
        parents = {q["question_no"] for q in uploaded["questions"]
                   if not q["parent_no"]}
        for child in children:
            assert child["parent_no"] in parents

    def test_diagnostics_are_typed(self, uploaded):
        assert uploaded["diagnostics"]
        for diagnostic in uploaded["diagnostics"]:
            assert diagnostic["severity"] in (
                "error", "warning", "unresolved", "info")
            assert diagnostic["code"] and diagnostic["message"]

    def test_notes_mirror_the_diagnostic_messages(self, uploaded):
        assert uploaded["notes"] == [d["message"] for d in uploaded["diagnostics"]]

    def test_extraction_detail_is_exposed(self, uploaded):
        assert uploaded["extraction_detail"]["candidates"]

    def test_header_detail_carries_raw_values(self, uploaded):
        fields = uploaded["header_detail"]["fields"]
        assert fields["course_code"]["raw"]
        assert fields["course_code"]["source"]

    def test_confidence_level_matches_the_score(self, uploaded):
        score, level = uploaded["confidence"], uploaded["confidence_level"]
        expected = "high" if score >= 80 else "medium" if score >= 50 else "low"
        assert level == expected


class TestPersistenceRoundTrip:
    def test_refetch_matches_the_upload_response(self, client, uploaded):
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        assert again == uploaded

    def test_questions_survive_a_reload(self, client, uploaded):
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        assert again["questions"] == uploaded["questions"]

    def test_marks_raw_survives_a_reload(self, client, uploaded):
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        originals = {q["question_no"]: q["marks_raw"] for q in uploaded["questions"]}
        reloaded = {q["question_no"]: q["marks_raw"] for q in again["questions"]}
        assert reloaded == originals

    def test_diagnostics_survive_a_reload(self, client, uploaded):
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        assert again["diagnostics"] == uploaded["diagnostics"]

    def test_figures_survive_a_reload(self, client, uploaded):
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        assert again["figures"] == uploaded["figures"]

    def test_figure_question_links_are_persisted(self, uploaded):
        assert uploaded["figures"]
        labels = {q["question_no"] for q in uploaded["questions"]}
        for figure in uploaded["figures"]:
            assert figure["question_no"] in labels

    def test_paper_appears_in_the_list(self, client, uploaded):
        papers = client.get("/api/papers").json()
        assert [p["id"] for p in papers] == [uploaded["id"]]
        assert papers[0]["question_count"] == uploaded["question_count"]

    def test_json_sidecar_is_written(self, client, uploaded, storage):
        sidecars = list(storage["json"].glob("paper_*.json"))
        assert len(sidecars) == 1


class TestFigureImages:
    def test_figure_image_is_served(self, client, uploaded):
        figure = next(f for f in uploaded["figures"] if f["image_url"])
        response = client.get(figure["image_url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as image:
            assert image.width > 50

    def test_unknown_figure_is_404(self, client, uploaded):
        assert client.get("/api/figures/9999/image").status_code == 404

    def test_missing_file_on_disk_is_410(self, client, uploaded, db_session):
        from app.models import Figure

        figure_id = uploaded["figures"][0]["id"]
        figure = db_session.query(Figure).filter(Figure.id == figure_id).one()
        figure.image_path = "/nonexistent/figure.png"
        db_session.commit()
        assert client.get(f"/api/figures/{figure_id}/image").status_code == 410


class TestLookupErrors:
    def test_unknown_paper_is_404(self, client):
        assert client.get("/api/papers/4242").status_code == 404


class TestScannedPaper:
    @pytest.mark.slow
    def test_scanned_upload_persists_ocr_metadata(self, client, bhum103l_pdf):
        path, is_real = bhum103l_pdf
        paper = upload(client, path).json()
        assert paper["pdf_type"] == "scanned"
        assert paper["ocr_engine"] == "tesseract"
        assert paper["ocr_config"]
        assert paper["ocr_confidence"] > 0
        # The real file is the 10-question FAT sitting; the surrogate models
        # the 5-question CAT-1 sitting.
        assert paper["question_count"] == (10 if is_real else 5)

        again = client.get(f"/api/papers/{paper['id']}").json()
        assert again["ocr_confidence"] == paper["ocr_confidence"]
        assert again["ocr_config"] == paper["ocr_config"]


class TestOptionalFields:
    def test_schema_tolerates_absent_optional_values(self, client, uploaded):
        """The frontend must never receive a missing key for an optional field."""
        required_keys = {
            "academic_year", "slot", "duration", "exam_date", "exam_time",
            "ocr_engine", "ocr_config", "ocr_confidence", "course_name",
            "diagnostics", "figures", "header_detail", "extraction_detail",
        }
        assert required_keys <= set(uploaded)


class TestFigureSerialization:
    """Merged figures must reach the API intact and without duplicates."""

    def test_each_figure_appears_once(self, uploaded):
        ids = [f["id"] for f in uploaded["figures"]]
        assert len(ids) == len(set(ids))

    def test_no_two_stored_figures_describe_the_same_region(self, client, uploaded,
                                                            db_session):
        from app.models import Figure
        from app.services import figure_geometry as geo

        rows = db_session.query(Figure).filter(
            Figure.paper_id == uploaded["id"]).all()
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a.page != b.page:
                    continue
                overlap = geo.describe((a.x0, a.top, a.x1, a.bottom),
                                       (b.x0, b.top, b.x1, b.bottom))
                assert overlap.containment < 0.6, "duplicate region persisted"

    def test_provenance_is_exposed(self, uploaded):
        for figure in uploaded["figures"]:
            assert figure["sources"], "figure lost its detector provenance"
            assert isinstance(figure["clipped_edges"], list)

    def test_question_links_point_at_real_questions(self, uploaded):
        labels = {q["question_no"] for q in uploaded["questions"]}
        for figure in uploaded["figures"]:
            if figure["question_no"] is not None:
                assert figure["question_no"] in labels

    def test_grouping_is_stable_across_reloads(self, client, uploaded):
        """Reopening the paper must produce the same grouping."""
        first = [(f["question_no"], f["page"], f["image_url"])
                 for f in uploaded["figures"]]
        again = client.get(f"/api/papers/{uploaded['id']}").json()
        second = [(f["question_no"], f["page"], f["image_url"])
                  for f in again["figures"]]
        assert first == second

    def test_reprocessing_the_same_pdf_gives_the_same_figures(self, client,
                                                              bcse308l_pdf):
        path, _ = bcse308l_pdf
        shapes = []
        for _ in range(2):
            with open(path, "rb") as handle:
                response = client.post(
                    "/api/upload",
                    files={"file": (path.name, handle, "application/pdf")},
                )
            assert response.status_code == 200
            shapes.append([
                (f["page"], f["question_no"], f["kind"])
                for f in response.json()["figures"]
            ])
        assert shapes[0] == shapes[1]
