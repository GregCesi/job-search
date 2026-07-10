"""FastAPI — Zone A job-search."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import get_conn
from .export import router as export_router
from .offers import router as offers_router
from .traces import router as traces_router


def _migrate_db() -> None:
    """Ajoute les colonnes manquantes à la DB (idempotent)."""
    conn = get_conn()
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(offers)").fetchall()}
        for col, col_type in [
            ("rescored_at", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE offers ADD COLUMN {col} {col_type}")
        conn.commit()
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
