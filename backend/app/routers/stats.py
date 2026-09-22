from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Course, Paper, Question
from ..schemas import Stats

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=Stats)
def get_stats(db: Session = Depends(get_db)):
    total_papers = db.query(func.count(Paper.id)).scalar() or 0
    total_questions = db.query(func.count(Question.id)).scalar() or 0
    total_courses = db.query(func.count(Course.id)).scalar() or 0
    avg_confidence = db.query(func.avg(Paper.confidence)).scalar() or 0

    return Stats(
        total_papers=total_papers,
        total_questions=total_questions,
        total_courses=total_courses,
        avg_confidence=round(avg_confidence),
    )
