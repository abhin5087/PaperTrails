# Validation results

Everything here was produced by running the code in the supplied project archive against two examination PDFs. This report summarizes the recorded results.

| File | What it is |
| --- | --- |
| `pytest-full-output.txt` | Full verbose test run, 330 tests |
| `real-pdf-extraction.txt` | Complete extraction dump for both real papers |
| `migration-check.txt` | Migration applied to a disposable populated legacy DB |
| `ui-verification.txt` | Browser-driven upload/reload check |
| `screenshots/` | Pages as rendered during that run |
| `figure-crops/` | Figure images cropped from the real BCSE308L scan |
| `environment.txt` | Versions used for the validation run |

## Important: the BHUM103L file is a different sitting

The brief described `BHUM103L-CAT-1-F2-2024-2025` — five questions, 50 marks. The supplied file is **`BHUM103L-FAT-A1-2023-2024`**: a Final Assessment Test, slot A1, November 2023, **ten questions, 100 marks**. Expectations were written against the document actually supplied.

## Results per paper

### BHUM103L-FAT-A1-2023-2024 (Micro Economics)

Image-only scan with no text layer (0 characters), so OCR carries everything including the header.

| | Result |
| --- | --- |
| Source | `scanned` → OCR, `psm6-block`, 86.9% mean confidence |
| Candidates compared | 4 (native unusable; psm6 chose 10 questions, psm4 8, psm3 2) |
| Top-level questions | **10** |
| Marks | 10 each → **100, matching the stated 100** |
| Marks provenance | `distribution` — paper states `(10 X 10 = 100 Marks)` once, not per question |
| Figures | 0 |
| Confidence | 82 (high) |

Header fields `course name`, `exam type` and `semester` were reported as not found rather than guessed. The course code reads `BHUM103` because OCR rendered the trailing `L` as a comma.

### BCSE308L-FAT-C2-2022-2023 (Computer Networks)

A scan carrying an OCR text layer, which itself contains OCR damage.

| | Result |
| --- | --- |
| Source | `ocr_text` → native text layer (corrected) |
| Top-level questions | **13** |
| Marks | Q1–Q6 = 5, Q7–Q13 = 10 → **100, matching the stated 100** |
| Multipart | Q9, Q10 and Q13 carry subparts |
| Figures | 6 regions detected and cropped, attributed to Q9/Q11/Q12/Q13 |
| Confidence | 90–98 (high) |

Handled OCR damage included a fused `1G.` recovered as question 10, labels fused to following words, mismatched mark brackets, and conservative correction of several misspelled words. Figure labels, IP addresses and axis ticks were not extracted as phantom questions.

## Tests

The recorded run reports **330 passed, 0 failed**. The golden suite identifies whether it used the real PDFs or generated surrogates.

## Database, API and frontend

- Migration applied to a disposable copy of a populated legacy database: 16 columns added, 3 tables created, 0 blocked, every row preserved; rerun was a no-op.
- API upload, list, detail, figure image, and 404/400 error paths were verified.
- Both real PDFs were uploaded through the browser UI. Results persisted after reload.

| | BHUM103L | BCSE308L |
| --- | ---: | ---: |
| Question rows rendered | 10 | 17 (13 + 4 subparts) |
| Rows after reload | 10 | 17 |
| Figures displayed | 0 | 6 |
| Broken images | 0 | 0 |
| Page identical after reload | yes | yes |

No 4xx/5xx responses were recorded. One console 404 was reported for `/favicon.ico`.

## Known limitations

1. Figure isolation on heavily photocopied scans is approximate; some regions are imprecise and explicitly tagged as approximate.
2. The BHUM103L header is partly unreadable and is reported as missing rather than guessed.
3. Subpart detection misses some markers fused to following words; those lines remain in the parent question text.
4. `course_code` for BHUM103L reads `BHUM103`, missing the trailing `L`.
