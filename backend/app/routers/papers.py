from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Figure, Paper
from ..schemas import PaperDetail, PaperSummary
from ..serializers import to_detail, to_summary

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers", response_model=list[PaperSummary])
def list_papers(db: Session = Depends(get_db)):
    papers = (
        db.query(Paper)
        .options(joinedload(Paper.course), joinedload(Paper.questions))
        .order_by(Paper.created_at.desc())
        .all()
    )
    return [to_summary(p) for p in papers]


@router.get("/papers/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = (
        db.query(Paper)
        .options(
            joinedload(Paper.course),
            joinedload(Paper.questions),
            joinedload(Paper.figures),
        )
        .filter(Paper.id == paper_id)
        .one_or_none()
    )
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return to_detail(paper)


@router.get("/figures/{figure_id}/image")
def get_figure_image(figure_id: int, db: Session = Depends(get_db)):
    """Serve a cropped figure image."""
    figure = db.query(Figure).filter(Figure.id == figure_id).one_or_none()
    if figure is None:
        raise HTTPException(404, "Figure not found")
    if not figure.image_path:
        raise HTTPException(404, "No image was produced for this figure")

    path = Path(figure.image_path)
    if not path.is_file():
        raise HTTPException(410, "Figure image is no longer available on disk")

    return FileResponse(path, media_type="image/png")
