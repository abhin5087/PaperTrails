from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Paper
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
        .options(joinedload(Paper.course), joinedload(Paper.questions))
        .filter(Paper.id == paper_id)
        .one_or_none()
    )
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return to_detail(paper)
