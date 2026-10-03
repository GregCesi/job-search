"""FastAPI — Zone A job-search."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.job_search.storage.db import init_db

from .ajouts import router as ajouts_router
from .cv import router as cv_router
from .db import get_conn
from .expiration import router as expiration_router
from .export import router as export_router
from .fiche import router as fiche_router
from .lettre import router as lettre_router
from .mail import router as mail_router
from .offers import router as offers_router
from .pieces import router as pieces_router
from .traces import router as traces_router


def _migrate_db() -> None:
    """Crée les tables manquantes et ajoute les colonnes manquantes (idempotent) —
    la même fonction que le pipeline, pour que l'API n'attende plus un run
    orchestrator avant de pouvoir servir `cvs` / `cv_corrections` (EXE-63 critères 7-8).
    """
    conn = get_conn()
    try:
        init_db(conn)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _migrate_db()
    yield


app = FastAPI(title="job-search-api", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(offers_router)
app.include_router(export_router)
app.include_router(traces_router)
app.include_router(fiche_router)
app.include_router(cv_router)
app.include_router(lettre_router)
app.include_router(mail_router)
app.include_router(pieces_router)
app.include_router(expiration_router)
app.include_router(ajouts_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
