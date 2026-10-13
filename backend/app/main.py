import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import init_db
from .routers import papers, stats, upload

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create missing tables and migrate existing ones before serving."""
    applied = init_db()
    if applied.get("added"):
        logger.info("Schema migrated: added %s", ", ".join(applied["added"]))
    if applied.get("blocked"):
        logger.error(
            "Schema changes needing manual attention: %s",
            ", ".join(applied["blocked"]),
        )
    yield


app = FastAPI(title="PaperTrails API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(papers.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
