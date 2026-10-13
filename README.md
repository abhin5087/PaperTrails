# PaperTrails

Extracts examination metadata, questions, marks and figures from exam paper
PDFs — including scans with no text layer at all.

## Running it

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API serves on `http://localhost:8000`; `/docs` has the OpenAPI UI.

**System packages.** Scanned papers need Tesseract and a PDF rasteriser:

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils
```

Without Tesseract the application still runs: native-text PDFs are unaffected,
and a scanned paper is reported with an `ocr_unavailable` diagnostic naming the
remedy rather than silently returning nothing.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Serves on `http://localhost:3000` and proxies `/api/*` to the backend. Point it
elsewhere with `BACKEND_URL`.

### Database

SQLite at `backend/papertrails.db`, created on first start.

Schema changes are applied automatically at startup by `app/migrations.py`,
which is **additive only** — it creates missing tables and adds missing columns
with `ALTER TABLE ... ADD COLUMN`, and never drops, renames or re-types
anything. Existing rows are preserved and every added column is nullable or
has a default, so an older build still reads the database. To apply a schema
change, just start the application.

To see what a migration *would* do without doing it:

```python
from sqlalchemy import create_engine
from app.migrations import pending_changes
print(pending_changes(create_engine("sqlite:///backend/papertrails.db")))
```

A column that cannot be added safely is reported under `blocked` and logged as
an error instead of being forced.

## How extraction works

`app/services/pipeline.py` builds several independent **candidates** — the
PDF's own text layer, plus one per Tesseract page-segmentation mode — and
chooses between them.

Each candidate **parses its own header from its own text**. This matters: a
header read from `pdf.pages[0].extract_text()` is empty on a scan even when OCR
read the page perfectly.

Candidates are selected on **structural quality** — contiguous question
numbering, header completeness, marks recovered, coherent text length, minus
penalties for duplicated and fragmented text — with engine confidence as a
supporting term only. Raw character confidence alone will happily pick a
fragmented read over a well-structured one.

| Module | Responsibility |
| --- | --- |
| `pipeline.py` | Builds and selects candidates, runs the whole extraction |
| `ocr.py` | Tesseract over rendered pages, word geometry in PDF points |
| `ocr_correction.py` | Conservative prose correction with protected tokens |
| `header.py` | Header fields across OCR damage and layout variation |
| `questions.py` | All question/subquestion boundary decisions |
| `marks.py` | Marks parsing, including values it refuses to resolve |
| `figure_detector.py` | Figure detection, association and cropping |
| `confidence.py` | Structural scoring and typed diagnostics |

### What it refuses to guess

- A mark is reported as a number only when the text supports it. `7+3` read as
  `743` is kept as `marks_raw` with `marks_resolved: false` and a reason, rather
  than resolved to a wrong number. Marks are never invented to make a total
  match the paper.
- A header field that cannot be read confidently is absent, not fabricated. The
  raw text and the reading used are kept in `header_detail`.
- A question label is recovered from damaged text only under strong structural
  evidence, and recovery is flagged on the question and in the diagnostics.

### Why diagram text does not become questions

Every boundary decision lives in `questions.classify_lines`. A line opens a
question only if it sits at the document's left margin, is followed by prose
rather than another number, is not part of a dotted-decimal run, is not inside
a detected figure, and fits the numbering sequence. IP octets (`16.0.0.1`),
subnet masks and graph axis ticks fail these and stay body text; text inside a
figure region is attributed to the figure instead of the question's wording.

### Figures

Three detectors run: clusters of drawn geometry, embedded images (excluding the
full-page scan itself), and — for pure scans, where there is no geometry to
inspect — regions of ink that no OCR word box explains. Each figure is grown to
cover its own labels, cropped to a PNG under `backend/storage/figures/`, and
attributed to the question it sits under. Crops are served from
`/api/figures/{id}/image`.

## Tests

```bash
cd backend
python -m pytest            # everything
python -m pytest -m golden  # whole-paper regression only
python -m pytest -m "not slow"
```

Tests use a throwaway SQLite file; `backend/papertrails.db` is never touched.

### Golden regression papers

`tests/test_extraction_regression.py` checks two reference papers end to end. It
uses the **real PDFs** when they are present:

```
backend/tests/fixtures/pdfs/BHUM103L-CAT-1-F2-2024-2025.pdf
backend/tests/fixtures/pdfs/BCSE308L-FAT-C2-2022-2023.pdf
```

Drop them in and the golden tests bind to them automatically. When they are
absent the suite falls back to generated surrogates that reproduce the same
failure modes — no text layer, OCR character confusion, lost `+` in marks sums,
IP addresses and axis ticks next to question text. `test_which_source_is_in_use`
prints which source ran, so a green suite is never mistaken for proof that the
real documents were checked.

Surrogates are built by `tests/fixtures/synthetic.py` and cached in
`tests/fixtures/generated/` (gitignored). Rebuild them with:

```bash
python tests/fixtures/synthetic.py tests/fixtures/generated
```
