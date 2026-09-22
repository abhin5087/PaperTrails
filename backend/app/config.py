from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
PDF_DIR = STORAGE_DIR / "pdfs"
JSON_DIR = STORAGE_DIR / "json"

DATABASE_URL = f"sqlite:///{BASE_DIR / 'papertrails.db'}"
MAX_UPLOAD_MB = 25
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

for _d in (PDF_DIR, JSON_DIR):
    _d.mkdir(parents=True, exist_ok=True)
