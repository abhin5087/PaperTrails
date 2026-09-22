from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    papers: Mapped[list["Paper"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    topic_clusters: Mapped[list["TopicCluster"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )

    original_filename: Mapped[str] = mapped_column(String(255))
    pdf_path: Mapped[str] = mapped_column(String(512))
    json_path: Mapped[str | None] = mapped_column(String(512))

    pdf_type: Mapped[str] = mapped_column(String(16))  # vector | ocr_text | scanned
    extraction_method: Mapped[str] = mapped_column(String(32))

    exam_type: Mapped[str | None] = mapped_column(String(128))
    semester: Mapped[str | None] = mapped_column(String(64))
    academic_year: Mapped[str | None] = mapped_column(String(32))
    slot: Mapped[str | None] = mapped_column(String(32))
    max_marks: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[str | None] = mapped_column(String(64))
    exam_date: Mapped[str | None] = mapped_column(String(32))

    marks_extracted: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    confidence_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    course: Mapped[Course] = relationship(back_populates="papers")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="Question.id",
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    question_no: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    marks: Mapped[int | None] = mapped_column(Integer)
    module: Mapped[str | None] = mapped_column(String(16))
    co: Mapped[str | None] = mapped_column(String(16))
    bl: Mapped[str | None] = mapped_column(String(16))
    page: Mapped[int | None] = mapped_column(Integer)

    # Future: set once topic clustering exists.
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic_clusters.id", ondelete="SET NULL"), index=True
    )

    paper: Mapped[Paper] = relationship(back_populates="questions")
    cluster: Mapped["TopicCluster | None"] = relationship(back_populates="questions")
    embedding: Mapped["QuestionEmbedding | None"] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )


class QuestionEmbedding(Base):
    """Schema only - nothing writes to this table yet."""

    __tablename__ = "question_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, index=True
    )
    model: Mapped[str] = mapped_column(String(128))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # packed float32
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    question: Mapped[Question] = relationship(back_populates="embedding")


class TopicCluster(Base):
    """Schema only - nothing writes to this table yet."""

    __tablename__ = "topic_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    centroid: Mapped[bytes | None] = mapped_column(LargeBinary)
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    course: Mapped[Course] = relationship(back_populates="topic_clusters")
    questions: Mapped[list[Question]] = relationship(back_populates="cluster")
