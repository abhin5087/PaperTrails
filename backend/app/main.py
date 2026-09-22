from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import init_db
from .routers import papers, stats, upload

app = FastAPI(title="PaperTrails API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


app.include_router(upload.router)
app.include_router(papers.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
