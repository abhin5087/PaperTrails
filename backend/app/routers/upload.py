from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import MAX_UPLOAD_MB
from ..database import get_db
from ..schemas import PaperDetail
from ..serializers import to_detail
from ..services.ingest import run_pipeline

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=PaperDetail)
async def upload_paper(file: UploadFile, db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    body = await file.read()
    if len(body) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_MB}MB limit")
    if not body:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        paper = run_pipeline(db, body, file.filename)
    except Exception as exc:  # noqa: BLE001 - surface a clean 500 to the client
        raise HTTPException(500, f"Failed to process PDF: {exc}") from exc

    return to_detail(paper)
