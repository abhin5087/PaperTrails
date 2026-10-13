import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
PDF_DIR = STORAGE_DIR / "pdfs"
JSON_DIR = STORAGE_DIR / "json"
FIGURE_DIR = STORAGE_DIR / "figures"

# Overridable so a test or a verification run can point at a throwaway
# database instead of the one holding real papers.
DATABASE_URL = os.environ.get(
    "PAPERTRAILS_DATABASE_URL", f"sqlite:///{BASE_DIR / 'papertrails.db'}"
)

# Storage can be redirected the same way.
if _root := os.environ.get("PAPERTRAILS_STORAGE_DIR"):
    STORAGE_DIR = Path(_root)
    PDF_DIR = STORAGE_DIR / "pdfs"
    JSON_DIR = STORAGE_DIR / "json"
    FIGURE_DIR = STORAGE_DIR / "figures"
MAX_UPLOAD_MB = 25
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

for _d in (PDF_DIR, JSON_DIR, FIGURE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
