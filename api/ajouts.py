"""Endpoints d'ajout à la main d'une offre par son URL ou son texte (EXE-79, EXE-82).

Même motif que la fiche entreprise, le CV et la lettre : POST répond tout de suite
(202, état « en_cours »), le traitement tourne en tâche de fond, GET lit l'état. Un
ajout resté « en_cours » sans tâche vivante (API redémarrée) se lit « echec ».

Le traitement est synchrone (lecture de page, extraction Ollama) : il tourne dans un
thread pour ne pas bloquer la boucle de l'API.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from orchestrator.job_search.ajout.service import create_ajout as _create_ajout
from orchestrator.job_search.ajout.service import run_ajout
from orchestrator.job_search.sources.manual import ManualSource

from .db import get_conn

router = APIRouter(prefix="/ajouts")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()

_ORPHELIN = "Ajout interrompu (API redémarrée pendant le traitement). Le relancer."


class AjoutIn(BaseModel):
    """L'URL seule, ou le texte collé de l'offre avec ou sans URL. Titre, entreprise
    et lieu sont facultatifs : sans titre, l'appel d'identification le cherche."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    texte: str | None = None
    titre: str | None = None
    entreprise: str | None = None
    lieu: str | None = None

    @field_validator("url")
    @classmethod
    def _url_nettoyee(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("texte")
    @classmethod
    def _texte_non_blanc(cls, v: str | None) -> str | None:
        return v if v is not None and v.strip() else None

    @model_validator(mode="after")
    def _url_ou_texte(self) -> "AjoutIn":
        if self.url is None and self.texte is None:
            raise ValueError("Une URL ou le texte de l'offre est obligatoire")
        return self


def _row_to_ajout(row) -> dict:
    ajout = {
        "id": row["id"],
        "url": row["url"],
        "texte": row["texte"],
        "statut": row["statut"],
        "offer_id": row["offer_id"],
        "categorie": row["categorie"],
        "raison": row["raison"],
        "causes": json.loads(row["causes_json"]) if row["causes_json"] else [],
        "message": row["message"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }
    if ajout["statut"] == "en_cours" and ajout["id"] not in _running:
        # Ajout orphelin (API redémarrée en cours de route) : jamais « en cours » indéfiniment.
        ajout["statut"] = "echec"
        ajout["message"] = _ORPHELIN
    return ajout


async def _process(ajout_id: int, source: ManualSource) -> None:
    try:
        await asyncio.to_thread(run_ajout, ajout_id, source)
    finally:
        _running.discard(ajout_id)


@router.post("")
async def create_ajout(body: AjoutIn, response: Response) -> dict:
    source = ManualSource(
        body.url,
        texte=body.texte,
        titre=body.titre,
        entreprise=body.entreprise,
        lieu=body.lieu,
    )
    with get_conn() as conn:
        ajout_id = _create_ajout(conn, body.url, body.texte)
    _running.add(ajout_id)
    task = asyncio.create_task(_process(ajout_id, source))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    response.status_code = 202
    return {"id": ajout_id, "statut": "en_cours", "url": body.url}


@router.get("")
def list_ajouts() -> list[dict]:
    """Les ajouts des dernières 24 heures, du plus récent au plus ancien."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(
        timespec="seconds"
    )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ajouts WHERE created_at >= ? ORDER BY id DESC", (since,)
        ).fetchall()
    return [_row_to_ajout(r) for r in rows]


@router.get("/{ajout_id}")
def get_ajout(ajout_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ajouts WHERE id = ?", (ajout_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ajout inconnu")
    return _row_to_ajout(row)
