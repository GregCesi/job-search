"""FastAPI — Zone A job-search."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .export import router as export_router
from .offers import router as offers_router

app = FastAPI(title="job-search-api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(offers_router)
app.include_router(export_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
